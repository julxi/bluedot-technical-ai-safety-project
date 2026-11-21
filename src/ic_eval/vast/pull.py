"""Image-pull progress from vast.ai's boot status messages, live (boot.py) or replayed (model.py).

The status message shows Docker's pull output ("<layer>: Pull complete"), then vast.ai's build
step. Layer sizes come from Docker Hub (image.py). Every poll is recorded (records.Poll), so the
model re-derives pull speeds by replaying the polls through the current tracker: a parser fix
then corrects old records too, without editing the append-only history.

Speed here is download + unpack of the whole image, in MB/s (1e6 bytes). Progress moves in steps:
only fully unpacked layers count, and this image has layers of 4.15 and 3.33 GB right after its
first 0.37 GB, so "done" can sit still for minutes on a healthy host. A live speed of
done / elapsed therefore decays between steps (26-11-18 live tests: it made the abort fire on no
evidence). Hence bounds, not a point value, while the pull runs (SpeedBounds).
"""

import re
from collections.abc import Sequence
from typing import NamedTuple

from ic_eval.vast.image import Layer
from ic_eval.vast.records import Poll, PullStats

LAYER_LINE = re.compile(r"^([0-9a-f]{12}): (.+)$")
# Layer events that mean bytes crossed the network (not "Already exists": the host had it).
DOWNLOAD_EVENTS = (
    "Downloading",
    "Verifying Checksum",
    "Download complete",
    "Pull complete",
)
DONE_EVENTS = ("Pull complete", "Already exists")
# vast.ai's build step after the pull. Hosts with BuildKit print "#<n> ..." lines; hosts with
# Docker's legacy builder print a deprecation notice, then "Step 3/8 : ..." and " ---> <id>"
# (26-11-18 live test, host 314882: missing these counted a 5.4 min build as pull time and
# halved the recorded pull speed). Matched on stripped lines.
# Layers smaller than this can finish between two polls without their "Pull complete" line ever
# being seen: vast.ai's status shows only the latest pull line(s), and such a layer unpacks within
# one 5-s poll even at 20 MB/s. 26-11-21 live test, host 626968: layers 9-16 (up to 35 MB) passed
# unseen, the tracker took the 804-byte layer 18 for the one in progress while the 4.15 GB layer
# 19 was unpacking, and the abort fired on a host that was not slow. So the upper bound skips
# ahead to the next layer of at least this size.
VISIBLE_LAYER_BYTES = 100_000_000
BUILD_LINE = re.compile(r"^(#\d|DEPRECATED: The legacy builder|Step \d+/\d+ :|---> )")


class SpeedBounds(NamedTuple):
    """Average pull speed so far, MB/s. Equal bounds once the pull has ended (exact speed).

    While it runs: low = fully unpacked bytes / elapsed; high = (those + the layers up to the next
    big one, which is or is still ahead of the one being unpacked; PullTracker.bytes_upper) /
    elapsed, because layers unpack one after another in manifest order, so less
    than that can be done. Julian's suggestion, 26-11-18. The bounds are about the time observed
    so far: later the speed can be higher (downloads run in parallel first, unpacking follows),
    so `high` is not a bound on the whole pull's speed.
    """

    low_mb_s: float
    high_mb_s: float
    elapsed_s: float

    @property
    def exact(self) -> bool:
        return self.low_mb_s == self.high_mb_s


class PullTracker:
    """Pull progress from the stream of status messages.

    Docker unpacks layers in manifest order, so the highest-index layer reported done implies all
    before it are done; bytes_done is their cumulative size. The pull starts with the first pull
    message and ends at the first line of vast.ai's build step after the pull (BUILD_LINE: BuildKit
    or legacy builder) or when the instance runs.
    """

    def __init__(self, layers: Sequence[Layer]):
        self.layers = list(layers)
        # first copy of a repeated (tiny) layer; see image.fetch_layers
        self.index: dict[str, int] = {}
        for i, layer in enumerate(self.layers):
            self.index.setdefault(layer.short_id, i)
        self.cumulative = [
            sum(layer.size for layer in self.layers[: i + 1]) for i in range(len(self.layers))
        ]
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

    @property
    def bytes_upper(self) -> int:
        """More than this cannot be unpacked yet: through the next layer of at least
        VISIBLE_LAYER_BYTES after the last one seen done. Smaller layers in between may have
        finished unseen, so stopping at the very next layer would understate the bound."""
        if self.ended_at is not None:
            return self.bytes_total
        j = self.done_index + 1
        while j < len(self.layers) - 1 and self.layers[j].size < VISIBLE_LAYER_BYTES:
            j += 1
        return self.cumulative[min(j, len(self.layers) - 1)]

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
        building = any(BUILD_LINE.match(line) for line in lines)
        if (
            self.started_at is not None
            and self.ended_at is None
            and (building or status == "running")
        ):
            self.ended_at = t

    def speed_bounds(self, now: float) -> SpeedBounds | None:
        """None while nothing is known: no pull started, the image was cached, or no time passed."""
        if self.started_at is None or not self.downloaded:
            return None
        end = self.ended_at if self.ended_at is not None else now
        elapsed = end - self.started_at
        if elapsed <= 0:
            return None
        return SpeedBounds(
            low_mb_s=self.bytes_done / 1e6 / elapsed,
            high_mb_s=self.bytes_upper / 1e6 / elapsed,
            elapsed_s=elapsed,
        )

    def stats(self, now: float) -> PullStats:
        bounds = self.speed_bounds(now)
        return PullStats(
            started_at=self.started_at,
            ended_at=self.ended_at,
            bytes_total=self.bytes_total,
            bytes_done=self.bytes_done,
            cached=not self.downloaded,
            # the lower bound while unfinished; kept for the record, the model replays polls
            speed_mb_s=bounds.low_mb_s if bounds is not None and bounds.low_mb_s > 0 else None,
            unknown_layer_ids=list(self.unknown_ids),
        )


def replay(layers: Sequence[Layer], polls: Sequence[Poll]) -> PullTracker:
    """The tracker's state after the recorded polls, as the current code reads them."""
    tracker = PullTracker(layers)
    for poll in polls:
        tracker.update(poll.t, poll.status, poll.message)
    return tracker
