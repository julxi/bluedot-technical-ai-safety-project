"""Costs, modes and the abort rule behave as their names promise."""

import math

import numpy as np

from ic_eval.vast.model import FlagObs, Observations, SpeedObs, fit
from ic_eval.vast.policy import (
    AbortRule,
    abort_rule,
    evaluate,
    mode_settings,
    next_best_setup,
    predict_remaining,
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


def test_abort_rule_threshold_and_prediction(policy, rng):
    offers, posterior = _market(policy, rng)
    lam, aversion = mode_settings("exploit", policy)
    ev = evaluate(offers, posterior, IMAGE_BYTES, set(), 2.0, lam, aversion, policy, rng)
    chosen = 2  # the unknown host
    nxt = next_best_setup(ev, chosen, "exploit", policy)
    assert nxt is not None
    rule = abort_rule(ev, posterior, chosen, nxt, policy)
    assert rule.threshold_min is not None and rule.threshold_min > nxt
    # 10% of the image in 120 s = ~9 MB/s: ~18 min still to go -> beyond the threshold
    slow = predict_remaining(rule, IMAGE_BYTES // 10, IMAGE_BYTES, 120.0)
    # 40% in 120 s = ~36 MB/s: ~3 min to go -> fine
    fast = predict_remaining(rule, IMAGE_BYTES * 4 // 10, IMAGE_BYTES, 120.0)
    assert slow is not None and fast is not None
    assert slow > rule.threshold_min > fast


def test_prediction_needs_progress():
    rule = AbortRule(math.log(30), 0.5, 1.0, 10.0)
    assert predict_remaining(rule, 0, IMAGE_BYTES, 100.0) is None
    done = predict_remaining(rule, IMAGE_BYTES, IMAGE_BYTES, 100.0)
    assert done is not None and math.isclose(done, 1.0)
