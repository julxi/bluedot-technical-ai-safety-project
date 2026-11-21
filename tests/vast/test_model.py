"""The host model learns speeds and failure rates, pools across hosts, and forgets old data."""

import math

import numpy as np

from ic_eval.vast.config import PolicyConfig
from ic_eval.vast.model import (
    ALPHA_PRIOR,
    FlagObs,
    Observations,
    SpeedObs,
    discount,
    fit,
    host_draws,
)


def _fit(obs: Observations, policy: PolicyConfig, rng: np.random.Generator):
    return fit(
        obs,
        policy.speed_half_life_days,
        policy.failure_half_life_days,
        policy.n_posterior_draws,
        policy.gibbs_iterations,
        policy.gibbs_burn_in,
        rng,
    )


def test_discount_halves_at_half_life():
    assert discount(0, 14) == 1.0
    assert math.isclose(discount(14, 14), 0.5)
    assert math.isclose(discount(28, 14), 0.25)


def test_no_data_gives_prior(policy, rng):
    posterior = _fit(Observations([], [], [], [], {}), policy, rng)
    assert abs(posterior.alpha.mean() - ALPHA_PRIOR[0]) < 0.2
    assert posterior.theta == {}


def test_recovers_host_speeds(policy, rng):
    """Hosts with several fresh observations end up near their true speed."""
    truth = {1: math.log(15.0), 2: math.log(40.0), 3: math.log(90.0)}
    speed = [
        SpeedObs(h, t + 0.2 * float(rng.standard_normal()), age_days=1.0)
        for h, t in truth.items()
        for _ in range(6)
    ]
    obs = Observations(speed, [], [], [], {1: 500.0, 2: 1000.0, 3: 2000.0})
    posterior = _fit(obs, policy, rng)
    for h, t in truth.items():
        assert abs(posterior.theta[h].mean() - t) < 0.3, (
            h,
            posterior.theta[h].mean(),
            t,
        )


def test_advertised_speed_effect_is_learned(policy, rng):
    """With many hosts whose speed rises with the advertised speed, beta comes out positive."""
    advertised = {h: float(a) for h, a in enumerate(np.geomspace(100, 10000, 20))}
    speed = []
    for h, adv in advertised.items():
        true_log = math.log(30) + 0.6 * math.log(adv / 1000) + 0.2 * float(rng.standard_normal())
        speed += [SpeedObs(h, true_log + 0.1 * float(rng.standard_normal()), 0.5) for _ in range(2)]
    posterior = _fit(Observations(speed, [], [], [], advertised), policy, rng)
    assert posterior.beta.mean() > 0.4


def test_old_observations_are_forgiven(policy, rng):
    """One very slow pull: fresh, it drags the host down; a year old, the host is back near the
    population (the "no hard cuts, forgetful" requirement)."""
    others = [SpeedObs(h, math.log(40.0), 1.0) for h in range(10, 16) for _ in range(3)]
    advertised = {h: 1000.0 for h in range(10, 16)} | {99: 1000.0}
    slow = math.log(3.0)
    fresh = _fit(
        Observations([*others, SpeedObs(99, slow, 0.0)], [], [], [], advertised),
        policy,
        rng,
    )
    old = _fit(
        Observations([*others, SpeedObs(99, slow, 365.0)], [], [], [], advertised),
        policy,
        rng,
    )
    assert fresh.theta[99].mean() < old.theta[99].mean() - 0.5
    assert abs(old.theta[99].mean() - math.log(40.0)) < 0.5


def test_failures_raise_failure_probability_and_fade(policy, rng):
    advertised = {1: 1000.0, 2: 1000.0}
    recent = Observations([], [FlagObs(1, True, 0.5) for _ in range(3)], [], [], advertised)
    old = Observations([], [FlagObs(1, True, 400.0) for _ in range(3)], [], [], advertised)
    post_recent = _fit(recent, policy, rng)
    post_old = _fit(old, policy, rng)
    failing = host_draws(post_recent, 1, 1000.0, rng).failure_prob.mean()
    unknown = host_draws(post_recent, 2, 1000.0, rng).failure_prob.mean()
    forgiven = host_draws(post_old, 1, 1000.0, rng).failure_prob.mean()
    assert failing > 0.35
    assert failing > unknown + 0.2
    assert forgiven < failing - 0.2


def test_censored_speed_is_an_interval_not_a_value(policy, rng):
    """An unfinished pull says only "between low and high". A wide interval around the population
    leaves the host near it; an interval far below it pulls the host down. Separate fits, so one
    unusual host cannot shift the population for the other. Catches the 26-11-18 bug class: an
    unfinished pull's lower bound used as its speed (that made host 701831 look like 3.9 MB/s),
    or the interval ignored altogether."""
    others = [SpeedObs(h, math.log(40.0), 1.0) for h in range(10, 16) for _ in range(3)]
    advertised = {h: 1000.0 for h in range(10, 16)} | {99: 1000.0}

    def host_99_mean(observation: SpeedObs) -> float:
        posterior = _fit(Observations([*others, observation], [], [], [], advertised), policy, rng)
        return float(posterior.theta[99].mean())

    vague = host_99_mean(SpeedObs(99, math.log(1.0), 0.0, log_speed_max=math.log(400.0)))
    assert abs(vague - math.log(40.0)) < 0.5
    slow = host_99_mean(SpeedObs(99, -math.inf, 0.0, log_speed_max=math.log(4.0)))
    assert slow < math.log(8.0)
    low_end_as_value = host_99_mean(SpeedObs(99, math.log(1.0), 0.0))  # the old reading
    assert low_end_as_value < vague - 1.0
