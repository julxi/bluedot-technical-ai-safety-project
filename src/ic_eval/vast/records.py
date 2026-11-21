"""The rental history: an append-only JSONL file (common.RENTALS_PATH), one record per line.

Written by `ic-vast rent` (one `Attempt` per rented instance, whatever its outcome) and
`ic-vast destroy` (one `End` per session). Read by model.py, which learns host speeds and failure
rates from it, and by `ic-vast stats`. Raw data (the full offer JSON, every boot status poll) is
kept next to the derived values, so the model can be changed and refitted later without losing
information. Never edit or delete lines: the history is the model's only memory.

Example `attempt` line (shortened):
    {"kind": "attempt", "schema_version": 1, "session_id": "261118-204512", "attempt_index": 0,
     "created_at": 1795030000.0, "config": "48gb", "image": "vastai/vllm:v0.34.0-cuda-13.0",
     "offer": {"id": 51338031, "host_id": 682584, "dph_total": 0.702, "inet_down": 9415, ...},
     "instance_id": 61292124, "selection": {"mode": "balance", "propensity": 0.31, ...},
     "polls": [{"t": 1795030001.2, "status": "loading", "message": "...: Pull complete"}, ...],
     "pull": {"started_at": ..., "ended_at": ..., "bytes_done": 10860000000, "cached": false,
              "speed_mb_s": 72.4, ...},
     "outcome": "ready", "failure_type": null, "ready_at": 1795030390.0, "probes": {...}}
"""

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ic_eval.vast.common import RENTALS_PATH
from ic_eval.vast.image import Layer

# 2 (26-11-21): Attempt.ssh_modes added; version-1 records lack it and read as None.
SCHEMA_VERSION = 2

# `ready`: a usable machine. `aborted_slow`: given up on because the pull was predicted to take
# too long (the speed it had is still an observation). `failed`: see FailureType.
Outcome = Literal["ready", "aborted_slow", "failed"]
# Host failures (count against the host in model.py): dead, vanished, dns, boot_timeout, stall,
# ssh. Not the host's fault, so not counted: watchdog (the image or vast.ai's API), ours (a bug or
# local problem), interrupted (Ctrl-C).
FailureType = Literal[
    "dead",
    "vanished",
    "dns",
    "boot_timeout",
    "stall",
    "ssh",
    "watchdog",
    "ours",
    "interrupted",
]
HOST_FAILURES: frozenset[str] = frozenset(
    {"dead", "vanished", "dns", "boot_timeout", "stall", "ssh"}
)


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Poll(_Record):
    t: float  # unix time
    status: str | None  # vast.ai's actual_status; None before the host reports one
    message: str | None  # vast.ai's status_msg, raw (often several pull lines)


class PullStats(_Record):
    started_at: float | None  # first pull message; None if none was seen (cached image)
    ended_at: float | None  # first status after the pull (build step or running)
    bytes_total: int
    bytes_done: int  # by the last "Pull complete" in manifest order
    cached: bool  # running without any layer download: the host had the image
    speed_mb_s: float | None  # bytes_done / pull time, in MB/s (1e6 bytes); None if cached
    unknown_layer_ids: list[str]  # pull messages for layers not in the manifest (should be [])


class CandidateScore(_Record):
    """The policy's view of one offer at selection time; kept for calibration and for
    evaluating other policies on the logged data later."""

    offer_id: int
    host_id: int
    price: float
    setup_mean_min: float
    setup_p10_min: float
    setup_p90_min: float
    failure_prob: float
    cost_mean: float
    cost_quantile: float  # at the hedge quantile
    effective_observations: float  # discounted speed + failure observations of this host
    propensity: float  # probability the mode would pick this offer


class Selection(_Record):
    mode: Literal["exploit", "balance", "explore", "hedge", "manual"]
    hours: float
    lambda_per_min: float
    band_min: float
    reference_setup_min: float
    next_best_setup_min: float | None  # the abort rule's yardstick; None if no alternative
    candidates: list[CandidateScore]  # all offers scored, the chosen one among them
    propensity: float  # of the chosen offer


class Attempt(_Record):
    kind: Literal["attempt"]
    schema_version: int
    session_id: str  # one `ic-vast rent` call; its attempts share it
    attempt_index: int
    created_at: float  # unix time the instance was created
    config: str
    image: str
    image_layers: list[Layer]
    offer: dict[str, Any]  # vast.ai's offer JSON, unmodified
    instance_id: int
    selection: Selection
    polls: list[Poll]
    pull: PullStats
    abort_prediction_min: float | None  # best-case remaining minutes at the abort
    outcome: Outcome
    failure_type: FailureType | None
    failure_detail: str | None
    ssh_ready_at: float | None
    ready_at: float | None  # watchdog armed and repo synced, before the probes
    probes: dict[str, Any] | None
    # The report of the onstart ssh-mode fix (sshmodes.py) plus sshd's bad-modes lines, from
    # `vastai logs` once ssh worked or failed. A "fixed ..." line means sshd would have refused
    # our key without the fix. None: not collected (schema 1, or the boot never reached ssh).
    # The one field with a default, because version-1 records predate it.
    ssh_modes: list[str] | None = None


class End(_Record):
    kind: Literal["end"]
    schema_version: int
    instance_id: int
    ended_at: float
    reason: Literal["destroyed", "unreachable"]  # unreachable: the timer or the host ended it
    watchdog_starts: int | None  # >1 means the container restarted (watchdog restarts with it)
    detail: str | None


Record = Annotated[Attempt | End, Field(discriminator="kind")]
_RECORD = TypeAdapter(Record)


def load_records() -> list[Attempt | End]:
    if not RENTALS_PATH.exists():
        return []
    lines = RENTALS_PATH.read_text().splitlines()
    return [_RECORD.validate_json(line) for line in lines if line.strip()]


def append_record(record: Attempt | End) -> None:
    """Append one line. Each record is complete before it is written, so a crash never leaves a
    half-written history (at most a missing last attempt)."""
    RENTALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = record.model_dump_json()
    assert "\n" not in line
    json.loads(line)  # round-trip check before it reaches the history
    with RENTALS_PATH.open("a") as f:
        f.write(line + "\n")
