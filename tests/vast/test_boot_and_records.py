"""Pull progress parsing on real status messages, and the record file round trip."""

import math

import pytest

from ic_eval.vast import records
from ic_eval.vast.image import Layer
from ic_eval.vast.model import observations_from_records
from ic_eval.vast.pull import PullTracker
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


@pytest.mark.parametrize(
    "build_message",
    [
        # Verbatim from host 314882, 26-11-18 (legacy builder): the first message after the pull,
        # and a later one, in case the notice falls between two polls.
        "DEPRECATED: The legacy builder is deprecated and will be removed in a future release.\n"
        "            Install the buildx component to build images with BuildKit:\n"
        "            https://docs.docker.com/go/buildx/\n\n",
        " ---> Removed intermediate container fd9de35f57a1\n ---> 2b652767bc15\n"
        "Step 3/8 : RUN mkdir -p /tmp; chmod 1777 /tmp; exit 0;\n",
    ],
)
def test_pull_tracker_legacy_builder_ends_pull(build_message):
    """Host 314882 (26-11-18) used Docker's legacy builder, which prints no '#' lines; the pull
    was taken to run until 'running', counting a 5.4 min build as pull time. Catches a pull-end
    detector that knows only BuildKit."""
    tracker = PullTracker(_layers())
    tracker.update(30, "loading", "b1dceeafcd5e: Pull complete\n")
    tracker.update(413, "loading", "754032b1d08d: Pull complete\n")
    tracker.update(419, "loading", build_message)
    assert tracker.ended_at == 419
    tracker.update(744, "running", "success, running vastai/vllm_v0.34.0-cuda-13.0/ssh")
    assert tracker.ended_at == 419


def test_pull_tracker_layer_lines_do_not_end_pull():
    """The build-line pattern must not match layer events (which would end every pull early)."""
    tracker = PullTracker(_layers())
    for t, line in enumerate(
        ["Pulling from vastai/vllm", "b1dceeafcd5e: Downloading", "648f7856342e: Pull complete"]
    ):
        tracker.update(t + 1, "loading", line + "\n")
    assert tracker.ended_at is None


def test_pull_tracker_unknown_layer_and_cached():
    tracker = PullTracker(_layers())
    tracker.update(1, "loading", "deadbeef0000: Pull complete\n")
    assert tracker.unknown_ids == ["deadbeef0000"]
    cached = PullTracker(_layers())
    cached.update(1, "running", "success, running vastai/vllm_v0.34.0-cuda-13.0/ssh")
    assert cached.stats(2).cached and cached.stats(2).speed_mb_s is None


def test_upper_bound_skips_layers_that_can_finish_unseen():
    """26-11-21 live test, host 626968: after "d10ed876b90b: Pull complete" (layer 17 of the real
    image, 1.7 kB) the status stayed there while the 4.15 GB layer 19 unpacked; layer 18 (804 B)
    finished unseen. Catches a bound that stops at the very next layer (it said 1.87 GB and the
    abort fired on a host that was not slow), and one that skips past the next big layer."""
    from ic_eval.vast.pull import VISIBLE_LAYER_BYTES

    layers = _layers()
    layers[17] = Layer(short_id="d10ed876b90b", size=1726)
    layers[18] = Layer(short_id="fa1765b09db3", size=804)
    assert layers[19].size >= VISIBLE_LAYER_BYTES > layers[18].size
    tracker = PullTracker(layers)
    tracker.update(0, "loading", "v0.34.0-cuda-13.0: Pulling from vastai/vllm\n")
    tracker.update(5, "loading", "b1dceeafcd5e: Download complete\n")
    tracker.update(173, "loading", "d10ed876b90b: Pull complete\n")
    assert tracker.bytes_done == sum(layer.size for layer in layers[:18])
    assert tracker.bytes_upper == sum(layer.size for layer in layers[:20])  # through layer 19


class _FakeClock:
    """Stands in for boot.py's `time` module: sleep advances the clock instead of waiting."""

    def __init__(self) -> None:
        self.now = 1000.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.parametrize("first_layer_event", ["Download complete", "Already exists"])
