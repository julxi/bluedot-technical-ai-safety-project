"""Score offers with the host model's posterior, choose one by mode, and derive the abort rule.

Cost of renting offer i, in dollars (design: convos/julian/26-11-18_vast_host_selection_LOG.md):
    success: price_i * (hours + S/60) + lambda * max(0, S - S_ref - band)
    failure: price_i * T_fail/60 + lambda * aversion * T_fail + C_ref
where S is the setup time in minutes, S_ref the best expected setup time among the offers,
band = max(band_minutes, band_fraction * S_ref) (setup differences inside it cost nothing, Julian
26-11-18), T_fail the minutes a failed rental wastes, and C_ref the expected success cost of the
best offer (what the re-rent then costs). Given a posterior draw of the host's parameters, the
expected cost averages over the day-to-day speed noise and the failure chance; across draws it
is a distribution, which the modes use differently:

    exploit  lowest posterior-mean cost (the old "greedy")
    balance  Thompson sampling with the spread shrunk to `balance_tempering`: mostly exploits,
             now and then tries a host it knows little about (the default)
    explore  Thompson sampling, full spread: deliberate exploration when nothing is urgent
    hedge    lowest `hedge_quantile` of the cost, with failure aversion, longer memory and the
             "watching" value of time: for when a failure or a long wait must be avoided.
             It never explores (unknown hosts look risky to a pessimist; from an empty history
             it sticks to its first choice), so it relies on a history built by the other modes.

The selection probability of every offer under the mode is recorded with each rental, so other
policies can later be evaluated on the logged data (off-policy evaluation).
"""

import math
from typing import Any, Literal, NamedTuple

import numpy as np

from ic_eval.vast.config import PolicyConfig
from ic_eval.vast.model import HostDraws, Posterior, host_draws
from ic_eval.vast.records import CandidateScore

Mode = Literal["exploit", "balance", "explore", "hedge"]
MODES: tuple[Mode, ...] = ("exploit", "balance", "explore", "hedge")
# Noise samples per draw for the day-to-day speed and overhead variation (common random numbers,
# shared by all offers, so comparisons between offers are not blurred by sampling noise).
N_NOISE = 32
# Variance of the log speed measured live from a pull that is complete, in log MB/s squared. The
# live estimate's variance grows as 1/fraction-done; at 10% done its sd is ~0.45 (a factor 1.6).
# "Pull complete" counts only unpacked layers while later layers already download, so early live
# speeds are underestimates; the warm-up (policy.yaml) and this wide variance absorb that.
LIVE_LOG_SPEED_VAR_AT_FULL = 0.02


class Evaluation(NamedTuple):
    offers: list[dict[str, Any]]
    hosts: list[HostDraws]
    setup_min: np.ndarray  # (N, K, M) setup minutes, cache mixed in
    cost: np.ndarray  # (N, K) expected cost given each posterior draw
    lambda_per_min: float
    band_min: float
    reference_setup_min: float
    hours: float
    failure_aversion: float


class AbortRule(NamedTuple):
    """What boot.py needs to decide, during a pull, whether to give up on the host."""

    log_speed_mean: float  # predictive log MB/s of this host for this rental
    log_speed_var: float
    overhead_min: float  # expected minutes from pull end to ready
    threshold_min: float | None  # abort if the predicted remaining time exceeds this


def mode_settings(mode: Mode, policy: PolicyConfig) -> tuple[float, float]:
    """(lambda $/min, failure aversion) of a mode.

    `hedge` is the mode for watching the boot, so it values time at the watching rate. `explore`
    does too, although it is not for watching: setup speed matters mostly when watching, so that
    is what exploration must learn about. Scoring exploration at the "away" rate, which barely
    values time, almost never tried the fast-but-pricier hosts, and `hedge` afterwards chose as
    badly as at random in one of three simulated markets; at the watching rate it found the best
    host in all three (simulation, 26-11-18; tests/vast/test_simulation.py).
    """
    match mode:
        case "hedge":
            return policy.lambda_watching_per_hour / 60, policy.hedge_failure_aversion
        case "explore":
            return policy.lambda_watching_per_hour / 60, 1.0
        case "exploit" | "balance":
            return policy.lambda_away_per_hour / 60, 1.0


