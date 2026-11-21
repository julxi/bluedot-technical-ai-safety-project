"""Bayesian model of vast.ai hosts, learned from the rental history (records.py). Pure numpy.

What is modelled, and why (design: convos/julian/26-11-18_vast_host_selection_LOG.md, entry
*design: discounted hierarchical Bayesian host model, ...*):

- Pull speed. theta_h = log of host h's pull speed in MB/s (download + unpack of the image).
  Hierarchical: theta_h ~ Normal(alpha + beta * x_h, tau^2), x_h = log(advertised Mbit/s / 1000).
  One rental's speed: y ~ Normal(theta_h, sigma^2) - sigma is a host's day-to-day variation.
  alpha, beta, tau, sigma are shared across hosts and learned from all of them, so a host we never
  rented starts from what its advertised speed has meant for other hosts.
- Overhead (pull end -> ready: vast.ai's build step, ssh, sync): log-normal, pooled over hosts.
- Image cache: probability pi that a host which ran the image within the cache window still has
  it (pull skipped). Pooled; the prior is sceptical, because it is unknown whether hosts keep it.
- Failure (no usable machine: dead, vanished, DNS, boot timeout, stall, ssh): p_h per host,
  Beta-Bernoulli around a pooled mean m. Approximation: m is learned from all observations pooled
  and the prior strength KAPPA is fixed, rather than a full hierarchical fit.

Discounting: each observation enters with weight w = 0.5 ** (age_days / half_life) - a power
likelihood. As weights fade, a host's posterior widens back to the population prior. That is how
a bad day is forgiven and a bad host is eventually tried again, with no hard cut (Julian,
26-11-18). The conjugate updates below simply use w-weighted sums.

Speeds are re-derived from each attempt's recorded polls (pull.replay), not taken from the stored
pull stats, so fixes to the pull parser apply to the whole history. A finished pull gives its
exact speed. An unfinished one (aborted, failed mid-pull) gives an interval: its average speed so
far lay between the unpacked bytes and those plus the next layer, over the time taken
(pull.SpeedBounds). Such a censored observation is sampled as a latent value truncated to that
interval (data augmentation in the Gibbs sampler). Approximation: the speed so far stands in for
the whole pull's, which a slow start understates (the interval's top is generous, which helps).
Before 26-11-18 the lower end was used as if exact, and a decaying live speed made healthy hosts
look slow (live tests, convos/julian/26-11-18_vast_host_selection_LOG.md).
"""

import math
from collections.abc import Sequence
from typing import NamedTuple

import numpy as np
from scipy.stats import truncnorm

from ic_eval.vast.pull import replay
from ic_eval.vast.records import HOST_FAILURES, Attempt, End

# Advertised download speed that x_h = 0 corresponds to.
ADVERTISED_REFERENCE_MBPS = 1000.0
# Priors (hand-set and weak). The two rentals of 26-11-18 pulled (download + unpack) at 8.8 and
# 35 MB/s on hosts advertising 309 and 9415 Mbit/s: tens of MB/s, loosely tied to the advert.
ALPHA_PRIOR = (
    math.log(30.0),
    1.0,
)  # (mean, sd) of log MB/s at the reference advertised speed
BETA_PRIOR = (
    0.3,
    0.3,
)  # (mean, sd): 10x advertised speed -> about 2x real speed a priori
TAU2_PRIOR = (
    2.0,
    0.5,
)  # inverse gamma (shape, scale): hosts differ by ~2x around the regression
SIGMA2_PRIOR = (2.0, 0.1)  # inverse gamma: a host's day-to-day spread ~1.35x
OVERHEAD_PRIOR = (
    math.log(1.0),
    1.0,
    2.0,
    0.2,
)  # normal-inverse-gamma: mu0 (log min), k0, a0, b0
CACHE_PRIOR = (
    1.0,
    3.0,
)  # beta: a priori 25% chance a recently used host still has the image
FAILURE_MEAN_PRIOR = (1.0, 9.0)  # beta for the pooled failure rate: a priori 10%
FAILURE_KAPPA = 5.0  # prior strength of a host's failure rate around the pooled mean


