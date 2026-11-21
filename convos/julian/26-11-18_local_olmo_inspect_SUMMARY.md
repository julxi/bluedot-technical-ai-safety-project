# SUMMARY: Running Olmo 3 7B Think locally with Inspect (learning guide)

**Last updated:** 26-11-21 (vLLM serves Olmo 3 7B Think on a rented A6000 via Julian's `scripts/serve_vllm.sh`; ready 2 min 40 s after start; Inspect through the tunnel not tried yet)

Julian wants to write, himself and with guidance, a script that runs Olmo-3-7B-Think on his laptop through the Inspect evaluation framework, to learn the tools before the real runs on a rented GPU.

## Current state

- **Guide written** in the LOG (entry *step-by-step guide: Olmo 3 7B Think on the laptop, driven by Inspect*). Eight steps:
  1. Install llama.cpp.
  2. Start `llama-server` with a quantized Olmo.
  3. Inspect the chat template and the response format with curl.
  4. Project folder and virtual environment.
  5. Hello-world Inspect task with a judge-free scorer.
  6. Load the Evading Shutdown CSV from the pinned commit with a hash check.
  7. Add the benchmark system prompt and do a first run.
  8. A judge scorer, later.
- **Choices in the guide** [concluded, not ratified]:
  - Server: llama.cpp's `llama-server`, Vulkan build, not Ollama. It uses the model file's original chat template, has an `/apply-template` endpoint that shows the rendered prompt, and needs no sudo.
  - Model files: `mradermacher/Olmo-3-7B-Think{,-DPO,-SFT}-GGUF`, one uploader for all three stages, so the quantization is the same. Q4_K_M is 4.47 GB, Q8_0 7.76 GB.
  - Inspect model string: `openai-api/llamacpp/<name>`, with `LLAMACPP_BASE_URL` and `LLAMACPP_API_KEY`.
  - Code location: [decided: Julian, transcribed in the LOG] the **repo root**. There is one project and no `projects/` folder. `uv`-managed `pyproject.toml` (Python >= 3.14, `inspect-ai`), package `src/instr_eval/`, Inspect tasks in `tasks/`, `.venv/` and `logs/` at the root. We first proposed `projects/instrumental_eval/` following `docs/CODING.md`'s example layout; Julian chose the root. `docs/CODING.md` §Additional instructions now says so.
- **Local results are for learning and pipeline-building only** [concluded]: the model is quantized and runs one response at a time. Project data comes from the unquantized model on a rented GPU, with the same Inspect code.
- **Checked facts:**
  - [verified: checked locally 26-11-18] Laptop: Ryzen AI 9 365, 62 GB RAM, integrated Radeon usable via Vulkan (RADV), Python 3.13, `uv`.
  - [verified: Hugging Face API 26-11-18] The model files above exist.
  - [verified: llama.cpp releases 26-11-18] Release builds are named like `llama-b12503-bin-ubuntu-vulkan-x64.tar.gz`.
  - [verified: PyPI 26-11-18] inspect-ai 0.3.291.
  - [verified: downloaded 26-11-18] The Evading Shutdown CSV at InstrumentalEval commit `269678168cf0388bf5dd7d10dfaed4af07905c49` has SHA-256 `c6c2dd40…69d6`, 21 rows, 1 column; row 1 is the judge context.
- **Checks the guide flagged, now resolved by Julian's runs:** `-hf …:Q4_K_M` found the file; `--reasoning-format deepseek` does not split (see below); speed measured (see below). Whether Inspect auto-loads `.env` remains unconfirmed.

## Local results and the move to a GPU (26-11-18)

- [verified: Julian's runs, llama.cpp b12502 Vulkan, Q4_K_M] Generation runs at 14-16 tokens/s. `--reasoning-format deepseek` does not separate Olmo's thinking (only `</think>` is generated, because the template pre-opens `<think>`), so `tasks/hello.py` splits at `</think>` itself, with fail-loudly checks. A 1,500-token cap cut off the thinking on "17 * 23". `<think>`/`</think>` are ordinary text, not special tokens.
- [concluded, not ratified] Use vLLM on a rented GPU for project data: original weights, any RLVR checkpoint via `--revision`, the engine Ai2 used for RL, much higher batch throughput. Keep llama.cpp for local development. The task code stays the same; only the model string changes.

## Open (waiting on Julian)

- **vLLM serve script, suggested 26-11-21** (LOG entry *what a vllm serve script should contain*; draft, not tested): `scripts/serve_vllm.sh [model] [revision]` only starts the server; tunnel, health check and Inspect stay on the laptop. It resolves the revision to a commit hash and logs it, binds to 127.0.0.1 (tunnel only), names the model `olmo`, sets `--max-model-len` explicitly (32768 is a placeholder), and `exec`s vLLM. No `--reasoning-parser olmo3` for now [concluded]: `tasks/hello.py`'s own `</think>` split would raise on the parser's output, and leaving it off keeps the raw text comparable with llama.cpp. Inspect: `--model openai-api/vllm/olmo` with `VLLM_BASE_URL=http://localhost:8000/v1` [assumed: untried].
- **First start** [verified: Julian's start-up log 26-11-21, one start, RTX A6000 300 W, vLLM 0.34.0]: script start to ready in about 2 min 40 s, of which the 13.59 GiB weights download took 73.6 s (about 198 MB/s) and engine init 35 s. Attention cache 128,957 tokens, 3.94 full 32,768-token requests at once. The server's default sampling comes from `generation_config.json` (temperature 0.6, top-p 0.95, max_tokens 32768), so Inspect must always pass these. The login shell's `python3` lacks `huggingface_hub`; the script needs vLLM's venv (`/venv/main`). Details: LOG entry *first vllm serve start on the A6000*.

- Whether `logs/` (Inspect transcripts) is committed, and a `.gitignore` entry for the cached benchmark CSV (step 6).

- LOG: `convos/julian/26-11-18_local_olmo_inspect_LOG.md`
- See also: `convos/julian/26-11-18_vast_gpu_runner_SUMMARY.md` — the rented-GPU launcher for the vLLM move discussed here (in planning).
- See also: `convos/julian/26-11-16_rlvr_instrumental_convergence_SUMMARY.md` — the research topic this tooling serves. Its LOG holds the hosting and price analysis, the judge-comparison idea, and the own-harness discussion this guide builds on.
- See also: `convos/julian/26-11-21_instrumental_eval_harness_SUMMARY.md` — the full benchmark on the vLLM server; its guide supersedes steps 6-8 of this one.
