"""End to end on a simulated market: the policy learns which hosts are good and uses that."""

import math

import numpy as np

from ic_eval.vast.policy import Mode, mode_settings
from ic_eval.vast.simulate import make_market, run, true_expected_cost

IMAGE_BYTES = 10_860_000_000
OVERHEAD_MIN = 1.0
SIGMA = 0.3
HOURS = 2.0


def schedule(*parts: tuple[Mode, int]) -> list[Mode]:
    """("explore", 20), ("hedge", 10) -> 20 explore rentals, then 10 hedge rentals."""
    return [mode for mode, count in parts for _ in range(count)]


def _true_costs(market, mode, policy) -> dict[int, float]:
    """Every host's true expected cost, computed exactly as simulate.run scores its choices."""
    lam, _ = mode_settings(mode, policy)
    reference = min(OVERHEAD_MIN + IMAGE_BYTES / 1e6 / math.exp(h.log_speed) / 60 for h in market)
    return {
        h.host_id: true_expected_cost(
            h, IMAGE_BYTES, HOURS, lam, OVERHEAD_MIN, SIGMA, policy, reference
        )
        for h in market
    }


def test_balance_learns_to_beat_random_choice(policy):
    """Late rentals cost less than picking a host at random, and close in on the best host.

    Truth and randomness are seeded, so this is deterministic. The threshold leaves a wide margin
    for a correct model; a broken one (e.g. a sign error in the cost) ends near random.
    """
    rng = np.random.default_rng(7)
    market = make_market(12, rng)
    costs = _true_costs(market, "balance", policy)
    rentals = run(
        market, schedule(("balance", 40)), policy, rng, IMAGE_BYTES, HOURS, SIGMA, OVERHEAD_MIN
    )
    late = float(np.mean([r.expected_cost for r in rentals[20:]]))
    random_choice = float(np.mean(list(costs.values())))
    best = min(costs.values())
    # at least two thirds of the way from random choice to the best host
    assert late < best + (random_choice - best) / 3, (late, random_choice, best)


def test_hedge_uses_what_explore_learned(policy):
    """`hedge` after a history gathered by `explore` picks the best host by its own (watching)
    cost, in several seeded markets. With exploration scored at the away rate this failed in one
    of three markets (see policy.mode_settings)."""
    for seed in (7, 11, 23):
        rng = np.random.default_rng(seed)
        market = make_market(12, rng)
        costs = _true_costs(market, "hedge", policy)
        rentals = run(
            market,
            schedule(("explore", 20), ("hedge", 10)),
            policy,
            rng,
            IMAGE_BYTES,
            HOURS,
            SIGMA,
            OVERHEAD_MIN,
        )
        hedged = float(np.mean([r.expected_cost for r in rentals[20:]]))
        random_choice = float(np.mean(list(costs.values())))
        best = min(costs.values())
        assert hedged < best + (random_choice - best) / 3, (
            seed,
            hedged,
            random_choice,
            best,
        )


def test_hedge_alone_never_explores(policy):
    """Documented behaviour, not a goal: pessimism makes every unknown host look risky, so from
    an empty history `hedge` sticks to its first choice (seen 26-11-18: the cheapest host, 40
    times in a row). It is meant to run on a history built by the other modes."""
    rng = np.random.default_rng(7)
    market = make_market(12, rng)
    rentals = run(
        market, schedule(("hedge", 15)), policy, rng, IMAGE_BYTES, HOURS, SIGMA, OVERHEAD_MIN
    )
    assert len({r.host_id for r in rentals}) == 1


def test_balance_concentrates_on_few_hosts(policy):
    rng = np.random.default_rng(11)
    market = make_market(10, rng)
    rentals = run(
        market, schedule(("balance", 40)), policy, rng, IMAGE_BYTES, HOURS, SIGMA, OVERHEAD_MIN
    )
    late = [r.host_id for r in rentals[25:]]
    most_common = max(set(late), key=late.count)
    assert late.count(most_common) >= 6  # it settles, while still trying others now and then
