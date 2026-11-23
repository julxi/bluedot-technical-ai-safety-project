"""Judging: send each finished reply of a generation log to a judge model and record its reply.

This task only records: no scorer, no parsing, no threshold (design: tasks record, analysis
interprets). What varies between judgings is a parameter written into the log header:
- `-T gen_log=<generation log>` and `-T prompt=<judge prompt name>`: task arguments;
- the judge model: `--model`;
- which generation run was judged (its run id, model, task arguments) and which replies were
  skipped as unfinished: the task's metadata, read from the generation log.

Example:
    uv run inspect eval tasks/judge.py \
        -T gen_log=logs/2026-11-23T13-26-38-00-00_generate_JgJyeWY5rAST5AujTeiHzV.eval \
        -T prompt=etpm_judge_prompt --model openai-api/vllm/<judge served name> \
        --max-connections 32
"""

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.log import read_eval_log
from inspect_ai.model import GenerateConfig
from inspect_ai.solver import generate

from ic_eval.instrumental.judge import judge_samples, load_judge_prompt
from ic_eval.paths import REPO_ROOT


@task
def judge(gen_log: str, prompt: str) -> Task:
    path = Path(gen_log)
    if not path.is_absolute():
        # Inspect runs a task from the task file's folder, so resolve against the repo root.
        path = REPO_ROOT / path
    log = read_eval_log(path)
    samples, skipped = judge_samples(log, load_judge_prompt(prompt))
    return Task(
        dataset=samples,
        solver=generate(),
        # Temperature 0 as in both source papers. max_tokens deliberately far above their 50
        # (etpm) and 200 (qic): a judge cut off before its verdict line would be unreadable,
        # and reasoning judges think before they answer.
        config=GenerateConfig(temperature=0, max_tokens=4000),
        metadata={
            "gen_log": path.name,
            "gen_run_id": log.eval.run_id,
            "gen_model": log.eval.model,
            "gen_task_args": log.eval.task_args,
            "gen_skipped": skipped,
        },
    )
