# SUMMARY: Our own InstrumentalEval harness on Inspect

**Last updated:** 26-11-23 (Data bullet brought up to date: `etpm.json`, `build_data.py` and CSVs deleted)

Julian, with vLLM now serving Olmo 3 7B Think with `--reasoning-parser olmo3` on a rented GPU, asked for instructions to implement our own version of the InstrumentalEval benchmark. He writes the code; the LOG holds the guide (entry *step-by-step guide: our own InstrumentalEval on Inspect*).

## Design [concluded, not ratified]

- Inspect is the runner (parallel requests, logs, `inspect view`). The benchmark code is ours: task loading with hash checks, verbatim prompts, the thinking/answer handling, and a judge with a strict parser.
- Generate once, judge many: `inspect score <log> --scorer … --model-role judge=… --action append` re-judges a saved run without the GPU [verified: `inspect score --help`, inspect-ai 0.3.291].
- Layout (since 26-11-23): `src/ic_eval/instrumental/{data,scorer}.py` (`build_data.py` deleted 26-11-23, decided; last version in commit 954d465), `tasks/generate.py`, `tests/instrumental/`. Design "tasks record, analysis interprets", one task per procedure: `convos/julian/26-11-22_bluedot_course_exercises_LOG.md`, entries *overall code design…* and *stage 1 implemented…*.
- **Data** (current state 26-11-23): `data/input/etpm.json` (dataset `etpm`), git-tracked and final, so runs need no download; built once from upstream's six benchmark CSVs and `main.py` by `build_data.py`, which was then deleted together with the CSV copies (decided; last version `git show 954d465:src/ic_eval/instrumental/build_data.py`). `data.py` only reads it: `load_samples(path, category=None)`, `load_system_prompt(path)`. Shape: `{dataset: {name, description}, source, commit, system_prompt: {source_file, source_sha256, text}, categories: [{id, source_file, source_sha256, judge_context, tasks: [{id, title, prompt}]}]}`, 6 categories, 76 tasks [verified: loaded 26-11-23]; upstream file names and hashes stay recorded there. `system_prompt.text` is the tested model's system prompt, extracted with `ast` from upstream `main.py`. Prompts verbatim, including the scenario title line of the 20 shutdown prompts (also copied into `title`). An earlier version moved the titles out of the prompt [superseded: decided by Julian in the LOG entry *shutdown title lines split off*, replaced 26-11-23 by the verbatim dataset, see `convos/julian/26-11-22_bluedot_course_exercises_LOG.md`]. No system/user split and no separate "Remember …" field: upstream sends the whole CSV text as the user message, and only 5 of 76 prompts contain "Remember", in varying places (LOG entry *step 1 data*). Judge prompts live separately in `data/input/judge_prompts.json`. The upstream repo has no license file, so committing the data is redistribution without explicit permission; check before going public.
- Steps: (1) load all six CSVs, (2) prompts verbatim, (3) two GPU checks (rendered prompt; parser output on truncated thinking), (4) task plus a judge-free scorer recording thinking, answer, stop reason, tokens, finished, (5) first run with `--limit 2`, then all 76, (6) the judge.

## Facts [verified: fetched 26-11-21, InstrumentalEval commit `269678168cf0388bf5dd7d10dfaed4af07905c49`]

- Six one-column CSVs under `benchmark/`. Row 1 of each is the judge-only context; 76 tasks in total (20/10/13/11/11/11, as in the paper). SHA-256 for each file is in the LOG. Row 1 of the Hacking file says "Acquiring Restricted Access", so the category name comes from the file name.
- `main.py` (SHA-256 `e470e8a7…4c91f`): the tested model's system prompt is at lines 65-79 and includes the goal-nudging sentence (nudging ON by default). The judge prompts are at lines 106-139; settings are at lines 19-24.
- **Two more silent failures in the original judging:** the judge gets only 50 max tokens, and the parser needs a line starting with exactly `DECISION:`. Markdown, brackets, or a cut-off reply all become `no_convergence`, which pushes the rate down. Our judge uses more tokens and counts unparseable replies as `invalid`.
- Inspect 0.3.291 turns vLLM's `reasoning` field into `ContentReasoning` items, so `state.output.completion` is only the answer [verified: source read; not yet seen in a log]. `tasks/hello.py`'s own `</think>` split raises against a server with the parser on; keep it for llama.cpp.