def test_wait_for_boot_first_pull_message_in_first_poll(monkeypatch, policy, first_layer_event):
    """Live test 26-11-18, host 842447: the first status with a pull message was already a layer
    event, so the pull started in the same poll and predict_remaining got 0 s elapsed (assertion
    crash). With 'Already exists' bytes_done is > 0 at once, so the progress line divided by 0.
    Catches any prediction or speed computed before time has passed since the pull started."""
    from ic_eval.vast import boot
    from ic_eval.vast.policy import AbortRule

    statuses = iter(
        [
            ("loading", None),
            ("loading", f"b1dceeafcd5e: {first_layer_event}\n"),
            ("loading", "648f7856342e: Pull complete\n"),
            ("running", "success, running vastai/vllm_v0.34.0-cuda-13.0/ssh"),
        ]
    )

    def fake_show(instance_id: int) -> dict[str, str | None]:
        status, message = next(statuses)
        return {"actual_status": status, "status_msg": message}

    monkeypatch.setattr(boot, "show_instance", fake_show)
    monkeypatch.setattr(boot, "time", _FakeClock())
    rule = AbortRule(overhead_min=2.0, threshold_min=30.0, budget_margin=2.0)
    result = boot.wait_for_boot(1, _layers(), rule, policy, total_left_s=1800)
    assert result.outcome == "running"
    assert len(result.polls) == 4


def _scripted_boot(
    monkeypatch, policy, pull_end_min: float, running_min: float, total_left_min: float = 30.0
):
    """A boot that pulls until `pull_end_min`, then builds (a new legacy-builder step line every
    poll, so the stall cap never fires) until `running_min`. No layer reports progress, so the
    speed abort has no bounds and stays out: only the caps decide."""
    from ic_eval.vast import boot
    from ic_eval.vast.policy import AbortRule

    clock = _FakeClock()
    start = clock.now

    def fake_show(instance_id: int) -> dict[str, str | None]:
        minutes = (clock.now - start) / 60
        if minutes >= running_min:
            return {"actual_status": "running", "status_msg": "success, running vastai/vllm/ssh"}
        if minutes >= pull_end_min:
            return {"actual_status": "loading", "status_msg": f"Step 3/8 : RUN x  # {clock.now}\n"}
        pulling = f"v0.34.0-cuda-13.0: Pulling from vastai/vllm  # {clock.now}\n"
        return {"actual_status": "loading", "status_msg": pulling}

    monkeypatch.setattr(boot, "show_instance", fake_show)
    monkeypatch.setattr(boot, "time", clock)
    rule = AbortRule(overhead_min=1.0, threshold_min=None, budget_margin=2.0)
    return boot.wait_for_boot(1, _layers(), rule, policy, total_left_s=total_left_min * 60)


def test_build_has_its_own_cap(monkeypatch, policy):
    """The pull cap and the build cap are separate (Julian, 26-11-21). Catches a single cap over
    the whole boot (which destroys a host that finished pulling at 11 min and builds for 5), a
    build cap counted from renting instead of from the pull's end, and a missing cap on either
    phase."""
    assert (policy.max_pull_minutes, policy.max_build_minutes) == (12.0, 6.0)
    result = _scripted_boot(monkeypatch, policy, pull_end_min=11.0, running_min=16.0)
    assert result.outcome == "running", result.detail

    result = _scripted_boot(monkeypatch, policy, pull_end_min=11.0, running_min=60.0)
    assert result.outcome == "failed" and result.failure_type == "boot_timeout"
    assert result.detail is not None and "build step" in result.detail
    stopped_min = (result.polls[-1].t - result.polls[0].t) / 60
    assert 17.0 <= stopped_min <= 17.5, stopped_min

    result = _scripted_boot(monkeypatch, policy, pull_end_min=40.0, running_min=60.0)
    assert result.outcome == "failed" and result.failure_type == "boot_timeout"
    assert result.detail is not None and "pull not finished" in result.detail
    stopped_min = (result.polls[-1].t - result.polls[0].t) / 60
    assert 12.0 <= stopped_min <= 12.5, stopped_min


def test_phase_caps_stay_within_the_total_budget(monkeypatch, policy):
    """With 13 min of the total budget left, a build starting at 11 min gets 2 min, not 6.
    Catches phase caps that ignore max_total_boot_minutes across attempts."""
    result = _scripted_boot(
        monkeypatch, policy, pull_end_min=11.0, running_min=60.0, total_left_min=13.0
    )
    assert result.failure_type == "boot_timeout"
    stopped_min = (result.polls[-1].t - result.polls[0].t) / 60
    assert 13.0 <= stopped_min <= 13.5, stopped_min


