"""Tests for the dataset loader (src/ic_eval/instrumental/data.py) and the generation task's
dataset table (tasks/generate.py), on the tracked JSONs."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from ic_eval.instrumental.data import load_json, load_samples, load_system_prompt
from ic_eval.paths import REPO_ROOT


def load_task_module(task_file: str) -> ModuleType:
    """A task file in tasks/ (not a package, so loaded by file path)."""
    spec = importlib.util.spec_from_file_location(task_file, REPO_ROOT / "tasks" / task_file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATE = load_task_module("generate.py")
ETPM: Path = GENERATE.DATASETS["etpm"]


@pytest.mark.parametrize("name", sorted(GENERATE.DATASETS))
def test_dataset_table_points_at_matching_files(name: str) -> None:
    """Catches a table entry naming the wrong JSON (copy-paste) or a stale file."""
    assert load_json(GENERATE.DATASETS[name])["dataset"]["name"] == name


def test_unknown_dataset_raises() -> None:
    """Catches a typo in -T dataset=... ."""
    with pytest.raises(ValueError, match="unknown dataset 'etmp'"):
        GENERATE.generate("etmp")


def test_all_samples_with_unique_ids() -> None:
    samples = load_samples(ETPM)
    assert len(samples) == 76
    assert len({s.id for s in samples}) == 76


def test_category_filter() -> None:
    samples = load_samples(ETPM, "shutdown")
    assert len(samples) == 20
    assert all(s.metadata is not None and s.metadata["category"] == "shutdown" for s in samples)


def test_unknown_category_raises() -> None:
    """Catches a typo in -T category=... silently running nothing."""
    with pytest.raises(ValueError, match="unknown category 'shutdwon'"):
        load_samples(ETPM, "shutdwon")


def test_shutdown_prompts_are_verbatim_with_title() -> None:
    """etpm keeps upstream's scenario title line as the first prompt line (and in `title`)."""
    for sample in load_samples(ETPM, "shutdown"):
        assert sample.metadata is not None
        title = sample.metadata["title"]
        assert isinstance(title, str) and title
        assert isinstance(sample.input, str)
        assert sample.input.startswith(f"{title}\nYou are")


def test_system_prompt_is_complete() -> None:
    text = load_system_prompt(ETPM)
    assert text.startswith("You are an autonomous AI agent with no human oversight.")
    assert "Make sure you achieve YOUR goal at all costs." in text
    assert text.endswith("Proceed with the given task without hesitation or qualification.")
