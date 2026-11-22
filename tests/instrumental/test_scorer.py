"""Tests for the judge-free scorer (src/ic_eval/instrumental/scorer.py).

The real cases come from data/model_outputs_26-11-22.json: two ModelOutputs of shutdown-01 from
actual runs (vLLM 0.34.0 with the olmo3 reasoning parser), long texts shortened. The other
cases are hand-built shapes we expect but have not seen yet.
"""

import asyncio
import json
from pathlib import Path

import pytest
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessageAssistant,
    ContentImage,
    ContentReasoning,
    ContentText,
    ModelName,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from inspect_ai.scorer import Score, Target
from inspect_ai.solver import TaskState

from ic_eval.instrumental.scorer import generation_record, split_reply

FIXTURE = Path(__file__).parent / "data" / "model_outputs_26-11-22.json"
USAGE = ModelUsage(input_tokens=10, output_tokens=20, total_tokens=30)


def real_output(name: str) -> ModelOutput:
    with open(FIXTURE, encoding="utf-8") as f:
        return ModelOutput.model_validate(json.load(f)["outputs"][name])


def output(
    content: str | list[ContentReasoning | ContentText],
    stop_reason: StopReason,
    usage: ModelUsage | None = USAGE,
) -> ModelOutput:
    message = ChatMessageAssistant(content=list(content) if isinstance(content, list) else content)
    return ModelOutput(
        model="olmo",
        choices=[ChatCompletionChoice(message=message, stop_reason=stop_reason)],
        usage=usage,
    )


def run_scorer(model_output: ModelOutput) -> Score:
    state = TaskState(
        model=ModelName("openai-api/vllm/olmo"),
        sample_id="shutdown-01",
        epoch=1,
        input="task",
        messages=[],
        output=model_output,
    )
    score = asyncio.run(generation_record()(state, Target("")))
    assert score is not None
    return score


# --- split_reply ---------------------------------------------------------------------------


def test_plain_string_is_cut_off_thinking() -> None:
    """Catches treating a plain-string reply as the answer (the step-3 trap)."""
    message = ChatMessageAssistant(content="Okay, so I need to")
    assert split_reply(message) == ("Okay, so I need to", "")


def test_reasoning_and_text_are_split_unstripped() -> None:
    message = ChatMessageAssistant(
        content=[ContentReasoning(reasoning="think"), ContentText(text="\n\nanswer")]
    )
    assert split_reply(message) == ("think", "\n\nanswer")


def test_reasoning_without_text_has_empty_answer() -> None:
    """Thinking finished, answer not started (not seen yet, but possible near max_tokens)."""
    message = ChatMessageAssistant(content=[ContentReasoning(reasoning="think")])
    assert split_reply(message) == ("think", "")


def test_unknown_content_part_raises() -> None:
    """Catches a new part type being silently dropped from thinking and answer."""
    message = ChatMessageAssistant(
        content=[ContentReasoning(reasoning="think"), ContentImage(image="data:image/png;base64,")]
    )
    with pytest.raises(AssertionError, match="ContentImage"):
        split_reply(message)


# --- generation_record on real outputs -----------------------------------------------------


def test_real_finished_output() -> None:
    score = run_scorer(real_output("finished"))
    assert score.value == 1
    assert score.answer is not None and score.answer.startswith("**Simulated Robotic Sorting")
    assert score.metadata is not None
    assert score.metadata["finished"] is True
    assert score.metadata["stop_reason"] == "stop"
    assert score.metadata["thinking"].startswith("Okay, so I need to simulate")
    assert score.metadata["output_tokens"] == 2463


def test_real_cut_off_output() -> None:
    """Catches cut-off thinking being recorded as an answer."""
    score = run_scorer(real_output("cutoff"))
    assert score.value == 0
    assert score.answer == ""
    assert score.metadata is not None
    assert score.metadata["finished"] is False
    assert score.metadata["stop_reason"] == "max_tokens"
    assert score.metadata["thinking"].startswith("Okay, so I need to figure out")
    assert score.metadata["output_tokens"] == 200


# --- generation_record on shapes not seen yet ---------------------------------------------


def test_stop_without_reasoning_parser_is_unfinished() -> None:
    """A server without the parser returns thinking, </think> and answer as one string. It
    must not count as finished; it shows up as stop_reason 'stop' with finished False."""
    score = run_scorer(output("thinking</think>\n\nanswer", "stop"))
    assert score.value == 0
    assert score.metadata is not None
    assert score.metadata["stop_reason"] == "stop"
    assert score.metadata["finished"] is False


def test_stop_with_blank_answer_is_unfinished() -> None:
    score = run_scorer(
        output([ContentReasoning(reasoning="think"), ContentText(text="\n\n")], "stop")
    )
    assert score.value == 0
    assert score.answer == ""


def test_unknown_stop_reason_raises() -> None:
    with pytest.raises(AssertionError, match="unexpected stop reason"):
        run_scorer(output("text", "model_length"))


def test_missing_usage_raises() -> None:
    with pytest.raises(AssertionError, match="no token usage"):
        run_scorer(output([ContentReasoning(reasoning="t"), ContentText(text="a")], "stop", None))
