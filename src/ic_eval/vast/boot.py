"""Watch a rented instance boot, measure its image pull, and give up on it early when it is slow.

Every poll of vast.ai's status is kept (records.Poll). The pull messages in it ("<layer>: Pull
complete") give the bytes unpacked so far (image.py); from them the live pull speed, combined with
the host's posterior, predicts the remaining time, and the boot is aborted when switching to the
next-best offer is predicted to be faster by more than the tolerance band (policy.AbortRule).
Hard caps (total boot time, a status that stops changing) stay on top of that.
"""

import re
import time
from typing import Literal, NamedTuple

from ic_eval.vast.common import log
from ic_eval.vast.config import PolicyConfig
from ic_eval.vast.image import Layer
from ic_eval.vast.market import show_instance
from ic_eval.vast.policy import AbortRule, predict_remaining
from ic_eval.vast.records import FailureType, Poll, PullStats

POLL_INTERVAL_S = 5
# vast.ai reports these when the host has dropped off its control plane. It keeps claiming
# intended_status "running", but the container never finishes provisioning.
DEAD_STATUSES = frozenset({"missing", "exited"})
# A boot status containing this means the host cannot resolve vast.ai's own servers; such a host
# never finishes booting (SPD repo, host 124072 on 26-10-06).
DNS_FAILURE_MARKER = "resolve host"
LAYER_LINE = re.compile(r"^([0-9a-f]{12}): (.+)$")
# Layer events that mean bytes crossed the network (not "Already exists": the host had it).
DOWNLOAD_EVENTS = (
    "Downloading",
    "Verifying Checksum",
    "Download complete",
    "Pull complete",
)
DONE_EVENTS = ("Pull complete", "Already exists")


class BootResult(NamedTuple):
    outcome: Literal["running", "aborted_slow", "failed"]
    failure_type: FailureType | None
    detail: str | None
    polls: list[Poll]
    pull: PullStats
    abort_prediction_min: float | None


class PullTracker:
    """Pull progress from the stream of status messages.

    Docker unpacks layers in manifest order, so the highest-index layer reported done implies all
    before it are done; bytes_done is their cumulative size. The pull starts with the first pull
    message and ends at the first BuildKit line ("#0 building ...", vast.ai's step after the pull)
    or when the instance runs.
    """

    def __init__(self, layers: list[Layer]):
        self.layers = layers
        # first copy of a repeated (tiny) layer; see image.fetch_layers
        self.index: dict[str, int] = {}
        for i, layer in enumerate(layers):
            self.index.setdefault(layer.short_id, i)
        self.cumulative = [sum(layer.size for layer in layers[: i + 1]) for i in range(len(layers))]
        self.bytes_total = self.cumulative[-1]
        self.done_index = -1
        self.started_at: float | None = None
        self.ended_at: float | None = None
        self.downloaded = False
        self.unknown_ids: list[str] = []

    @property
    def bytes_done(self) -> int:
        if self.ended_at is not None:
            return self.bytes_total
        return self.cumulative[self.done_index] if self.done_index >= 0 else 0

    def update(self, t: float, status: str | None, message: str | None) -> None:
        lines = [line.strip() for line in (message or "").splitlines() if line.strip()]
        for line in lines:
            match = LAYER_LINE.match(line)
            if (match is not None or "Pulling from" in line) and self.started_at is None:
                self.started_at = t
            if match is None:
                continue
            short_id, event = match.groups()
            if short_id not in self.index:
                if short_id not in self.unknown_ids:
                    self.unknown_ids.append(short_id)
                continue
            if event.startswith(DOWNLOAD_EVENTS):
                self.downloaded = True
            if event.startswith(DONE_EVENTS):
                self.done_index = max(self.done_index, self.index[short_id])
        building = any(line.startswith("#") for line in lines)
        if (
            self.started_at is not None
            and self.ended_at is None
            and (building or status == "running")
        ):
            self.ended_at = t

    def stats(self, now: float) -> PullStats:
        cached = not self.downloaded
        speed = None
        if not cached and self.started_at is not None:
            end = self.ended_at if self.ended_at is not None else now
            if end > self.started_at and self.bytes_done > 0:
                speed = self.bytes_done / 1e6 / (end - self.started_at)
        return PullStats(
            started_at=self.started_at,
            ended_at=self.ended_at,
            bytes_total=self.bytes_total,
            bytes_done=self.bytes_done,
            cached=cached,
            speed_mb_s=speed,
            unknown_layer_ids=list(self.unknown_ids),
        )


