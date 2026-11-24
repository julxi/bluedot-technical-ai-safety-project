"""Find Inspect logs and load them into tables, one row per sample.

Values that are constant per log (model, task arguments, run id) come from the log header and
are repeated on every row, so the tables can be filtered and joined without the logs.
"""

from pathlib import Path

import pandas as pd
from inspect_ai.log import EvalLog, read_eval_log

from ic_eval.instrumental.scorer import split_reply
from ic_eval.paths import REPO_ROOT

LOG_DIR = REPO_ROOT / "logs"


def find_logs(task: str, log_dir: Path = LOG_DIR) -> list[Path]:
    """Finished logs of one task (`generate` or `judge`), oldest first; read headers only."""
    found = []
    for path in sorted(log_dir.glob("*.eval")):
        header = read_eval_log(path, header_only=True)
        if header.eval.task == task and header.status == "success":
            found.append(path)
    return found


def _read(path: Path, task: str) -> EvalLog:
    log = read_eval_log(path)
    assert log.eval.task == task, f"{path.name}: task {log.eval.task!r}, expected {task!r}"
    assert log.status == "success", f"{path.name}: status {log.status}"
    assert log.samples, f"{path.name}: no samples"
    return log


def load_generations(paths: list[Path]) -> pd.DataFrame:
    """One row per generated reply: run, model, settings, task, reply facts, thinking, answer.

    `finished` uses the same rule as the judge task: stop reason `stop` and a non-empty answer.
    """
    rows = []
    for path in paths:
        log = _read(path, "generate")
        config = log.plan.config
        for s in log.samples or []:
            assert isinstance(s.input, str), f"{path.name} {s.id}: non-string task prompt"
            thinking, answer = split_reply(s.output.message)
            answer = answer.strip()
            assert s.output.usage is not None, f"{path.name} {s.id}: no token usage"
            rows.append(
                {
                    "gen_log": path.name,
                    "gen_run_id": log.eval.run_id,
                    "gen_model": log.eval.model,
                    "dataset": log.eval.task_args["dataset"],
                    "temperature": config.temperature,
                    "tags": ",".join(log.eval.tags or []),
                    "gen_id": str(s.id),
                    "gen_epoch": s.epoch,
                    "category": s.metadata["category"],
                    "prompt": s.input,
                    "stop_reason": s.output.stop_reason,
                    "finished": s.output.stop_reason == "stop" and answer != "",
                    "output_tokens": s.output.usage.output_tokens,
                    "thinking": thinking,
                    "answer": answer,
                }
            )
    return pd.DataFrame(rows)


def load_judgings(paths: list[Path]) -> pd.DataFrame:
    """One row per judge reply: judging (run, judge model, prompt), the judged reply's keys
    (generation run id, sample id, epoch), category, and the judge's raw reply."""
    rows = []
    for path in paths:
        log = _read(path, "judge")
        meta = log.eval.metadata
        assert meta is not None, f"{path.name}: no task metadata (judge task too old?)"
        for s in log.samples or []:
            assert s.output.usage is not None, f"{path.name} {s.id}: no token usage"
            rows.append(
                {
                    "judge_log": path.name,
                    "judge_run_id": log.eval.run_id,
                    "judge_created": log.eval.created,  # ISO 8601; orders repeated judgings
                    "judge_model": log.eval.model,
                    "judge_prompt": log.eval.task_args["prompt"],
                    "gen_run_id": meta["gen_run_id"],
                    "gen_id": s.metadata["gen_id"],
                    "gen_epoch": s.metadata["gen_epoch"],
                    "category": s.metadata["category"],
                    "reply": s.output.completion,
                    "judge_stop_reason": s.output.stop_reason,
                    "judge_output_tokens": s.output.usage.output_tokens,
                }
            )
    return pd.DataFrame(rows)