def evaluate(
    offers: list[dict[str, Any]],
    posterior: Posterior,
    image_bytes: int,
    cache_eligible_hosts: set[int],
    hours: float,
    lambda_per_min: float,
    failure_aversion: float,
    policy: PolicyConfig,
    rng: np.random.Generator,
) -> Evaluation:
    assert offers, "nothing to evaluate"
    k = len(posterior.alpha)
    image_mb = image_bytes / 1e6
    z_speed = rng.standard_normal(N_NOISE)
    z_overhead = rng.standard_normal(N_NOISE)
    u_cache = rng.random((k, N_NOISE))
    overhead = np.exp(
        posterior.overhead_mu[:, None]
        + np.sqrt(posterior.overhead_sigma2)[:, None] * z_overhead[None, :]
    )  # (K, M) minutes
    hosts: list[HostDraws] = []
    setups = []
    for offer in offers:
        draws = host_draws(posterior, int(offer["host_id"]), float(offer["inet_down"]), rng)
        hosts.append(draws)
        speed = np.exp(
            draws.log_speed[:, None] + np.sqrt(posterior.sigma2)[:, None] * z_speed[None, :]
        )  # (K, M) MB/s
        pull = image_mb / speed / 60
        if int(offer["host_id"]) in cache_eligible_hosts:
            cached = u_cache < posterior.cache_pi[:, None]
            pull = np.where(cached, 0.0, pull)
        setups.append(overhead + pull)
    setup = np.array(setups)  # (N, K, M)
    reference = float(setup.mean(axis=(1, 2)).min())
    band = max(policy.band_minutes, policy.band_fraction * reference)
    price = np.array([float(o["dph_total"]) for o in offers])[:, None, None]
    success = price * (hours + setup / 60) + lambda_per_min * np.maximum(
        0.0, setup - reference - band
    )
    success_k = success.mean(axis=2)  # (N, K)
    reference_cost = float(success_k.mean(axis=1).min())
    t_fail = policy.failure_lost_minutes
    failure = (
        price[:, 0, 0] * t_fail / 60 + lambda_per_min * failure_aversion * t_fail + reference_cost
    )  # (N,)
    p = np.array([h.failure_prob for h in hosts])  # (N, K)
    cost = (1 - p) * success_k + p * failure[:, None]
    return Evaluation(
        offers=offers,
        hosts=hosts,
        setup_min=setup,
        cost=cost,
        lambda_per_min=lambda_per_min,
        band_min=band,
        reference_setup_min=reference,
        hours=hours,
        failure_aversion=failure_aversion,
    )


def selection_scores(evaluation: Evaluation, mode: Mode, policy: PolicyConfig) -> np.ndarray:
    """(N, K) scores whose per-column argmin is the offer chosen with posterior draw k.

    Deterministic modes have identical columns, so every draw picks the same offer.
    """
    cost = evaluation.cost
    mean = cost.mean(axis=1, keepdims=True)
    match mode:
        case "exploit":
            return np.repeat(mean, cost.shape[1], axis=1)
        case "hedge":
            q = np.quantile(cost, policy.hedge_quantile, axis=1, keepdims=True)
            return np.repeat(q, cost.shape[1], axis=1)
        case "balance":
            return mean + policy.balance_tempering * (cost - mean)
        case "explore":
            return cost


def propensities(scores: np.ndarray) -> np.ndarray:
    """Probability of each offer being chosen: the share of posterior draws that pick it."""
    picks = scores.argmin(axis=0)
    return np.bincount(picks, minlength=scores.shape[0]) / scores.shape[1]