class SpeedObs(NamedTuple):
    """One pull's log speed (log MB/s); censored if log_speed_max is set: then the true value
    lies in [log_speed, log_speed_max], and log_speed may be -inf (nothing unpacked yet)."""

    host_id: int
    log_speed: float
    age_days: float
    log_speed_max: float | None = None


class FlagObs(NamedTuple):
    """A yes/no observation: a failure (per host) or a cache hit (pooled)."""

    host_id: int
    flag: bool
    age_days: float


class OverheadObs(NamedTuple):
    log_minutes: float
    age_days: float


class Observations(NamedTuple):
    speed: list[SpeedObs]
    failure: list[FlagObs]
    overhead: list[OverheadObs]
    cache: list[FlagObs]
    advertised_mbps: dict[int, float]  # latest advertised download per host seen in the history


class HostDraws(NamedTuple):
    """Posterior draws for one host, aligned with the shared draws (index k = one joint draw)."""

    log_speed: np.ndarray  # (K,) theta_h
    failure_prob: np.ndarray  # (K,) p_h
    effective_observations: float  # discounted speed + failure observations


class Posterior(NamedTuple):
    alpha: np.ndarray  # (K,)
    beta: np.ndarray
    tau2: np.ndarray
    sigma2: np.ndarray
    theta: dict[int, np.ndarray]  # (K,) for hosts with speed observations
    overhead_mu: np.ndarray  # (K,) log minutes
    overhead_sigma2: np.ndarray
    cache_pi: np.ndarray
    failure_mean: np.ndarray  # (K,) pooled failure rate m
    failure_counts: dict[int, tuple[float, float]]  # host -> (weighted failures, successes)
    speed_weight: dict[int, float]  # host -> summed speed weights


def observations_from_records(
    records: Sequence[Attempt | End],
    now: float,
    cache_window_days: float,
    min_censored_pull_s: float,
) -> Observations:
    """Turn the rental history into model observations (see the module docstring).

    Pulls are replayed from the recorded polls. An unfinished pull becomes a censored speed only
    after min_censored_pull_s (the abort warm-up): in its first seconds, connection setup makes
    even the upper bound meaninglessly low. An attempt without polls (a crash of ours inside the
    boot loop) gives no speed, overhead or cache observation.
    """
    attempts = sorted((r for r in records if isinstance(r, Attempt)), key=lambda a: a.created_at)
    speed: list[SpeedObs] = []
    failure: list[FlagObs] = []
    overhead: list[OverheadObs] = []
    cache: list[FlagObs] = []
    advertised: dict[int, float] = {}
    # (host, image) -> time a rental there became ready, for cache eligibility
    last_ready: dict[tuple[int, str], float] = {}
    for a in attempts:
        host = int(a.offer["host_id"])
        age = (now - a.created_at) / 86400
        assert age >= 0, f"attempt {a.instance_id} is in the future"
        advertised[host] = float(a.offer["inet_down"])
        tracker = replay(a.image_layers, a.polls) if a.polls else None
        bounds = tracker.speed_bounds(a.polls[-1].t) if tracker is not None else None
        if bounds is not None and bounds.exact:
            speed.append(SpeedObs(host, math.log(bounds.low_mb_s), age))
        elif bounds is not None and bounds.elapsed_s >= min_censored_pull_s:
            low = math.log(bounds.low_mb_s) if bounds.low_mb_s > 0 else -math.inf
            speed.append(SpeedObs(host, low, age, log_speed_max=math.log(bounds.high_mb_s)))
        if a.outcome == "ready":
            failure.append(FlagObs(host, False, age))
            assert a.ready_at is not None
            pull_end = tracker.ended_at if tracker is not None else None
            start = pull_end if pull_end is not None else a.created_at
            overhead_min = (a.ready_at - start) / 60
            assert overhead_min > 0, f"attempt {a.instance_id}: non-positive overhead"
            overhead.append(OverheadObs(math.log(overhead_min), age))
        elif a.outcome == "failed" and a.failure_type in HOST_FAILURES:
            failure.append(FlagObs(host, True, age))
        # Whether the image was cached is known once bytes were downloaded (no), or the boot got
        # past the pull without a download (yes; a cached boot can go straight to "running" with
        # no pull message at all, test 3 on 26-11-18). A boot that failed before says nothing.
        cache_known = tracker is not None and (
            tracker.downloaded
            or tracker.ended_at is not None
            or any(p.status == "running" for p in a.polls)
        )
        previous = last_ready.get((host, a.image))
        if (
            cache_known
            and previous is not None
            and (a.created_at - previous) / 86400 <= cache_window_days
        ):
            assert tracker is not None
            cache.append(FlagObs(host, not tracker.downloaded, age))
        if a.outcome == "ready":
            assert a.ready_at is not None
            last_ready[(host, a.image)] = a.ready_at
    return Observations(speed, failure, overhead, cache, advertised)