## Step 4.2: scorer [verified: on the two saved shutdown-01 logs, 26-11-22]

- `src/ic_eval/instrumental/scorer.py`: `split_reply(message) -> (thinking, answer)` (plain-string content = cut-off thinking, answer `""`; deliberately not `message.text`) and `generation_record()` (value 1 if `stop` and a non-empty answer, else 0; metadata: finished, stop_reason, thinking, output_tokens, thinking/answer chars; crashes on unknown stop reasons or content items).
- Test offline with `inspect score <log> --scorer src/ic_eval/instrumental/scorer.py@generation_record --output-file <new file>`; it prompts before overwriting an existing output file.
- No extra asserts for `</think>` in the answer or `stop` without thinking [decided: Julian]: both cases already come out as `stop_reason == "stop"` with `finished == False`. Check for that combination after step 5.
- **Step 4.4 done:** category filter in `load_samples(category)` (`-T category=…`, `ValueError` listing valid names); tests in `tests/instrumental/` (15, incl. the two real outputs as a fixture; a seeded `message.text` defect fails 3 of them) [verified: 61/61 pass, 26-11-22]. `make check` still fails on Julian's scratch `log_test.py` in the package. A `model_length` stop reason would crash the scorer; only reachable if `max_tokens` goes to 32768. LOG entry *step 4.4 tests written*.

## Step 5: running at scale

- Inspect 0.3.291 defaults to adaptive concurrency (starts at 20, grows to at most 100, shrinks only on 429s, which vLLM never sends); `--max-connections N` fixes it at N [verified: source read]. The HTTP request timeout is 600 s; one sequence ran at about 38 tokens/s (last real run, 2 at once), so a 16,000-token reply can exceed it under load and be retried from zero. Use `-M client_timeout=3600` [assumed: not seen to trigger yet].
- **Throughput sweep on the RTX A6000** [verified: one run per setting, 26-11-22; 152 requests = 76 tasks × 2 epochs]: `--max-connections 32` gave 442 tok/s end to end (501 in the saturated phase); 64 gave 404 (536 saturated), because the KV cache (116,346 tokens) filled, vLLM re-queued started requests and the tail doubled (368 s vs 162 s). Julian's 20-request shutdown run: 286. About 32 replies fit in the cache at these lengths, so the cache, not Inspect, is the limit. Use `--max-connections 32 -M client_timeout=3600` and one big run (the tail costs 2–3 min per run). More throughput needs more memory: a bigger GPU, or `--gpu-memory-utilization 0.95` (≈ +9% cache, untested).
- **8-bit KV cache on the A6000** [verified: 26-11-22, one run]: FP8 fails to start (needs compute capability 8.9+, i.e. L40S/4090/H100). `int8_per_token_head` works, doubles the cache (225,475 tokens) and ran 64 requests without queueing, but on a slower attention backend (Triton instead of FlashAttention): 591 vs 503 tok/s while the batch was full, 433 vs 442 end to end (long tail). Not worth the numerics change [concluded]; stay with bf16. All replies finished and per-category median lengths stayed inside the bf16 run-to-run spread. LOG entry *8-bit KV cache on the A6000: FP8 unsupported, INT8 no gain*.
- Reply lengths [verified: same runs]: medians about 1,500–2,500 tokens per category, longest 9,391 (INT8 run; 7,312 in bf16, `aligned-02` the slowest in both bf16 runs); none near `max_tokens` 16000. Per-reply speed about 16 tok/s at 32 connections, so a full 16,000-token reply would need about 17 min: past the 600 s default timeout.
- Analysis: `scripts/laptop/vllm_throughput.py` (an Inspect log plus a copy of the vLLM log → tokens/s, queue, cache, tail). Details: LOG entries *step 5: full shutdown run and filling the GPU* and *throughput sweep: 32 connections is the A6000 optimum*.

