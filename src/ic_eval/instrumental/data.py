"""Load the InstrumentalEval benchmark from data/input/instrumental_eval.json.

The JSON is git-tracked; `build_data.py` made it from the upstream repository. Eval runs only
read it here and never touch the network.
"""

import json

from inspect_ai.dataset import Sample

from ic_eval.paths import DATA_INPUT_DIR

JSON_PATH = DATA_INPUT_DIR / "instrumental_eval.json"


def load_samples(category: str | None = None) -> list[Sample]:
    """All benchmark samples, or only those of one category."""

    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)

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


def load_system_prompt() -> str:
    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["system_prompt"]["text"]