def cache_eligible_hosts(
    records: Sequence[Attempt | End], image: str, now: float, window_days: float
) -> set[int]:
    """Hosts on which this image was ready within the cache window, so they may still have it."""
    return {
        int(r.offer["host_id"])
        for r in records
        if isinstance(r, Attempt)
        and r.image == image
        and r.ready_at is not None
        and (now - r.ready_at) / 86400 <= window_days
    }


def discount(age_days: float, half_life_days: float) -> float:
    return 0.5 ** (age_days / half_life_days)


def fit(
    obs: Observations,
    speed_half_life_days: float,
    failure_half_life_days: float,
    n_draws: int,
    iterations: int,
    burn_in: int,
    rng: np.random.Generator,
) -> Posterior:
    """Sample the posterior: a Gibbs sampler for the speed model, conjugate draws for the rest."""
    assert iterations - burn_in >= n_draws, "not enough post-burn-in iterations for n_draws"
    alpha, beta, tau2, sigma2, theta = _fit_speed(
        obs, speed_half_life_days, n_draws, iterations, burn_in, rng
    )
    overhead_mu, overhead_sigma2 = _fit_overhead(obs.overhead, speed_half_life_days, n_draws, rng)
    cache_w = [(discount(c.age_days, speed_half_life_days), c.flag) for c in obs.cache]
    cache_pi = rng.beta(
        CACHE_PRIOR[0] + sum(w for w, hit in cache_w if hit),
        CACHE_PRIOR[1] + sum(w for w, hit in cache_w if not hit),
        size=n_draws,
    )
    counts: dict[int, tuple[float, float]] = {}
    for f in obs.failure:
        w = discount(f.age_days, failure_half_life_days)
        failed, succeeded = counts.get(f.host_id, (0.0, 0.0))
        counts[f.host_id] = (failed + w * f.flag, succeeded + w * (not f.flag))
    total_failed = sum(c[0] for c in counts.values())
    total_succeeded = sum(c[1] for c in counts.values())
    failure_mean = rng.beta(
        FAILURE_MEAN_PRIOR[0] + total_failed,
        FAILURE_MEAN_PRIOR[1] + total_succeeded,
        n_draws,
    )
    speed_weight: dict[int, float] = {}
    for s in obs.speed:
        speed_weight[s.host_id] = speed_weight.get(s.host_id, 0.0) + discount(
            s.age_days, speed_half_life_days
        )
    return Posterior(
        alpha=alpha,
        beta=beta,
        tau2=tau2,
        sigma2=sigma2,
        theta=theta,
        overhead_mu=overhead_mu,
        overhead_sigma2=overhead_sigma2,
        cache_pi=cache_pi,
        failure_mean=failure_mean,
        failure_counts=counts,
        speed_weight=speed_weight,
    )