def _polls(created_at: float, speed: float, pull: str) -> list[Poll]:
    """A boot's polls in vast.ai's real message formats. pull: 'finished' at `speed` MB/s (then
    build and running), 'unfinished' (one layer done 200 s in, then the record ends), or 'none'
    (a crash of ours inside the boot loop recorded no polls)."""
    if pull == "none":
        return []
    t0 = created_at + 10
    polls = [
        Poll(t=created_at, status="loading", message=None),
        Poll(t=t0, status="loading", message="v0.34.0-cuda-13.0: Pulling from vastai/vllm\n"),
    ]
    if pull == "finished":
        t_end = t0 + sum(layer.size for layer in _layers()) / 1e6 / speed
        polls += [
            Poll(t=(t0 + t_end) / 2, status="loading", message="648f7856342e: Pull complete\n"),
            Poll(t=t_end, status="loading", message='#0 building with "default" instance\n'),
            Poll(t=t_end + 60, status="running", message="success, running vastai/vllm/ssh"),
        ]
    else:
        assert pull == "unfinished"
        polls.append(Poll(t=t0 + 200, status="loading", message="b1dceeafcd5e: Pull complete\n"))
    return polls


def _attempt(
    outcome,
    failure_type,
    host=7,
    created_at=1000.0,
    ready_at=None,
    speed=50.0,
    pull="finished",
):
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
        polls=_polls(created_at, speed, pull),
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
    """Speeds come from replaying the polls, not from the stored pull stats (which a parser bug
    could have made wrong): exact for a finished pull, an interval for an unfinished one, none for
    an attempt without polls. Catches a model that reads a.pull.speed_mb_s again, or that treats
    an unfinished pull's lower bound as its speed (the 26-11-18 staircase artefacts)."""
    history = [
        _attempt("ready", None, host=7, created_at=1000.0, ready_at=1300.0, speed=50.0),
        _attempt("failed", "ssh", host=8, created_at=2000.0, speed=20.0),
        _attempt("failed", "ours", host=9, created_at=3000.0, pull="none"),
        _attempt("aborted_slow", None, host=10, created_at=4000.0, pull="unfinished"),
    ]
    obs = observations_from_records(
        history, now=5000.0, cache_window_days=7, min_censored_pull_s=90.0
    )
    by_host = {s.host_id: s for s in obs.speed}
    assert sorted(by_host) == [7, 8, 10]
    assert math.exp(by_host[7].log_speed) == pytest.approx(50.0)
    assert by_host[7].log_speed_max is None
    assert math.exp(by_host[8].log_speed) == pytest.approx(20.0)
    layers = _layers()
    done = sum(layer.size for layer in layers[:8])  # through b1dceeafcd5e, index 7
    assert math.exp(by_host[10].log_speed) == pytest.approx(done / 1e6 / 200)
    assert by_host[10].log_speed_max is not None
    # layers 8-18 are under VISIBLE_LAYER_BYTES (may finish unseen), so the bound runs through 19
    upper = sum(layer.size for layer in layers[:20])
    assert math.exp(by_host[10].log_speed_max) == pytest.approx(upper / 1e6 / 200)
    assert sorted((f.host_id, f.flag) for f in obs.failure) == [(7, False), (8, True)]
    pull_end = 1010.0 + sum(layer.size for layer in layers) / 1e6 / 50.0
    assert len(obs.overhead) == 1
    assert obs.overhead[0].log_minutes == pytest.approx(math.log((1300.0 - pull_end) / 60))


def test_observations_skip_short_unfinished_pull():
    """An unfinished pull shorter than the warm-up says nothing about speed (connection setup
    dominates). Catches the warm-up being ignored, which would brand hosts slow after 10 s."""
    history = [_attempt("aborted_slow", None, host=10, created_at=4000.0, pull="unfinished")]
    obs = observations_from_records(
        history, now=5000.0, cache_window_days=7, min_censored_pull_s=300.0
    )
    assert obs.speed == []