def wait_for_boot(
    instance_id: int,
    layers: list[Layer],
    rule: AbortRule,
    policy: PolicyConfig,
    budget_s: float,
) -> BootResult:
    """Poll until the instance runs, fails, or is given up on. Never destroys it (the caller does).

    `budget_s` is the boot time left for this attempt: min(max_boot_minutes, what remains of
    max_total_boot_minutes across attempts).
    """
    start = time.time()
    tracker = PullTracker(layers)
    polls: list[Poll] = []
    last_change = start
    last_seen: tuple[str | None, str | None] | None = None
    last_logged = ""

    def result(outcome, failure_type, detail, prediction=None) -> BootResult:
        if tracker.unknown_ids:
            log(
                f"WARNING: pull messages for layers not in the manifest: {tracker.unknown_ids} - "
                f"the image tag's layers may have changed; progress is unreliable"
            )
        return BootResult(
            outcome, failure_type, detail, polls, tracker.stats(time.time()), prediction
        )

    while True:
        now = time.time()
        shown = show_instance(instance_id)
        if shown is None:
            polls.append(Poll(t=now, status=None, message="<instance no longer exists>"))
            return result("failed", "vanished", "the host dropped the rental")
        status, message = shown["actual_status"], shown["status_msg"]
        polls.append(Poll(t=now, status=status, message=message))
        tracker.update(now, status, message)
        if (status, message) != last_seen:
            last_seen, last_change = (status, message), now
        if status == "running":
            return result("running", None, None)
        if status in DEAD_STATUSES:
            return result("failed", "dead", f"instance went '{status}' while booting ({message})")
        if message and DNS_FAILURE_MARKER in message:
            return result("failed", "dns", f"cannot resolve vast.ai's servers: {message}")
        if now - start > budget_s:
            return result("failed", "boot_timeout", f"not running after {budget_s / 60:.1f} min")
        if now - last_change > policy.stall_minutes * 60:
            return result(
                "failed",
                "stall",
                f"status unchanged for {policy.stall_minutes} min: {message}",
            )
        progress = _progress_line(tracker, rule, now)
        line = f"{status} | {progress}" if progress else f"{status} ({_last_line(message)})"
        if line != last_logged:
            log(f"Boot: {line}")
            last_logged = line
        if tracker.started_at is not None and tracker.ended_at is None:
            pulled_s = now - tracker.started_at
            prediction = predict_remaining(rule, tracker.bytes_done, tracker.bytes_total, pulled_s)
            if (
                pulled_s >= policy.abort_warmup_seconds
                and prediction is not None
                and rule.threshold_min is not None
                and prediction > rule.threshold_min
            ):
                return result(
                    "aborted_slow",
                    None,
                    f"predicted {prediction:.1f} more min > {rule.threshold_min:.1f} min for the "
                    f"next-best offer (switch included)",
                    prediction,
                )
        time.sleep(POLL_INTERVAL_S)


def _progress_line(tracker: PullTracker, rule: AbortRule, now: float) -> str | None:
    if tracker.started_at is None or tracker.ended_at is not None or tracker.bytes_done == 0:
        return None
    pulled_s = now - tracker.started_at
    speed = tracker.bytes_done / 1e6 / pulled_s
    prediction = predict_remaining(rule, tracker.bytes_done, tracker.bytes_total, pulled_s)
    limit = f", abort above {rule.threshold_min:.1f}" if rule.threshold_min is not None else ""
    return (
        f"pulled {tracker.bytes_done / 1e9:.2f}/{tracker.bytes_total / 1e9:.2f} GB at "
        f"{speed:.0f} MB/s, ~{prediction:.1f} min to ready{limit}"
    )


def _last_line(message: str | None) -> str:
    lines = [line for line in (message or "").splitlines() if line.strip()]
    return lines[-1].strip()[:80] if lines else "no message"