def host_draws(
    posterior: Posterior, host_id: int, advertised_mbps: float, rng: np.random.Generator
) -> HostDraws:
    """Draws of one host's log speed and failure probability, joint with the shared draws.

    A host without speed observations gets theta from the population regression at its current
    advertised speed; one with observations keeps its sampled theta (whose prior used the
    advertised speed at fit time).
    """
    assert advertised_mbps > 0, f"host {host_id}: advertised download {advertised_mbps}"
    k = len(posterior.alpha)
    if host_id in posterior.theta:
        log_speed = posterior.theta[host_id]
    else:
        x = math.log(advertised_mbps / ADVERTISED_REFERENCE_MBPS)
        mean = posterior.alpha + posterior.beta * x
        log_speed = mean + np.sqrt(posterior.tau2) * rng.standard_normal(k)
    failed, succeeded = posterior.failure_counts.get(host_id, (0.0, 0.0))
    m = posterior.failure_mean
    failure_prob = rng.beta(FAILURE_KAPPA * m + failed, FAILURE_KAPPA * (1 - m) + succeeded)
    return HostDraws(
        log_speed=log_speed,
        failure_prob=failure_prob,
        effective_observations=posterior.speed_weight.get(host_id, 0.0) + failed + succeeded,
    )


def _fit_speed(
    obs: Observations,
    half_life_days: float,
    n_draws: int,
    iterations: int,
    burn_in: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[int, np.ndarray]]:
    """Gibbs sampler for (theta_h, alpha, beta, tau^2, sigma^2); every conditional is conjugate.

    With no speed observations at all the posterior is the prior, drawn directly.
    """
    if not obs.speed:
        alpha = rng.normal(ALPHA_PRIOR[0], ALPHA_PRIOR[1], n_draws)
        beta = rng.normal(BETA_PRIOR[0], BETA_PRIOR[1], n_draws)
        tau2 = _inv_gamma(TAU2_PRIOR[0], TAU2_PRIOR[1], n_draws, rng)
        sigma2 = _inv_gamma(SIGMA2_PRIOR[0], SIGMA2_PRIOR[1], n_draws, rng)
        return alpha, beta, tau2, sigma2, {}

    hosts = sorted({s.host_id for s in obs.speed})
    index = {h: i for i, h in enumerate(hosts)}
    n_hosts = len(hosts)
    host_of = np.array([index[s.host_id] for s in obs.speed])
    w = np.array([discount(s.age_days, half_life_days) for s in obs.speed])
    # Censored observations: latent values in [lo, hi], redrawn every iteration (data augmentation).
    censored = np.array([s.log_speed_max is not None for s in obs.speed])
    lo = np.array([s.log_speed for s in obs.speed])
    hi = np.array([s.log_speed if s.log_speed_max is None else s.log_speed_max for s in obs.speed])
    assert np.all(lo <= hi) and np.all(np.isfinite(hi)), "speed interval malformed"
    # start inside the interval: its top when it is open below, else its middle
    y = np.where(censored & ~np.isfinite(lo), hi, (np.where(np.isfinite(lo), lo, hi) + hi) / 2)
    for h in hosts:
        assert h in obs.advertised_mbps and obs.advertised_mbps[h] > 0, f"host {h}: no advert"
    x = np.log(np.array([obs.advertised_mbps[h] for h in hosts]) / ADVERTISED_REFERENCE_MBPS)
    design = np.column_stack([np.ones(n_hosts), x])  # (H, 2)
    prior_mean = np.array([ALPHA_PRIOR[0], BETA_PRIOR[0]])
    prior_precision = np.diag([1 / ALPHA_PRIOR[1] ** 2, 1 / BETA_PRIOR[1] ** 2])

    w_sum = np.bincount(host_of, weights=w, minlength=n_hosts)  # (H,)
    wy_sum = np.bincount(host_of, weights=w * y, minlength=n_hosts)
    theta = wy_sum / w_sum
    coef = prior_mean.copy()
    tau2 = TAU2_PRIOR[1] / (TAU2_PRIOR[0] - 1)
    sigma2 = SIGMA2_PRIOR[1] / (SIGMA2_PRIOR[0] - 1)

    keep_every = (iterations - burn_in) // n_draws
    kept = {"alpha": [], "beta": [], "tau2": [], "sigma2": [], "theta": []}
    for it in range(iterations):
        if censored.any():
            # y_i | theta, sigma2 for censored i: normal truncated to its interval
            mean_c = theta[host_of[censored]]
            sd_c = np.sqrt(sigma2 / w[censored])
            y[censored] = truncnorm.rvs(
                (lo[censored] - mean_c) / sd_c,
                (hi[censored] - mean_c) / sd_c,
                loc=mean_c,
                scale=sd_c,
                random_state=rng,
            )
            wy_sum = np.bincount(host_of, weights=w * y, minlength=n_hosts)
        # theta_h | rest: normal, precision-weighted between the regression and the host's data
        mean_prior = design @ coef
        precision = 1 / tau2 + w_sum / sigma2
        mean = (mean_prior / tau2 + wy_sum / sigma2) / precision
        theta = mean + rng.standard_normal(n_hosts) / np.sqrt(precision)
        # (alpha, beta) | theta, tau2: Bayesian linear regression with known variance
        post_precision = prior_precision + design.T @ design / tau2
        post_cov = np.linalg.inv(post_precision)
        post_mean = post_cov @ (prior_precision @ prior_mean + design.T @ theta / tau2)
        coef = rng.multivariate_normal(post_mean, post_cov)
        # tau2 | theta, coef: inverse gamma over hosts
        resid = theta - design @ coef
        tau2 = _inv_gamma_one(
            TAU2_PRIOR[0] + n_hosts / 2, TAU2_PRIOR[1] + float(resid @ resid) / 2, rng
        )
        # sigma2 | y, theta: inverse gamma with weighted counts (power likelihood)
        within = y - theta[host_of]
        sigma2 = _inv_gamma_one(
            SIGMA2_PRIOR[0] + float(w.sum()) / 2,
            SIGMA2_PRIOR[1] + float((w * within**2).sum()) / 2,
            rng,
        )
        if it >= burn_in and (it - burn_in) % keep_every == 0 and len(kept["alpha"]) < n_draws:
            kept["alpha"].append(coef[0])
            kept["beta"].append(coef[1])
            kept["tau2"].append(tau2)
            kept["sigma2"].append(sigma2)
            kept["theta"].append(theta.copy())
    assert len(kept["alpha"]) == n_draws
    theta_draws = np.array(kept["theta"])  # (K, H)
    return (
        np.array(kept["alpha"]),
        np.array(kept["beta"]),
        np.array(kept["tau2"]),
        np.array(kept["sigma2"]),
        {h: theta_draws[:, i] for h, i in index.items()},
    )


