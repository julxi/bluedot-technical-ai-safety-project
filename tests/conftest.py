"""Shared fixtures for tests/instrumental and tests/analysis: real Inspect runs of our tasks
against Inspect's fake model (mockllm), with scripted replies. No GPU, no network; the logs go
to a temporary folder."""

import importlib.util
from types import ModuleType

import pytest
from inspect_ai import eval as inspect_eval
from inspect_ai.log import EvalLog
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
    ContentReasoning,
    ContentText,
    GenerateConfig,
    ModelOutput,
    get_model,
)
from inspect_ai.tool import ToolChoice, ToolInfo

from ic_eval.paths import REPO_ROOT

# The third shutdown task (by title) gets a cut-off reply, so judging must skip it.
CUT_OFF_TITLE = "Conflicting Human Override"
# Braces in an answer must reach the judge unchanged (str.format must not touch values).
ANSWER_SUFFIX = " {not a placeholder}"


def load_task_module(task_file: str) -> ModuleType:
    """A task file in tasks/ (not a package, so loaded by file path)."""
    spec = importlib.util.spec_from_file_location(task_file, REPO_ROOT / "tasks" / task_file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def user_text(messages: list[ChatMessage]) -> str:
    users = [m for m in messages if isinstance(m, ChatMessageUser)]
    assert len(users) == 1
    return users[0].text


def fake_olmo(
    messages: list[ChatMessage], tools: list[ToolInfo], choice: ToolChoice, config: GenerateConfig
) -> ModelOutput:
    """Olmo-shaped replies: thinking and answer as separate content items, as vLLM's olmo3
    reasoning parser returns them; the cut-off reply is a plain string (thinking only)."""
    title = user_text(messages).split("\n", 1)[0]
    if title == CUT_OFF_TITLE:
        message = ChatMessageAssistant(content=f"THINKING about {title}, cut off")
        stop_reason = "max_tokens"
    else:
        message = ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning=f"THINKING about {title}"),
                ContentText(text=f"\n\nANSWER for {title}{ANSWER_SUFFIX}"),
            ]
        )
        stop_reason = "stop"
    return ModelOutput(
        model="mockllm/model",
        choices=[ChatCompletionChoice(message=message, stop_reason=stop_reason)],
    )


def fake_judge(
    messages: list[ChatMessage], tools: list[ToolInfo], choice: ToolChoice, config: GenerateConfig
) -> ModelOutput:
    return ModelOutput.from_content(
        model="mockllm/model", content="DECISION: convergence\nREASON: scripted."
    )


def fake_qic_judge(
    messages: list[ChatMessage], tools: list[ToolInfo], choice: ToolChoice, config: GenerateConfig
) -> ModelOutput:
    """Disagrees with fake_judge on shutdown-01 (score 0.2) and agrees on the rest (0.9)."""
    low = "Uncertain Shutdown Source" in user_text(messages)
    return ModelOutput.from_content(
        model="mockllm/model", content=f"SCORE: {0.2 if low else 0.9}\nREASON: scripted."
    )


@pytest.fixture(scope="session")
def gen_log(tmp_path_factory: pytest.TempPathFactory) -> EvalLog:
    """A finished `generate` run: shutdown-01 and -02 answered, shutdown-03 cut off."""
    task = load_task_module("generate.py").generate(dataset="etpm", category="shutdown")
    (log,) = inspect_eval(
        task,
        model=get_model("mockllm/model", custom_outputs=fake_olmo),
        limit=3,
        log_dir=str(tmp_path_factory.mktemp("logs")),
        display="none",
    )
    assert log.status == "success"
    return log


@pytest.fixture(scope="session")
def judge_log(gen_log: EvalLog, tmp_path_factory: pytest.TempPathFactory) -> EvalLog:
    """A finished `judge` run over gen_log with the etpm judge prompt."""
    task = load_task_module("judge.py").judge(gen_log=gen_log.location, prompt="etpm_judge_prompt")
    (log,) = inspect_eval(
        task,
        model=get_model("mockllm/model", custom_outputs=fake_judge),
        log_dir=str(tmp_path_factory.mktemp("logs")),
        display="none",
    )
    assert log.status == "success"
    return log


@pytest.fixture(scope="session")
def judge_log_qic(gen_log: EvalLog, tmp_path_factory: pytest.TempPathFactory) -> EvalLog:
    """A finished `judge` run over gen_log with the qic judge prompt (see fake_qic_judge)."""
    task = load_task_module("judge.py").judge(gen_log=gen_log.location, prompt="qic_judge_prompt")
    (log,) = inspect_eval(
        task,
        model=get_model("mockllm/model", custom_outputs=fake_qic_judge),
        log_dir=str(tmp_path_factory.mktemp("logs")),
        display="none",
    )
    assert log.status == "success"
    return log
