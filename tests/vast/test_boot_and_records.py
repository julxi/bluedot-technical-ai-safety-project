"""Pull progress parsing on real status messages, and the record file round trip."""

import pytest

from ic_eval.vast import records
from ic_eval.vast.boot import PullTracker
from ic_eval.vast.image import Layer
from ic_eval.vast.model import observations_from_records
from ic_eval.vast.records import Attempt, End, Poll, PullStats, Selection

# Real layer ids and positions of vastai/vllm:v0.34.0-cuda-13.0 (Docker Hub, 26-11-18); the
# other positions get placeholder ids. Sizes of the real ones are the real sizes.
REAL = {
    7: ("b1dceeafcd5e", 234_000_000),
    15: ("41eaa41e205a", 400),
    19: ("648f7856342e", 4_153_000_000),
    20: ("754032b1d08d", 3_334_000_000),
    22: ("2b27998691cb", 1_000_000),
    23: ("0215040ad1a4", 67_000_000),
}


def _layers() -> list[Layer]:
    return [
        Layer(short_id=REAL[i][0], size=REAL[i][1])
        if i in REAL
        else Layer(short_id=f"{i:012x}", size=10_000_000)
        for i in range(25)
    ]


def test_pull_tracker_on_real_messages():
    """Messages as vast.ai showed them during the 26-11-18 test rental on host 682584."""
    tracker = PullTracker(_layers())
    tracker.update(0, "loading", None)
    assert tracker.started_at is None
    tracker.update(5, "loading", "v0.34.0-cuda-13.0: Pulling from vastai/vllm\n")
    assert tracker.started_at == 5 and tracker.bytes_done == 0
    tracker.update(10, "loading", "41eaa41e205a: Verifying Checksum\n")
    assert tracker.downloaded and tracker.bytes_done == 0
    tracker.update(15, "loading", "b1dceeafcd5e: Pull complete\n")
    assert tracker.bytes_done == sum(layer.size for layer in _layers()[:8])
    tracker.update(20, "loading", "648f7856342e: Pull complete\n")
    after_19 = tracker.bytes_done
    tracker.update(25, "loading", "b1dceeafcd5e: Pull complete\n")  # repeated, earlier layer
    assert tracker.bytes_done == after_19  # progress never goes backwards
    tracker.update(30, "loading", '#0 building with "default" instance using docker driver\n')
    assert tracker.ended_at == 30 and tracker.bytes_done == tracker.bytes_total
    stats = tracker.stats(31)
    assert not stats.cached and stats.unknown_layer_ids == []
    assert stats.speed_mb_s == pytest.approx(tracker.bytes_total / 1e6 / 25)


def test_pull_tracker_unknown_layer_and_cached():
    tracker = PullTracker(_layers())
    tracker.update(1, "loading", "deadbeef0000: Pull complete\n")
    assert tracker.unknown_ids == ["deadbeef0000"]
    cached = PullTracker(_layers())
    cached.update(1, "running", "success, running vastai/vllm_v0.34.0-cuda-13.0/ssh")
    assert cached.stats(2).cached and cached.stats(2).speed_mb_s is None


def _attempt(outcome, failure_type, host=7, created_at=1000.0, ready_at=None, speed=50.0):
    layers = _layers()
    return Attempt(
        kind="attempt",
        schema_version=records.SCHEMA_VERSION,
        session_id="s",
        attempt_index=0,
        created_at=created_at,
        config="48gb",
        image="vastai/vllm:test",
        image_layers=layers,
        offer={"id": 1, "host_id": host, "inet_down": 900.0, "dph_total": 0.5},
        instance_id=int(created_at),
        selection=Selection(
            mode="balance",
            hours=2,
            lambda_per_min=0.01,
            band_min=3,
            reference_setup_min=5,
            next_best_setup_min=6,
            candidates=[],
            propensity=0.5,
        ),
        polls=[Poll(t=created_at, status="loading", message="x")],
        pull=PullStats(
            started_at=created_at + 10,
            ended_at=created_at + 200,
            bytes_total=100,
            bytes_done=100,
            cached=False,
            speed_mb_s=speed,
            unknown_layer_ids=[],
        ),
        abort_prediction_min=None,
        outcome=outcome,
        failure_type=failure_type,
        failure_detail=None,
        ssh_ready_at=None,
        ready_at=ready_at,
        probes=None,
    )


def test_records_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "RENTALS_PATH", tmp_path / "rentals.jsonl")
    attempt = _attempt("ready", None, ready_at=1300.0)
    end = End(
        kind="end",
        schema_version=1,
        instance_id=1000,
        ended_at=2000.0,
        reason="destroyed",
        watchdog_starts=1,
        detail=None,
    )
    records.append_record(attempt)
    records.append_record(end)
    assert records.load_records() == [attempt, end]


def test_observations_from_records():
    history = [
        _attempt("ready", None, host=7, created_at=1000.0, ready_at=1300.0),
        _attempt("failed", "ssh", host=8, created_at=2000.0, speed=20.0),
        _attempt("failed", "ours", host=9, created_at=3000.0),  # not the host's fault
        _attempt("aborted_slow", None, host=10, created_at=4000.0, speed=5.0),
    ]
    obs = observations_from_records(history, now=5000.0, cache_window_days=7)
    assert sorted(s.host_id for s in obs.speed) == [7, 8, 9, 10]
    assert sorted((f.host_id, f.flag) for f in obs.failure) == [(7, False), (8, True)]
    assert len(obs.overhead) == 1 and obs.overhead[0].log_minutes == pytest.approx(
        __import__("math").log((1300.0 - 1200.0) / 60)
    )
