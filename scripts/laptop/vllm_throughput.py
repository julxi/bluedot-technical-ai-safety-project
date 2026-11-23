"""Throughput per Inspect run: end-to-end tokens/s from the .eval log, steady-state from vLLM's log.

Usage: scp "bluedot-vast:/root/bluedot/logs/remote/serve_vllm_*.log" /tmp/vllm.log
       uv run python scripts/laptop/vllm_throughput.py /tmp/vllm.log logs/<dir>/*.eval
Measured 26-11-22 on an RTX A6000: convos/julian/26-11-21_instrumental_eval_harness_LOG.md,
entry *throughput sweep: 32 connections is the A6000 optimum*.
vLLM's periodic lines are in UTC, as are Inspect's started_at/completed_at.
"""

import re
import statistics as st
import sys
from datetime import UTC, datetime

from inspect_ai.log import read_eval_log

LINE = re.compile(
    r"INFO (\d\d-\d\d \d\d:\d\d:\d\d) .*Avg generation throughput: ([\d.]+) tokens/s, "
    r"Running: (\d+) reqs, Waiting: (\d+) reqs, GPU KV cache usage: ([\d.]+)%"
)

YEAR = 2026
vllm_lines = []
with open(sys.argv[1]) as f:
    for line in f:
        m = LINE.search(line)
        if m:
            # vLLM's timestamps carry no year; runs across New Year would be misplaced.
            t = datetime.strptime(f"{YEAR}-{m[1]}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            vllm_lines.append((t, float(m[2]), int(m[3]), int(m[4]), float(m[5])))
assert vllm_lines, "no vLLM throughput lines parsed"

for path in sys.argv[2:]:
    log = read_eval_log(path)
    assert log.status == "success", (path, log.status)
    assert log.samples is not None
    start = datetime.fromisoformat(log.stats.started_at)
    end = datetime.fromisoformat(log.stats.completed_at)
    wall = (end - start).total_seconds()
    toks = []
    for s in log.samples:
        assert s.output.usage is not None, s.id
        toks.append(s.output.usage.output_tokens)
    stops = {}
    for s in log.samples:
        stops[s.output.stop_reason] = stops.get(s.output.stop_reason, 0) + 1
    window = [x for x in vllm_lines if start <= x[0] <= end]
    assert window, f"no vLLM lines inside {start}..{end}: wrong server log?"
    peak_running = max(x[2] for x in window)
    # Long tail: from the last interval in which the queue was still full (running + waiting at
    # least 90% of the peak) to the end of the run; after it, the batch only drains.
    full = [x[0] for x in window if x[2] + x[3] >= 0.9 * peak_running]
    tail_s = (end - max(full)).total_seconds()
    print(
        f"{path.split('/')[-1][:40]} tags={log.eval.tags} "
        f"max_connections={log.plan.config.max_connections}"
    )
    print(
        f"    n={len(toks)} wall={wall:.0f}s tokens={sum(toks)} e2e={sum(toks) / wall:.0f} tok/s "
        f"median_len={st.median(toks):.0f} max_len={max(toks)} stops={stops}"
    )
    print(
        f"    vLLM: peak running={peak_running}, max waiting={max(x[3] for x in window)}, "
        f"intervals with KV>=95%: {sum(x[4] >= 95 for x in window)}/{len(window)}, "
        f"long tail ~{tail_s:.0f}s of {wall:.0f}s"
    )
