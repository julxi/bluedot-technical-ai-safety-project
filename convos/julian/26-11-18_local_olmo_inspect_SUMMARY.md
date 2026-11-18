# SUMMARY: Running Olmo 3 7B Think locally with Inspect (learning guide)

**Last updated:** 26-11-18 (guide written; Julian has not started; nothing installed or run)

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
  - Code location: `projects/instrumental_eval/`, per `docs/CODING.md`.
- **Local results are for learning and pipeline-building only** [concluded]: the model is quantized and runs one response at a time. Project data comes from the unquantized model on a rented GPU, with the same Inspect code.
- **Checked facts:**
  - [verified: checked locally 26-11-18] Laptop: Ryzen AI 9 365, 62 GB RAM, integrated Radeon usable via Vulkan (RADV), Python 3.13, `uv`.
  - [verified: Hugging Face API 26-11-18] The model files above exist.
  - [verified: llama.cpp releases 26-11-18] Release builds are named like `llama-b12503-bin-ubuntu-vulkan-x64.tar.gz`.
  - [verified: PyPI 26-11-18] inspect-ai 0.3.291.
  - [verified: downloaded 26-11-18] The Evading Shutdown CSV at InstrumentalEval commit `269678168cf0388bf5dd7d10dfaed4af07905c49` has SHA-256 `c6c2dd40…69d6`, 21 rows, 1 column; row 1 is the judge context.
- **Unverified points the guide flags as checks** [assumed]:
  - whether `-hf …:Q4_K_M` finds the uploader's file;
  - whether `--reasoning-format deepseek` separates the thinking, given that Olmo's template pre-opens `<think>`;
  - whether Inspect auto-loads `.env`;
  - generation speed (guess: 10-20 tokens/s).

## Open (waiting on Julian)

- The project folder name.
- Results of steps 1-3: which field the reasoning lands in, and the measured speed.

- LOG: `convos/julian/26-11-18_local_olmo_inspect_LOG.md`
- See also: `convos/julian/26-11-16_rlvr_instrumental_convergence_SUMMARY.md` — the research topic this tooling serves. Its LOG holds the hosting and price analysis, the judge-comparison idea, and the own-harness discussion this guide builds on.
