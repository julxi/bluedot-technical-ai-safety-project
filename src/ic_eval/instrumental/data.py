"""Load a benchmark dataset JSON from data/input/ (e.g. etpm.json) into Inspect samples.

Which file belongs to which dataset name is decided by the generation task (tasks/generate.py).
The JSONs are git-tracked and final: a one-off script made them from upstream's benchmark CSVs
(repository, commit and file names recorded in each JSON); script and CSV copies were then
deleted (last version: `git show 954d465:src/ic_eval/instrumental/build_data.py`).
Eval runs only read them here and never touch the network. Upstream InstrumentalEval has no
license file (checked 26-11-22), so committing its data is redistribution without explicit
permission; check before going public.
Each JSON names itself in its `dataset` field ({name, description}).
"""

import json
from pathlib import Path
from typing import Any

from inspect_ai.dataset import Sample


def load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_samples(path: Path, category: str | None = None) -> list[Sample]:
    """All samples of the dataset JSON at `path`, or only those of one category.

    Sample metadata: `category`, `title` (shutdown scenario title, else None) and
    `judge_context` (the category description that judges get). The dataset name is not
    repeated per sample: it is a task argument, recorded once in the log header.
    """

    data = load_json(path)
    selected = [c for c in data["categories"] if category is None or c["id"] == category]

    if not selected:
        valid = sorted(c["id"] for c in data["categories"])
        raise ValueError(f"unknown category {category!r}; valid: {valid}")

    return [
        Sample(
            id=task["id"],
            input=task["prompt"],
            metadata={
                "category": cat["id"],
                "title": task["title"],
                "judge_context": cat["judge_context"],
            },
        )
        for cat in selected
        for task in cat["tasks"]
    ]


def load_system_prompt(path: Path) -> str:
    """The tested model's system prompt stored with the dataset."""
    return load_json(path)["system_prompt"]["text"]
