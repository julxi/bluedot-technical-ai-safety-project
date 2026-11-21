"""Costs, modes and the abort rule behave as their names promise."""

import math

import numpy as np

from ic_eval.vast.model import FlagObs, Observations, SpeedObs, fit
from ic_eval.vast.policy import (
    AbortRule,
    abort_reason,
    abort_rule,
    best_case_pull_left,
    evaluate,
    mode_settings,
    next_best_setup,
    propensities,
    select,
    selection_scores,
)

IMAGE_BYTES = 10_860_000_000


def _offer(host: int, price: float, advertised: float = 1000.0) -> dict:
    return {
        "id": host * 10,
        "host_id": host,
        "dph_total": price,
        "inet_down": advertised,
    }


def _posterior(obs, policy, rng):
    return fit(
        obs,
        policy.speed_half_life_days,
        policy.failure_half_life_days,
        policy.n_posterior_draws,
        policy.gibbs_iterations,
        policy.gibbs_burn_in,
        rng,
    )


def _market(policy, rng):
    """Host 1: known fast. Host 2: known slow (~25 min pulls). Host 3: unknown. Host 4: cheap
    but failed twice recently."""
    speed = [SpeedObs(1, math.log(80.0), 1.0) for _ in range(4)]
    speed += [SpeedObs(2, math.log(7.0), 1.0) for _ in range(4)]
    failure = [FlagObs(1, False, 1.0) for _ in range(4)] + [FlagObs(2, False, 1.0)] * 4
    failure += [FlagObs(4, True, 0.2), FlagObs(4, True, 0.5)]
    advertised = {h: 1000.0 for h in (1, 2, 3, 4)}
    posterior = _posterior(Observations(speed, failure, [], [], advertised), policy, rng)
    offers = [_offer(1, 0.70), _offer(2, 0.50), _offer(3, 0.60), _offer(4, 0.45)]
    return offers, posterior


def test_deterministic_modes_have_propensity_one(policy, rng):
    offers, posterior = _market(policy, rng)
    for mode in ("exploit", "hedge"):
        lam, aversion = mode_settings(mode, policy)
        ev = evaluate(offers, posterior, IMAGE_BYTES, set(), 2.0, lam, aversion, policy, rng)
        probs = propensities(selection_scores(ev, mode, policy))
        assert max(probs.tolist()) == 1.0


def test_explore_spreads_more_than_balance(policy, rng):
    offers, posterior = _market(policy, rng)
    lam, aversion = mode_settings("balance", policy)
    ev = evaluate(offers, posterior, IMAGE_BYTES, set(), 2.0, lam, aversion, policy, rng)

    def entropy(p):
        p = p[p > 0]
        return float(-(p * np.log(p)).sum())

    balance = propensities(selection_scores(ev, "balance", policy))
    explore = propensities(selection_scores(ev, "explore", policy))
    assert math.isclose(balance.sum(), 1.0) and math.isclose(explore.sum(), 1.0)
    assert entropy(explore) > entropy(balance)


def test_hedge_avoids_recent_failures_and_known_slow_hosts(policy, rng):
    offers, posterior = _market(policy, rng)
    lam, aversion = mode_settings("hedge", policy)
    ev = evaluate(offers, posterior, IMAGE_BYTES, set(), 2.0, lam, aversion, policy, rng)
    chosen, _ = select(ev, "hedge", policy, rng)
    assert offers[chosen]["host_id"] == 1  # the known-fast host, despite the higher price


def test_watching_values_time_more_than_away(policy):
    away, _ = mode_settings("balance", policy)
    watching, aversion = mode_settings("hedge", policy)
    exploring, explore_aversion = mode_settings("explore", policy)
    assert watching > away and aversion > 1
    assert exploring == watching and explore_aversion == 1


def test_cache_eligible_host_predicted_faster(policy, rng):
    offers, posterior = _market(policy, rng)
    lam, aversion = mode_settings("exploit", policy)
    plain = evaluate(offers, posterior, IMAGE_BYTES, set(), 2.0, lam, aversion, policy, rng)
    cached = evaluate(offers, posterior, IMAGE_BYTES, {2}, 2.0, lam, aversion, policy, rng)
    assert cached.setup_min[1].mean() < plain.setup_min[1].mean()


def test_abort_rule_threshold(policy, rng):
    offers, posterior = _market(policy, rng)
    lam, aversion = mode_settings("exploit", policy)
    ev = evaluate(offers, posterior, IMAGE_BYTES, set(), 2.0, lam, aversion, policy, rng)
    nxt = next_best_setup(ev, 2, "exploit", policy)
    assert nxt is not None
    rule = abort_rule(posterior, nxt, policy)
    assert rule.threshold_min is not None
    band = max(policy.band_minutes, policy.band_fraction * nxt)
    assert rule.threshold_min == nxt + policy.switch_overhead_minutes + band
    assert rule.budget_margin == policy.abort_budget_margin
    assert abort_rule(posterior, None, policy).threshold_min is None


def test_best_case_pull_left():
    """At most 2 of 10 GB in 100 s: at that best speed (20 MB/s) 8 GB take 400 s more."""
    assert math.isclose(best_case_pull_left(2_000_000_000, 10_000_000_000, 100.0), 400 / 60)
    assert best_case_pull_left(10**10, 10**10, 100.0) == 0.0


def test_abort_reason():
    """Threshold strictly, on the time to ready (overhead included); the budget only beyond the
    margin and on the pull alone (the build step has its own cap). Catches a margin applied the
    wrong way round, the budget compared strictly, or the overhead counted against the pull
    budget or left out of the comparison with the next-best offer."""
    rule = AbortRule(overhead_min=1.0, threshold_min=10.0, budget_margin=2.0)
    assert abort_reason(rule, pull_left_min=8.5, pull_budget_left_min=8.0) is None  # 9.5 < 10
    reason = abort_reason(rule, pull_left_min=9.5, pull_budget_left_min=12.0)  # 10.5 > 10
    assert reason is not None and "next-best" in reason
    reason = abort_reason(rule, pull_left_min=8.5, pull_budget_left_min=4.0)  # 8.5 > 2 x 4
    assert reason is not None and "budget" in reason
    # 7.5 + 1.0 overhead > 2 x 4, but the pull alone is not: the overhead isn't pull budget
    assert abort_reason(rule, pull_left_min=7.5, pull_budget_left_min=4.0) is None
    no_alternative = AbortRule(overhead_min=1.0, threshold_min=None, budget_margin=2.0)
    assert abort_reason(no_alternative, pull_left_min=30.0, pull_budget_left_min=20.0) is None