def select(
    evaluation: Evaluation, mode: Mode, policy: PolicyConfig, rng: np.random.Generator
) -> tuple[int, np.ndarray]:
    """Index of the chosen offer (one random posterior draw decides) and all propensities."""
    scores = selection_scores(evaluation, mode, policy)
    draw = int(rng.integers(scores.shape[1]))
    return int(scores[:, draw].argmin()), propensities(scores)


def candidate_scores(
    evaluation: Evaluation, probs: np.ndarray, policy: PolicyConfig
) -> list[CandidateScore]:
    out = []
    for i, offer in enumerate(evaluation.offers):
        setup = evaluation.setup_min[i].ravel()
        out.append(
            CandidateScore(
                offer_id=int(offer["id"]),
                host_id=int(offer["host_id"]),
                price=float(offer["dph_total"]),
                setup_mean_min=float(setup.mean()),
                setup_p10_min=float(np.quantile(setup, 0.1)),
                setup_p90_min=float(np.quantile(setup, 0.9)),
                failure_prob=float(evaluation.hosts[i].failure_prob.mean()),
                cost_mean=float(evaluation.cost[i].mean()),
                cost_quantile=float(np.quantile(evaluation.cost[i], policy.hedge_quantile)),
                effective_observations=evaluation.hosts[i].effective_observations,
                propensity=float(probs[i]),
            )
        )
    return out


def next_best_setup(
    evaluation: Evaluation, chosen: int, mode: Mode, policy: PolicyConfig
) -> float | None:
    """Expected setup minutes of the offer the mode would rank first if the chosen host failed:
    the yardstick of the abort rule. None if every offer is on the chosen host."""
    chosen_host = int(evaluation.offers[chosen]["host_id"])
    scores = selection_scores(evaluation, mode, policy).mean(axis=1)
    others = [i for i, o in enumerate(evaluation.offers) if int(o["host_id"]) != chosen_host]
    if not others:
        return None
    best = min(others, key=lambda i: scores[i])
    return float(evaluation.setup_min[best].mean())


def abort_rule(
    evaluation: Evaluation,
    posterior: Posterior,
    chosen: int,
    next_best_min: float | None,
    policy: PolicyConfig,
) -> AbortRule:
    """Continue a pull only while its predicted remaining time beats switching to the next-best
    offer by more than the tolerance band (an optimal-stopping comparison)."""
    log_speed = evaluation.hosts[chosen].log_speed
    threshold = None
    if next_best_min is not None:
        band = max(policy.band_minutes, policy.band_fraction * next_best_min)
        threshold = next_best_min + policy.switch_overhead_minutes + band
    overhead = np.exp(posterior.overhead_mu + posterior.overhead_sigma2 / 2)
    return AbortRule(
        log_speed_mean=float(log_speed.mean()),
        log_speed_var=float(log_speed.var() + posterior.sigma2.mean()),
        overhead_min=float(overhead.mean()),
        threshold_min=threshold,
    )


def predict_remaining(
    rule: AbortRule, bytes_done: int, bytes_total: int, pull_elapsed_s: float
) -> float | None:
    """Predicted minutes until ready, combining the host's prior speed with the live pull speed
    (a normal update in log space). None while nothing has been unpacked yet."""
    assert 0 <= bytes_done <= bytes_total and pull_elapsed_s > 0
    if bytes_done == 0:
        return None
    fraction = bytes_done / bytes_total
    live = math.log(bytes_done / 1e6 / pull_elapsed_s)
    live_var = LIVE_LOG_SPEED_VAR_AT_FULL / fraction
    precision = 1 / rule.log_speed_var + 1 / live_var
    mean = (rule.log_speed_mean / rule.log_speed_var + live / live_var) / precision
    inverse_speed = math.exp(-mean + 0.5 / precision)  # E[1/v] for log-normal v, s/MB
    return (bytes_total - bytes_done) / 1e6 * inverse_speed / 60 + rule.overhead_min
