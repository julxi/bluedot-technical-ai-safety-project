"""Judge requests: turn a generation log into one judge sample per generated reply.

Used by tasks/judge.py. This module only builds what is sent to the judge; it does not parse
or interpret judge replies (design: tasks record, analysis interprets).

Judge prompts live in data/input/judge_prompts.json, edited by hand (the two source prompts were
built once by a since-deleted script: `git show 954d465:src/ic_eval/instrumental/build_data.py`),
keyed by a name that says where the prompt comes from (e.g. `etpm_judge_prompt`). Variants of a
source prompt for reliability tests carry `derived_from` and `variant`. Each holds a system and
a user template with fixed placeholders, plus the output format the prompt asks for (`output`),
which the analysis needs to read the replies.
"""

import json
import logging
import string
from typing import Any

from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import ChatMessageSystem, ChatMessageUser

from ic_eval.instrumental.scorer import split_reply
from ic_eval.paths import DATA_JUDGE_PROMPTS

logger = logging.getLogger(__name__)

# {specific_prompt}: the category description (row 1 of the benchmark CSV), {prompt}: the task
# as sent to the tested model, {response}: the tested model's answer (without its thinking).
SYSTEM_FIELDS = {"specific_prompt"}
USER_FIELDS = {"prompt", "response"}


def template_fields(template: str) -> set[str]:
    """Names of the {placeholders} in a str.format template."""
    return {field for _, field, _, _ in string.Formatter().parse(template) if field is not None}


def check_judge_prompt(name: str, prompt: dict[str, Any]) -> None:
    """Crash on a judge prompt whose templates or output format don't fit together.

    str.format ignores unused keyword arguments, so a template missing a placeholder would
    silently send the judge a prompt without the answer; hence the exact-set checks.
    """
    system, user = prompt["system_template"], prompt["user_template"]
    assert template_fields(system) == SYSTEM_FIELDS, f"{name}: system {template_fields(system)}"
    assert template_fields(user) == USER_FIELDS, f"{name}: user {template_fields(user)}"
    output = prompt["output"]
    assert output["kind"] in ("categorical", "score"), f"{name}: output kind {output['kind']!r}"
    # The prompt must actually ask for the label the analysis will look for.
    assert f"{output['label']}:" in system, (
        f"{name}: system prompt never asks for {output['label']}"
    )
    if output["kind"] == "categorical":
        for value in output["values"]:
            assert value in system, f"{name}: value {value!r} not in the system prompt"


def load_judge_prompt(name: str) -> dict[str, Any]:
    with open(DATA_JUDGE_PROMPTS, encoding="utf-8") as f:
        prompts = json.load(f)
    if name not in prompts:
        raise ValueError(f"unknown judge prompt {name!r}; valid: {sorted(prompts)}")
    check_judge_prompt(name, prompts[name])
    return prompts[name]


def judge_samples(gen_log: EvalLog, prompt: dict[str, Any]) -> tuple[list[Sample], list[str]]:
    """One judge sample per finished reply of a generation log; also the ids skipped.

    A reply that was cut off (stop reason other than `stop`) or has an empty answer has nothing
    to judge. It is skipped, not crashed on, so one long reply doesn't block judging a run; the
    skipped ids are returned so the task can record them in its header and the analysis can
    count them.

    Sample id `<generation id>-e<epoch>` (unique also with several epochs); metadata `gen_id`,
    `gen_epoch`, `category`. Values that are the same for the whole log (which generation log,
    which prompt) are recorded once by the task, not per sample.
    """
    assert gen_log.status == "success", f"{gen_log.location}: status {gen_log.status}"
    assert gen_log.eval.task == "generate", f"{gen_log.location}: task {gen_log.eval.task!r}"
    assert gen_log.samples, f"{gen_log.location} has no samples"

    samples: list[Sample] = []
    skipped: list[str] = []
    for s in gen_log.samples:
        sample_id = f"{s.id}-e{s.epoch}"
        _thinking, answer = split_reply(s.output.message)
        answer = answer.strip()
        if s.output.stop_reason != "stop" or not answer:
            skipped.append(sample_id)
            continue
        assert isinstance(s.input, str), f"{s.id}: expected a plain-string task prompt"
        system = prompt["system_template"].format(specific_prompt=s.metadata["judge_context"])
        user = prompt["user_template"].format(prompt=s.input, response=answer)
        samples.append(
            Sample(
                id=sample_id,
                input=[ChatMessageSystem(content=system), ChatMessageUser(content=user)],
                metadata={"gen_id": s.id, "gen_epoch": s.epoch, "category": s.metadata["category"]},
            )
        )

    if skipped:
        logger.warning(f"{len(skipped)} unfinished replies not judged: {skipped}")
    assert samples, f"{gen_log.location}: no finished replies to judge"
    return samples, skipped
