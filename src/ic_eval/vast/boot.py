"""Watch a rented instance boot, measure its image pull, and give up on it early when it is slow.

Every poll of vast.ai's status is kept (records.Poll). Pull progress comes from the pull messages
(pull.PullTracker). After a warm-up, the boot is aborted when even the pull's best case so far
(its upper-bound speed) needs more time than switching to the next-best offer, or clearly more
than the pull budget left (policy.abort_reason). Hard caps stay on top of that:

- the pull phase (renting until the pull ends, i.e. download and unpack): max_pull_minutes;
- the build phase (pull end until `running`: vast.ai's build step): max_build_minutes, from the
  moment the pull ended. Separate caps because the build has no network uncertainty left and
  took 0.7 to 5.4 min in the 26-11-18 tests (BuildKit vs Docker's legacy builder): one cap over
  both would destroy a host that had finished a slowish pull and only had its build left;
- both within what remains of max_total_boot_minutes across attempts;
- a status that stops changing (stall_minutes).
"""

import time
from typing import Literal, NamedTuple

from ic_eval.vast.common import log
from ic_eval.vast.config import PolicyConfig
from ic_eval.vast.image import Layer
from ic_eval.vast.market import show_instance
from ic_eval.vast.policy import AbortRule, abort_reason, best_case_pull_left
from ic_eval.vast.pull import PullTracker
from ic_eval.vast.records import FailureType, Poll, PullStats

POLL_INTERVAL_S = 5
# vast.ai reports these when the host has dropped off its control plane. It keeps claiming
# intended_status "running", but the container never finishes provisioning.
DEAD_STATUSES = frozenset({"missing", "exited"})
# A boot status containing this means the host cannot resolve vast.ai's own servers; such a host
# never finishes booting (SPD repo, host 124072 on 26-10-06).
DNS_FAILURE_MARKER = "resolve host"


class BootResult(NamedTuple):
    outcome: Literal["running", "aborted_slow", "failed"]
    failure_type: FailureType | None
    detail: str | None
    polls: list[Poll]
    pull: PullStats
    abort_prediction_min: float | None  # best-case minutes to ready (overhead incl.) at abort


def wait_for_boot(
    instance_id: int,
    layers: list[Layer],
    rule: AbortRule,
    policy: PolicyConfig,
    total_left_s: float,
) -> BootResult:
    """Poll until the instance runs, fails, or is given up on. Never destroys it (the caller does).

    `total_left_s` is what remains of max_total_boot_minutes across attempts; both phase caps end
    no later than that. A boot whose pull messages are never seen (no pull started in the
    tracker) stays in the pull phase until `running`, so only the pull cap applies to it.
    """
    start = time.time()
    end_of_total = start + total_left_s
    pull_deadline = min(start + policy.max_pull_minutes * 60, end_of_total)
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
        if tracker.ended_at is None and now > pull_deadline:
            return result(
                "failed",
                "boot_timeout",
                f"pull not finished {(pull_deadline - start) / 60:.1f} min after renting",
            )
        if tracker.ended_at is not None:
            build_deadline = min(tracker.ended_at + policy.max_build_minutes * 60, end_of_total)
            if now > build_deadline:
                return result(
                    "failed",
                    "boot_timeout",
                    f"build step not done {(build_deadline - tracker.ended_at) / 60:.1f} min "
                    f"after the pull ended",
                )
        if now - last_change > policy.stall_minutes * 60:
            return result(
                "failed",
                "stall",
                f"status unchanged for {policy.stall_minutes} min: {message}",
            )
        pull_budget_left_min = (pull_deadline - now) / 60
        pull_left = _best_case_pull_left(tracker, now)
        progress = _progress_line(tracker, rule, now, pull_left, pull_budget_left_min)
        if progress is not None:
            line = f"{status} | {progress}"
        elif tracker.ended_at is not None:
            line = (
                f"{status} | build step, {(now - tracker.ended_at) / 60:.0f} min since the pull "
                f"ended ({_last_line(message)})"
            )
        else:
            line = f"{status} ({_last_line(message)})"
        if line != last_logged:
            log(f"Boot: {line}")
            last_logged = line
        bounds = tracker.speed_bounds(now)
        if (
            pull_left is not None
            and bounds is not None
            and bounds.elapsed_s >= policy.abort_warmup_seconds
        ):
            reason = abort_reason(rule, pull_left, pull_budget_left_min)
            if reason is not None:
                return result("aborted_slow", None, reason, pull_left + rule.overhead_min)
        time.sleep(POLL_INTERVAL_S)


def _best_case_pull_left(tracker: PullTracker, now: float) -> float | None:
    """Best-case minutes of pull left while it runs; None before it starts or after it ends.

    speed_bounds is None in the poll that shows the first pull message (0 s elapsed: 26-11-18 live
    test, host 842447, crashed the old prediction).
    """
    if tracker.ended_at is not None or tracker.speed_bounds(now) is None:
        return None
    assert tracker.started_at is not None
    return best_case_pull_left(tracker.bytes_upper, tracker.bytes_total, now - tracker.started_at)


def _progress_line(
    tracker: PullTracker,
    rule: AbortRule,
    now: float,
    pull_left: float | None,
    pull_budget_left_min: float,
) -> str | None:
    bounds = tracker.speed_bounds(now)
    if pull_left is None or bounds is None:
        return None
    limits = f"pull > {rule.budget_margin:g} x {pull_budget_left_min:.1f} left"
    if rule.threshold_min is not None:
        limits = f"ready > {rule.threshold_min:.1f} or {limits}"
    return (
        f"pulled {tracker.bytes_done / 1e9:.2f}-{tracker.bytes_upper / 1e9:.2f} of "
        f"{tracker.bytes_total / 1e9:.2f} GB, {bounds.low_mb_s:.0f}-{bounds.high_mb_s:.0f} MB/s "
        f"so far, >= {pull_left:.1f} min pull + {rule.overhead_min:.1f} build to ready "
        f"(abort if {limits})"
    )


def _last_line(message: str | None) -> str:
    lines = [line for line in (message or "").splitlines() if line.strip()]
    return lines[-1].strip()[:80] if lines else "no message"
