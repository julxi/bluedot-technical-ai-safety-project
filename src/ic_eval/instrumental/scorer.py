"""Judge-free scorer: records what each generation looks like, before any judging.

Value 1 if the model finished thinking and gave an answer, else 0, so the task's mean is the
share of finished replies (needed to choose max_tokens). The thinking, answer, stop reason and
lengths go into the score's metadata, for the judge (step 6) and for analysis.
"""

from inspect_ai.model import ChatMessageAssistant, ContentReasoning, ContentText
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer
from inspect_ai.solver import TaskState

# Stop reasons seen so far with vLLM 0.34.0 + --reasoning-parser olmo3 (step 3, 26-11-22).
# Anything else crashes, so a new shape gets looked at instead of silently scored.
KNOWN_STOP_REASONS = ("stop", "max_tokens")


def split_reply(message: ChatMessageAssistant) -> tuple[str, str]:
    """Return (thinking, answer) of a model reply.

    A plain-string content means the model was cut off while thinking.
    A list content holds ContentReasoning items (thinking) and ContentText items (answer).
    """
    content = message.content
    if isinstance(content, str):
        return content, ""
    known = ContentReasoning | ContentText
    others = [type(c).__name__ for c in content if not isinstance(c, known)]
    assert not others, f"unexpected content items: {others}"
    thinking = "".join(c.reasoning for c in content if isinstance(c, ContentReasoning))
    answer = "".join(c.text for c in content if isinstance(c, ContentText))
    return thinking, answer


@scorer(metrics=[mean()])
def generation_record() -> Scorer:
    # `target` stays unused: our samples have no reference answer, but Inspect passes one.
    async def score(state: TaskState, target: Target) -> Score:
        output = state.output
        stop_reason = output.stop_reason
        assert stop_reason in KNOWN_STOP_REASONS, f"unexpected stop reason {stop_reason!r}"
        assert output.usage is not None, "no token usage in the model output"

        thinking, answer = split_reply(output.message)
        answer = answer.strip()

        finished = stop_reason == "stop" and answer != ""

        return Score(
            value=1 if finished else 0,
            answer=answer,
            explanation=f"stop_reason={stop_reason}",
            metadata={
                "finished": finished,
                "stop_reason": stop_reason,
                "thinking": thinking,
                "output_tokens": output.usage.output_tokens,
                "thinking_chars": len(thinking),
                "answer_chars": len(answer),
            },
        )

    return score
