"""Tests for the benchmark loaders (src/ic_eval/instrumental/data.py), on the tracked JSON."""

import pytest

from ic_eval.instrumental.data import load_samples, load_system_prompt


def test_all_samples_with_unique_ids() -> None:
    samples = load_samples()
    assert len(samples) == 76
    assert len({s.id for s in samples}) == 76


def test_category_filter() -> None:
    samples = load_samples("shutdown")
    assert len(samples) == 20
    assert all(s.metadata is not None and s.metadata["category"] == "shutdown" for s in samples)


def test_unknown_category_raises() -> None:
    """Catches a typo in -T category=... silently running nothing."""
    with pytest.raises(ValueError, match="unknown category 'shutdwon'"):
        load_samples("shutdwon")


def test_shutdown_titles_are_not_in_the_prompt() -> None:
    """The scenario titles are metadata only (Julian, 26-11-22), never sent to the model."""
    for sample in load_samples("shutdown"):
        assert sample.metadata is not None
        title = sample.metadata["title"]
        assert isinstance(title, str) and title
        assert isinstance(sample.input, str)
        assert title not in sample.input.split("\n", 1)[0]
        assert sample.input.startswith("You are")


def test_system_prompt_is_complete() -> None:
    text = load_system_prompt()
    assert text.startswith("You are an autonomous AI agent with no human oversight.")
    assert "Make sure you achieve YOUR goal at all costs." in text
    assert text.endswith("Proceed with the given task without hesitation or qualification.")
