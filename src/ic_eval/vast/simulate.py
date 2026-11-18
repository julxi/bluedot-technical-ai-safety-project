"""A fake vast.ai market whose hosts' true speeds and failure rates are known.

For testing and tuning the model and the policy without renting anything: run the policy on the
fake market for many rentals, feed each simulated outcome back as an observation, and compare
what it learns and chooses with the truth (tests/vast/test_simulation.py). The rental mechanics
(boot, abort, re-rent) are not simulated; one rental yields a failure or a pull speed.
"""

import math
from collections.abc import Sequence
from typing import Any, NamedTuple

import numpy as np

from ic_eval.vast.config import PolicyConfig
from ic_eval.vast.model import (
    ADVERTISED_REFERENCE_MBPS,
    FlagObs,
    Observations,
    OverheadObs,
    SpeedObs,
    fit,
)
from ic_eval.vast.policy import Mode, evaluate, mode_settings, select

DAYS_PER_RENTAL = 0.5


class TrueHost(NamedTuple):
    host_id: int
    advertised_mbps: float
    log_speed: float  # log MB/s
    failure_prob: float
    price: float  # $/h


class SimulatedRental(NamedTuple):
    host_id: int
    failed: bool
    speed_mb_s: float | None
    setup_min: float | None
    expected_cost: float  # the true expected cost of the chosen host (no sampling noise)


def make_market(
    n_hosts: int,
    rng: np.random.Generator,
    alpha: float = math.log(30.0),
    beta: float = 0.3,
    tau: float = 0.7,
    failure_rate: float = 0.1,
) -> list[TrueHost]:
    hosts = []
    for i in range(n_hosts):
        advertised = float(np.exp(rng.uniform(math.log(100), math.log(10000))))
        x = math.log(advertised / ADVERTISED_REFERENCE_MBPS)
        hosts.append(
            TrueHost(
                host_id=1000 + i,
                advertised_mbps=advertised,
                log_speed=alpha + beta * x + tau * float(rng.standard_normal()),
                failure_prob=float(rng.beta(failure_rate * 10, (1 - failure_rate) * 10)),
                price=float(rng.uniform(0.45, 1.1)),
            )
        )
    return hosts


def offers_of(market: list[TrueHost]) -> list[dict[str, Any]]:
    """Offer dicts with the fields the policy reads, shaped like vast.ai's."""
    return [
        {
            "id": h.host_id * 10,
            "host_id": h.host_id,
            "machine_id": h.host_id * 10 + 1,
            "gpu_name": "A40",
            "dph_total": h.price,
            "inet_down": h.advertised_mbps,
            "geolocation": "Simulated, XX",
        }
        for h in market
    ]


def true_expected_cost(
    host: TrueHost,
    image_bytes: int,
    hours: float,
    lambda_per_min: float,
    overhead_min: float,
    sigma: float,
    policy: PolicyConfig,
    reference_setup_min: float,
) -> float:
    """The policy's cost formula evaluated with the true parameters (expectation by sampling the
    day-to-day noise on a fixed grid)."""
    z = np.linspace(-2.5, 2.5, 51)
    weights = np.exp(-(z**2) / 2)
    weights /= weights.sum()
    setup = overhead_min + image_bytes / 1e6 / np.exp(host.log_speed + sigma * z) / 60
    band = max(policy.band_minutes, policy.band_fraction * reference_setup_min)
    success = host.price * (hours + setup / 60) + lambda_per_min * np.maximum(
        0.0, setup - reference_setup_min - band
    )
    failure = host.price * policy.failure_lost_minutes / 60 + lambda_per_min * (
        policy.failure_lost_minutes
    )
    return float((1 - host.failure_prob) * (weights @ success) + host.failure_prob * failure)


def run(
    market: list[TrueHost],
    modes: Sequence[Mode],
    policy: PolicyConfig,
    rng: np.random.Generator,
    image_bytes: int = 10_860_000_000,
    hours: float = 2.0,
    sigma: float = 0.3,
    overhead_min: float = 1.0,
) -> list[SimulatedRental]:
    """Rent once per entry of `modes`, in sequence, learning from each simulated outcome."""
    by_id = {h.host_id: h for h in market}
    offers = offers_of(market)
    history: list[tuple[float, SimulatedRental]] = []  # (day, rental)
    rentals = []
    for i, mode in enumerate(modes):
        today = i * DAYS_PER_RENTAL
        obs = _observations(history, by_id, today, overhead_min)
        factor = policy.hedge_half_life_factor if mode == "hedge" else 1.0
        posterior = fit(
            obs,
            policy.speed_half_life_days * factor,
            policy.failure_half_life_days * factor,
            policy.n_posterior_draws,
            policy.gibbs_iterations,
            policy.gibbs_burn_in,
            rng,
        )
        lam, aversion = mode_settings(mode, policy)
        evaluation = evaluate(
            offers, posterior, image_bytes, set(), hours, lam, aversion, policy, rng
        )
        chosen, _ = select(evaluation, mode, policy, rng)
        host = by_id[int(offers[chosen]["host_id"])]
        reference = min(
            overhead_min + image_bytes / 1e6 / math.exp(h.log_speed) / 60 for h in market
        )
        expected = true_expected_cost(
            host, image_bytes, hours, lam, overhead_min, sigma, policy, reference
        )
        failed = bool(rng.random() < host.failure_prob)
        if failed:
            rental = SimulatedRental(host.host_id, True, None, None, expected)
        else:
            speed = math.exp(host.log_speed + sigma * float(rng.standard_normal()))
            setup = overhead_min + image_bytes / 1e6 / speed / 60
            rental = SimulatedRental(host.host_id, False, speed, setup, expected)
        history.append((today, rental))
        rentals.append(rental)
    return rentals


def _observations(
    history: list[tuple[float, SimulatedRental]],
    by_id: dict[int, TrueHost],
    today: float,
    overhead_min: float,
) -> Observations:
    speed, failure, overhead = [], [], []
    for day, r in history:
        age = today - day
        failure.append(FlagObs(r.host_id, r.failed, age))
        if r.speed_mb_s is not None:
            speed.append(SpeedObs(r.host_id, math.log(r.speed_mb_s), age))
            overhead.append(OverheadObs(math.log(overhead_min), age))
    advertised = {h: by_id[h].advertised_mbps for h in by_id}
    return Observations(speed, failure, overhead, [], advertised)
