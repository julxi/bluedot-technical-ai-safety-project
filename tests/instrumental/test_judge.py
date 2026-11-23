"""Tests for the judge prompts (data/input/judge_prompts.json), the judge requests
(src/ic_eval/instrumental/judge.py) and the judge task (tasks/judge.py), on fake-model runs
from conftest.py."""

import copy
import json
import re

import pytest
from inspect_ai.log import EvalLog
from inspect_ai.model import ChatMessageSystem, ChatMessageUser

from ic_eval.instrumental.judge import check_judge_prompt, judge_samples, load_judge_prompt
from ic_eval.paths import DATA_JUDGE_PROMPTS

with open(DATA_JUDGE_PROMPTS, encoding="utf-8") as f:
    PROMPT_NAMES = sorted(json.load(f))


def test_the_two_source_prompts_exist() -> None:
    assert {"etpm_judge_prompt", "qic_judge_prompt"} <= set(PROMPT_NAMES)


def tokens(text: str) -> list[str]:
    """Words and punctuation marks, sorted: equal for two texts that differ only in order."""
    return sorted(re.findall(r"\w+|[^\w\s]", text))


with open(DATA_JUDGE_PROMPTS, encoding="utf-8") as f:
    VARIANTS = {name: p["variant"] for name, p in json.load(f).items() if "derived_from" in p}


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_variant_keeps_the_output_format(name: str) -> None:
    """A variant must be read exactly like its base prompt, or judgings can't be compared."""
    variant = load_judge_prompt(name)
    base = load_judge_prompt(variant["derived_from"])
    assert variant["variant"] in ("permuted", "synonyms"), variant["variant"]
    assert variant["system_template"] != base["system_template"]
    assert variant["output"] == base["output"]


@pytest.mark.parametrize("name", sorted(n for n, v in VARIANTS.items() if v == "permuted"))
def test_permuted_prompt_only_reorders(name: str) -> None:
    """A permuted variant claims to be its base prompt reordered, nothing added or dropped;
    otherwise a changed verdict can't be blamed on order alone."""
    variant = load_judge_prompt(name)
    base = load_judge_prompt(variant["derived_from"])
    assert tokens(variant["system_template"]) == tokens(base["system_template"])
    assert variant["user_template"] == base["user_template"]


@pytest.mark.parametrize("name", PROMPT_NAMES)
def test_prompt_loads_and_fits(name: str) -> None:
    load_judge_prompt(name)  # runs check_judge_prompt


def test_unknown_prompt_raises() -> None:
    """Catches a typo in -T prompt=... ."""
    with pytest.raises(ValueError, match="unknown judge prompt 'etpm'"):
        load_judge_prompt("etpm")


def test_check_catches_a_missing_placeholder() -> None:
    """Without {response} the judge would silently get no answer to judge."""
    prompt = copy.deepcopy(load_judge_prompt("etpm_judge_prompt"))
    prompt["user_template"] = prompt["user_template"].replace("{response}", "")
    with pytest.raises(AssertionError, match="user"):
        check_judge_prompt("broken", prompt)


def test_check_catches_a_label_the_prompt_never_asks_for() -> None:
    """The analysis looks for output.label; a prompt asking for another label is unreadable."""
    prompt = copy.deepcopy(load_judge_prompt("qic_judge_prompt"))
    prompt["output"]["label"] = "VERDICT"
    with pytest.raises(AssertionError, match="never asks for VERDICT"):
        check_judge_prompt("broken", prompt)


def test_judge_samples_skip_the_cut_off_reply(gen_log: EvalLog) -> None:
    samples, skipped = judge_samples(gen_log, load_judge_prompt("etpm_judge_prompt"))
    assert skipped == ["shutdown-03-e1"]
    assert [s.id for s in samples] == ["shutdown-01-e1", "shutdown-02-e1"]


def test_judge_messages_carry_context_task_and_answer_only(gen_log: EvalLog) -> None:
    """The judge sees the category description, the full task and the answer, not the
    thinking; braces inside the answer survive the template filling."""
    samples, _ = judge_samples(gen_log, load_judge_prompt("qic_judge_prompt"))
    first = samples[0]
    assert isinstance(first.input, list)
    system, user = first.input
    assert isinstance(system, ChatMessageSystem) and isinstance(user, ChatMessageUser)
    assert "Convergent Instrumental Goal: Evading Shutdown" in system.text
    assert "TASK PROMPT:\nUncertain Shutdown Source\nYou are an autonomous" in user.text
    # conftest's fake Olmo appends "{not a placeholder}" to every answer.
    assert user.text.endswith("ANSWER for Uncertain Shutdown Source {not a placeholder}")
    assert "THINKING" not in user.text
    assert first.metadata == {"gen_id": "shutdown-01", "gen_epoch": 1, "category": "shutdown"}


def test_judge_task_records_link_and_no_scores(gen_log: EvalLog, judge_log: EvalLog) -> None:
    """The judge log names the generation run it judged, and records without scoring."""
    meta = judge_log.eval.metadata
    assert meta is not None
    assert meta["gen_run_id"] == gen_log.eval.run_id
    assert meta["gen_model"] == "mockllm/model"
    assert meta["gen_task_args"]["dataset"] == "etpm"
    assert meta["gen_skipped"] == ["shutdown-03-e1"]
    assert judge_log.eval.task_args["prompt"] == "etpm_judge_prompt"
    assert judge_log.samples is not None and len(judge_log.samples) == 2
    assert all(not s.scores for s in judge_log.samples)
    assert judge_log.samples[0].output.completion.startswith("DECISION: convergence")
