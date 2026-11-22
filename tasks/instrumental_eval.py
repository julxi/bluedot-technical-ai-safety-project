from inspect_ai import Task, task
from inspect_ai.model import GenerateConfig
from inspect_ai.solver import generate, system_message

from ic_eval.instrumental.data import load_samples, load_system_prompt
from ic_eval.instrumental.scorer import generation_record


@task
def instrumental_eval(category: str | None = None) -> Task:
    dataset = load_samples(category)

    return Task(
        dataset=dataset,
        solver=[system_message(load_system_prompt()), generate()],
        config=GenerateConfig(temperature=0.6, top_p=0.95, max_tokens=16000),
        scorer=generation_record(),
    )
