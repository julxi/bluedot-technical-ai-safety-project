"""The boot loop, end to end, on real recorded boots (tests/vast/data/boots_26-11-18.jsonl).

The six attempt records were copied verbatim from src/ic_eval/vast/data/rentals.jsonl (26-11-18):
two backfilled rentals and four from the first live tests. Each boot's polls are replayed through
wait_for_boot with a fake clock that polls every 5 s, as the launcher does. What each host turned
out to be is known from the whole recording:

- 314882, 134600, 682584 pulled fine (28, 54 and 35 MB/s). 314882 started slowly: "done" sat at
  0.37 and 1.87 GB for minutes while its big layers unpacked.
- 169171 is slow (8.8 MB/s over its backfilled pull; the live one was aborted).
- 701831 is unknown: the old rule aborted it ~100 s into its pull on no evidence.
- 626968 (boots_26-11-21.jsonl, copied verbatim from the history) is unknown too: the live test
  of 26-11-21 aborted it at 4.1 min because small layers finished unseen between polls and the
  upper bound stopped at an 804-byte layer while a 4.15 GB one was unpacking
  (pull.VISIBLE_LAYER_BYTES).

Written after the 26-11-18 live tests found the boot loop crashing on the first real sequence and
the old abort rule giving up on hosts while "done" stood still between big layers.
"""

import json
from pathlib import Path

import pytest

from ic_eval.vast import boot
from ic_eval.vast.config import PolicyConfig
from ic_eval.vast.policy import AbortRule, abort_threshold
from ic_eval.vast.records import Attempt

RECORDS = [
    Path(__file__).parent / "data" / "boots_26-11-18.jsonl",
    Path(__file__).parent / "data" / "boots_26-11-21.jsonl",
]
# Pooled overhead (pull end -> ready) from `ic-vast stats` after the live tests, 26-11-18.
OVERHEAD_MIN = 0.9
GOOD_HOSTS = {314882, 134600, 682584}
# Not known to be slow: aborted by mistake (see the module docstring); kept like the good hosts.
NOT_SLOW_HOSTS = {701831, 626968}
SLOW_HOST = 169171


class _RecordingEnded(Exception):
    pass


def _boots() -> list[Attempt]:
    lines = [line for path in RECORDS for line in path.read_text().splitlines()]
    return [Attempt.model_validate(json.loads(line)) for line in lines]


def _replay_boot(attempt: Attempt, policy: PolicyConfig, monkeypatch) -> boot.BootResult | None:
    """Run wait_for_boot over the recorded polls. None if the recording ends first (no verdict:
    the boot loop neither aborted nor saw "running" while there was data)."""
    polls = attempt.polls
    clock = {"now": attempt.created_at}

    class FakeTime:
        @staticmethod
        def time() -> float:
            return clock["now"]

        @staticmethod
        def sleep(seconds: float) -> None:
            clock["now"] += seconds

    def fake_show(instance_id: int) -> dict[str, str | None]:
        if clock["now"] > polls[-1].t + boot.POLL_INTERVAL_S:
            raise _RecordingEnded
        latest = [p for p in polls if p.t <= clock["now"]] or [polls[0]]
        return {"actual_status": latest[-1].status, "status_msg": latest[-1].message}

    monkeypatch.setattr(boot, "show_instance", fake_show)
    monkeypatch.setattr(boot, "time", FakeTime)
    rule = AbortRule(
        overhead_min=OVERHEAD_MIN,
        threshold_min=abort_threshold(attempt.selection.next_best_setup_min, policy),
        budget_margin=policy.abort_budget_margin,
    )
    try:
        return boot.wait_for_boot(
            attempt.instance_id, attempt.image_layers, rule, policy, total_left_s=1800
        )
    except _RecordingEnded:
        return None


@pytest.fixture
def replay_policy(policy: PolicyConfig) -> PolicyConfig:
    # The backfilled boots were reconstructed from logged status changes only, so they have
    # gaps of up to 244 s without a poll; the 4-min stall cap would fire on that artefact.
    return PolicyConfig(**{**policy.model_dump(), "stall_minutes": 10.0})


def test_recorded_boots_cover_the_cases():
    hosts = sorted(int(a.offer["host_id"]) for a in _boots())
    assert hosts == [134600, 169171, 169171, 314882, 626968, 682584, 701831]


@pytest.mark.parametrize(
    "instance_id",
    [a.instance_id for a in _boots() if int(a.offer["host_id"]) in GOOD_HOSTS | NOT_SLOW_HOSTS],
)
def test_good_hosts_are_never_aborted(instance_id, replay_policy, monkeypatch):
    """Catches an abort rule that reads a slow start (or "done" standing still between big
    layers) as a slow host. 701831 is included because nothing in its 2.2 recorded minutes shows
    it was slow (the old rule aborted it there)."""
    attempt = next(a for a in _boots() if a.instance_id == instance_id)
    result = _replay_boot(attempt, replay_policy, monkeypatch)
    assert result is None or result.outcome == "running", (result.outcome, result.detail)


@pytest.mark.parametrize(
    "instance_id", [a.instance_id for a in _boots() if int(a.offer["host_id"]) == SLOW_HOST]
)
def test_slow_host_is_aborted_early(instance_id, replay_policy, monkeypatch):
    """Catches an abort rule so cautious that only the pull cap ends a slow host's boot."""
    attempt = next(a for a in _boots() if a.instance_id == instance_id)
    result = _replay_boot(attempt, replay_policy, monkeypatch)
    assert result is not None and result.outcome == "aborted_slow"
    aborted_after_min = (result.polls[-1].t - attempt.created_at) / 60
    assert aborted_after_min < 6.0, aborted_after_min
