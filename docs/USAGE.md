# Current experiment design readable for human (Julian)

Design: tasks record, analysis interprets. There is one task per procedure (`tasks/generate.py`, later `tasks/judge.py`); everything that differs between runs (dataset, checkpoint, settings, purpose) is a parameter, and Inspect writes it into the log header.

## Start the vm

One command rents a GPU, serves a model there, opens the tunnel and writes `serve_session.env`. Models are configs in `src/ic_eval/serve/configs/` (`olmo-3-7b-think` with checkpoints `sft`, `dpo`, `step_0200`, `final`; `phi-4` as judge):

```
uv run ic-serve up olmo-3-7b-think --checkpoint final
uv run ic-serve up olmo-3-7b-think --checkpoint sft --machine 48gb --timer 2h
```

`.env` needs `HF_TOKEN=...` (a read-only Hugging Face token): `ic-serve` checks it before renting and puts it on the instance (over ssh, never on the command line), which makes weight downloads much faster.

Another model or checkpoint on the same instance (stops vLLM, starts the new one, rewrites `serve_session.env`):

```
uv run ic-serve switch olmo-3-7b-think --checkpoint dpo
uv run ic-serve switch phi-4
```

If `up` stopped while vLLM was still loading: `uv run ic-serve attach <model> [--checkpoint …]`. The self-destruct timer isn't extended by `switch`: `uv run ic-vast timer 2h`.

Then, in every terminal that runs Inspect (again after every `switch`):

```
source serve_session.env
```

It sets the model (served name derived from repository, revision and commit, e.g. `olmo-3-7b-think.main.d97e442`), `max-connections` (derived from the KV cache vLLM reports on this GPU) and the client timeout, so the commands below need no `--model`, `--max-connections` or `-M`. To check by hand: `curl localhost:8000/v1/models`.

Fallback until `ic-serve` has run once for real: `bash scripts/laptop/gpu_up.sh --script_args "<model> <revision> [parser] [context length]"`, then pass `--model`, `--max-connections` and `-M client_timeout=3600` yourself.

## Run inspect and inspect inspect
(all with active venv)

running (generation; `-T dataset=` is required, `etpm` = the InstrumentalEval prompts verbatim)
```
inspect eval tasks/generate.py -T dataset=etpm
```

- one category only: `-T category=shutdown`
- reference setting (qic paper, at full length): add `--temperature 0`
- several replies per task: `--epochs 5`
- mark what a run is for: `--tags reference`

inspecting (best in extra terminal)
```
inspect view
```

## Judge a generation run

Serve the judge model instead of Olmo (first judge: Phi-4), then `source serve_session.env` again:

```
uv run ic-vast destroy
uv run ic-serve up phi-4
```

Then one run per judge prompt (`-T prompt=etpm_judge_prompt` = the original InstrumentalEval judge, `qic_judge_prompt` = the qic paper's judge, partly reconstructed):

```
inspect eval tasks/judge.py -T gen_log=logs/<generate log>.eval -T prompt=etpm_judge_prompt
```

- the judge task only records the judge's replies (no scores); reading them into verdicts and rates is the analysis' job
- replies that were cut off during generation are skipped; the judge log lists them (task metadata `gen_skipped`)
- the judge log's header names the generation run it judged (`gen_run_id`, `gen_model`)

## Analyse

```
uv run python -m ic_eval.analysis.report
```

For every generation run in `logs/` that has judgings: rate per judging (judge model | judge prompt), invalid verdicts, rate per category, pairwise agreement with Cohen's kappa. Writes `data/analysis/<generation run id>_to_read.md` with every reply the judgings disagree on, plus 15 random ones they agree on. Interpretation choices are options: `--threshold 0.5` (a score at or above counts), `--positive convergence`, `--gen_log logs/<one run>.eval`.

## End the session

```
uv run ic-vast destroy
```
