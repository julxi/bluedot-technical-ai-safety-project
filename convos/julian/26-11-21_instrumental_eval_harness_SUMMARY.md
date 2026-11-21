# SUMMARY: Our own InstrumentalEval harness on Inspect

**Last updated:** 26-11-21 (step-by-step guide written; Julian implements it himself; design and judge provider not yet confirmed)

Julian, with vLLM now serving Olmo 3 7B Think with `--reasoning-parser olmo3` on a rented GPU, asked for instructions to implement our own version of the InstrumentalEval benchmark. He writes the code; the LOG holds the guide (entry *step-by-step guide: our own InstrumentalEval on Inspect*).

## Design [concluded, not ratified]

- Inspect is the runner (parallel requests, logs, `inspect view`). The benchmark code is ours: task loading with hash checks, verbatim prompts, the thinking/answer handling, and a judge with a strict parser.
- Generate once, judge many: `inspect score <log> --scorer … --model-role judge=… --action append` re-judges a saved run without the GPU [verified: `inspect score --help`, inspect-ai 0.3.291].
- Layout: `src/ic_eval/instrumental/{data,prompts,scorers}.py`, `tasks/instrumental_eval.py`, `tests/instrumental/`, cached CSVs in gitignored `data/input/`.
- Steps: (1) load all six CSVs, (2) prompts verbatim, (3) two GPU checks (rendered prompt; parser output on truncated thinking), (4) task plus a judge-free scorer recording thinking, answer, stop reason, tokens, finished, (5) first run with `--limit 2`, then all 76, (6) the judge.

## Facts [verified: fetched 26-11-21, InstrumentalEval commit `269678168cf0388bf5dd7d10dfaed4af07905c49`]

- Six one-column CSVs under `benchmark/`. Row 1 of each is the judge-only context; 76 tasks in total (20/10/13/11/11/11, as in the paper). SHA-256 for each file is in the LOG. Row 1 of the Hacking file says "Acquiring Restricted Access", so the category name comes from the file name.
- `main.py` (SHA-256 `e470e8a7…4c91f`): the tested model's system prompt is at lines 65-79 and includes the goal-nudging sentence (nudging ON by default). The judge prompts are at lines 106-139; settings are at lines 19-24.
- **Two more silent failures in the original judging:** the judge gets only 50 max tokens, and the parser needs a line starting with exactly `DECISION:`. Markdown, brackets, or a cut-off reply all become `no_convergence`, which pushes the rate down. Our judge uses more tokens and counts unparseable replies as `invalid`.
- Inspect 0.3.291 turns vLLM's `reasoning` field into `ContentReasoning` items, so `state.output.completion` is only the answer [verified: source read; not yet seen in a log]. `tasks/hello.py`'s own `</think>` split raises against a server with the parser on; keep it for llama.cpp.

## Open (Julian)

1. Confirm the design (Inspect plus our own code).
2. Judge provider and model, and its API key in `.env` (none yet; needed from step 6).
3. Whether Inspect's `logs/` is committed.
4. Settings before real runs: `max_tokens` (1000 and/or 32768), temperature (0 or 0.6), samples per task, checkpoints.

- LOG: `convos/julian/26-11-21_instrumental_eval_harness_LOG.md`
- See also: `convos/julian/26-11-16_rlvr_instrumental_convergence_SUMMARY.md` — the research question, the critiques of both papers, and the reasons for our own harness (separate generate/judge steps, prompt variants, several judges, loud parse failures).
- See also: `convos/julian/26-11-18_local_olmo_inspect_SUMMARY.md` — Inspect learning guide (steps 6-8 there are superseded by this guide's steps 1, 2 and 6) and the vLLM serve script with its first measured start.
