"""Hello-world Inspect task: two toy prompts, scored by whether Olmo finished thinking (no judge).

Run (llama-server must already be running; see convos/julian/26-11-18_local_olmo_inspect_LOG.md):
    inspect eval tasks/hello.py --model openai-api/llamacpp/olmo-3-7b-think \
        --max-tokens 2000 --temperature 0.6 --top-p 0.95 --max-connections 1
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Target, mean, scorer
from inspect_ai.solver import TaskState, generate, system_message

THINK_CLOSE = "</think>"


def split_thinking(text: str, stop_reason: str) -> tuple[str, str | None]:
    """Split raw Olmo output into (thinking, answer); answer is None if generation was cut off.

    Olmo 3's chat template ends the prompt with an opened `<think>`, so the generated text
    contains only the closing tag: "<thinking> </think> <answer>". Inspect's own reasoning
    parser needs both tags and therefore leaves this text unparsed in `completion`; we split
    it here instead. Every shape we don't expect raises, rather than being scored silently.
    """
    if "<think>" in text:
        raise ValueError(f"unexpected opening <think> in output: {text[:200]!r}")
    n_close = text.count(THINK_CLOSE)
    if n_close > 1:
        raise ValueError(f"{n_close} closing tags in output, expected at most 1: {text[:200]!r}")
    if n_close == 0:
        # Truncation inside the thinking is a legitimate outcome (no answer yet), not an error.
        if stop_reason == "max_tokens":
            return text.strip(), None
        raise ValueError(f"no {THINK_CLOSE} although stop_reason={stop_reason!r}: {text[-200:]!r}")
    thinking, answer = text.split(THINK_CLOSE)
    return thinking.strip(), answer.strip()


@scorer(metrics=[mean()])
def finished_thinking():
    """1.0 if the model closed its thinking and gave a non-empty answer, else 0.0."""

    async def score(state: TaskState, target: Target) -> Score:
        output = state.output
        # llama-server's finish_reason "length" arrives here as "max_tokens".
        if output.stop_reason not in ("stop", "max_tokens"):
            raise ValueError(f"unexpected stop_reason {output.stop_reason!r}")
        assert output.usage is not None, "server returned no token usage"

        thinking, answer = split_thinking(output.completion, output.stop_reason)
        finished = answer is not None and answer != ""

        return Score(
            value=1.0 if finished else 0.0,
            answer=answer,
            explanation="finished thinking and answered" if finished else "cut off or empty answer",
            metadata={
                "stop_reason": output.stop_reason,
                "input_tokens": output.usage.input_tokens,
                "output_tokens": output.usage.output_tokens,
                "thinking_chars": len(thinking),
                "answer_chars": len(answer) if answer is not None else None,
            },
        )

    return score


@task
def hello():
    return Task(
        dataset=[
            Sample(id="primes", input="Name three prime numbers."),
            Sample(id="mult", input="What is 17 * 23?", target="391"),
            Sample(id="test", input="Can you write <think>?"),
        ],
        solver=[system_message("You are a helpful assistant."), generate()],
        scorer=finished_thinking(),
    )
