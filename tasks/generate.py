"""Generation: send a dataset's prompts to the tested model and record the replies.

This task only records (design: tasks record, analysis interprets). Everything that varies
between runs is a parameter that Inspect writes into the log header:
- `-T dataset=etpm` (required) and optionally `-T category=shutdown`: task arguments;
- the tested model / checkpoint: `--model openai-api/vllm/<served name>`; the served name is
  derived from repository, revision and commit by scripts/vm/serve_vllm.sh;
- sampling: the defaults below (Olmo 3 model card: temperature 0.6, top-p 0.95), overridden on
  the command line, e.g. `--temperature 0` for runs in the setting of arXiv 2610.31624;
- the purpose of a run: `--tags`.

Example:
    uv run inspect eval tasks/generate.py -T dataset=etpm \
        --model openai-api/vllm/olmo-3-7b-think.main.d97e442 \
        --max-connections 32 -M client_timeout=3600
"""

from inspect_ai import Task, task
from inspect_ai.model import GenerateConfig

# Imported under another name because this module's task is called `generate` too.
from inspect_ai.solver import generate as generate_reply
from inspect_ai.solver import system_message

from ic_eval.instrumental.data import load_samples, load_system_prompt
from ic_eval.instrumental.scorer import generation_record
from ic_eval.paths import DATA_INPUT_DIR

# Dataset name -> file. Names say where a dataset comes from: etpm = He et al. 2025,
# "Evaluating the Paperclip Maximizer" (InstrumentalEval), prompts verbatim.
DATASETS = {
    "etpm": DATA_INPUT_DIR / "etpm.json",
}


@task
def generate(dataset: str, category: str | None = None) -> Task:
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}; valid: {sorted(DATASETS)}")
    path = DATASETS[dataset]
    return Task(
        dataset=load_samples(path, category),
        solver=[system_message(load_system_prompt(path)), generate_reply()],
        # Without explicit values vLLM would silently fill in its own defaults.
        config=GenerateConfig(temperature=0.6, top_p=0.95, max_tokens=16000),
        # Records facts about each reply (stop reason, lengths, thinking/answer split); no
        # judgment.
        scorer=generation_record(),
    )