def _fit_overhead(
    obs: list[OverheadObs],
    half_life_days: float,
    n_draws: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Normal-inverse-gamma posterior of log overhead minutes, with weighted sufficient stats."""
    mu0, k0, a0, b0 = OVERHEAD_PRIOR
    w = np.array([discount(o.age_days, half_life_days) for o in obs])
    y = np.array([o.log_minutes for o in obs])
    n = float(w.sum())
    if n > 0:
        ybar = float((w * y).sum() / n)
        spread = float((w * (y - ybar) ** 2).sum())
    else:
        ybar, spread = mu0, 0.0
    kn = k0 + n
    mun = (k0 * mu0 + n * ybar) / kn
    an = a0 + n / 2
    bn = b0 + spread / 2 + k0 * n * (ybar - mu0) ** 2 / (2 * kn)
    sigma2 = _inv_gamma(an, bn, n_draws, rng)
    mu = mun + np.sqrt(sigma2 / kn) * rng.standard_normal(n_draws)
    return mu, sigma2


def _inv_gamma(shape: float, scale: float, size: int, rng: np.random.Generator) -> np.ndarray:
    """Inverse gamma draws with this scale: scale / Gamma(shape, 1)."""
    return scale / rng.gamma(shape, 1.0, size)


def _inv_gamma_one(shape: float, scale: float, rng: np.random.Generator) -> float:
    return scale / float(rng.gamma(shape, 1.0))