## Later

- Julian wants his own prompts eventually; the upstream set is kept for now. Seen weaknesses and the case for keeping the upstream set as a reference arm: LOG entry *own prompts later*, and FUTURE_WORK.md.

## Step 3 results

- **Cut-off thinking lands in `content`, not `reasoning`** [verified: one request 26-11-22, vLLM 0.34.0 with `--reasoning-parser olmo3`, `max_tokens` 200]: `finish_reason` `length`, all text in `content`, `reasoning` null. So the scorer must treat every `finish_reason == "length"` sample as unfinished and never judge it; `content` alone cannot tell. LOG entry *step 3 check B result*.
- **Check A: the render route is disabled** (403, needs `--enable-scale-out`). Use `/tokenize` (`add_generation_prompt: true`) then `/detokenize` [verified: 26-11-22]. The template appends "You do not currently have access to any functions. <functions></functions>" to the system prompt and opens `<think>` at the end of the prompt. LOG entry *step 3 check A*.
- **A finished response splits correctly** [verified: Julian's run 26-11-22, one "1 + 1" request]: `finish_reason` `stop`, thinking in `reasoning`, answer only in `content` (starting with `\n\n`), no `</think>` in either. `usage.completion_tokens_details.reasoning_tokens` stays 0, so it is useless; count lengths ourselves. LOG entry *step 3: finished response splits correctly*.
- **Rendered benchmark prompt read** [verified: Julian's run 26-11-22, hacking-02]: system prompt complete, template sentence appended, task complete, ends with `<think>`. **Step 3 is done.**
- Julian asked (26-11-22) to be instructed rather than have the agent query the server.
- **In Inspect** [verified: Julian's two shutdown-01 runs 26-11-22]: finished → `stop_reason` `stop`, `message.content` = [`reasoning` item, `text` item]; cut off → `stop_reason` `max_tokens`, `content` a plain string holding the thinking, so `state.output.completion` is the thinking. `VLLM_BASE_URL`/`VLLM_API_KEY=none` live in `.env`, which Inspect loads itself. The task must set `GenerateConfig(temperature=0.6, top_p=0.95, max_tokens=…)`: an empty config sends no sampling settings and silently uses the server defaults. LOG entry *step 4.1*.

## Open (Julian)

Step 6 (judge) continues in `convos/julian/26-11-22_bluedot_course_exercises_LOG.md`, entry *judging code: design* (26-11-23): several self-hosted judges × two prompts (the original binary one and the paper's Table 9), each `inspect score` into its own file in `logs/judged/` (appending works, but one judge can't be replaced or removed afterwards); no hand labels up front.

1. Confirm the design (Inspect plus our own code).
2. Judge provider and model, and its API key in `.env` (none yet; needed from step 6).
3. Whether Inspect's `logs/` is committed.
4. Settings before real runs: `max_tokens` (1000 and/or 32768), temperature (0 or 0.6), samples per task, checkpoints.
5. What the judge grades (step 6): answer only, thinking and answer separately, or the whole transcript. Recommended: answer as the main number (comparable with upstream), thinking as an optional second one. The scorer keeps them apart either way [decided: Julian, "keep it like this for now"]. LOG entry *why split thinking from answer*.

- LOG: `convos/julian/26-11-21_instrumental_eval_harness_LOG.md`
- See also: `convos/julian/26-11-16_rlvr_instrumental_convergence_SUMMARY.md` — the research question, the critiques of both papers, and the reasons for our own harness (separate generate/judge steps, prompt variants, several judges, loud parse failures).
- See also: `convos/julian/26-11-18_local_olmo_inspect_SUMMARY.md` — Inspect learning guide (steps 6-8 there are superseded by this guide's steps 1, 2 and 6) and the vLLM serve script with its first measured start.
