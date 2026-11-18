# SUMMARY: vast.ai GPU launcher (port of the SPD repo's `spd-vast`)

**Last updated:** 26-11-18 (Julian answered the questions; implementation plan written; waiting on his go-ahead; nothing implemented)

Julian asked to set up vast.ai GPU rentals here the way his other project, `/home/jx/projects/targeted-parameter-decomposition` ("the SPD repo"), does them, to check that repo's `docs/CODING.md`, and to ask many questions before implementing.

## Reference

[verified: code read 26-11-18] `spd/scripts/run_vast.py` there (1,082 lines) rents one GPU, attaches an ssh key, writes an ssh alias, syncs code via a GitHub clone plus rsync of the working tree, runs `uv sync` under a time budget, and starts a job. Host failures blacklist the host and destroy the instance. Most of its guards come from real failed rentals (`targeted-parameter-decomposition/convos/julian/26-10-05_vast_rentals_SUMMARY.md`).

## Decided (Julian's `C:` answers in the LOG)

- The agent writes it, porting nearly all of the SPD launcher (copy and adapt, improvements welcome).
- **New feature: a self-destruct timer** on the instance, easy to update and switch off.
- Two modes: rent only, and rent + run a script.
- Inspect runs on the laptop via an ssh tunnel for now.
- vLLM comes preinstalled in vast.ai's image, so it stays out of `pyproject.toml`. The pinned image tag records the version in git.
- ssh alias `bluedot-vast`; own empty blacklist; default key `~/.ssh/id_rsa`.
- No Hugging Face token. The SPD launcher doesn't forward one either: it forwards only WandB credentials.
- Secrets reach the instance only over ssh. `docs/CODING.md` will say so, and any other route needs Julian's authorisation.
- No code to copy logs back before destroying.
- The summary after renting shows the hourly cost.
- `docs/CODING.md` takes only the SPD repo's vast.ai job rules, plus the secrets rule.
- Live test: one rental and a timer check only.
- Configs are the agent's choice.

## Plan [concluded, not ratified; LOG entry *implementation plan after Julian's answers*]

- **Command and files:** `instr-vast` from `src/instr_eval/vast.py`, with configs `7b` (48 GB-class cards, under $1.20/h) and `32b` (H200) in `src/instr_eval/vast_configs/`.
- **`pyproject.toml`:** gains a `[build-system]` so the package installs, plus the dependency `fire`. pydantic, pyyaml and python-dotenv are already installed via inspect-ai.
- **Dropped for now:** `uv sync` on the instance, WandB, and the `sync`/`detached` modes.
- **Timer** [verified: vast.ai docs 26-11-18]: each instance has a key (`CONTAINER_API_KEY`) that can only start, stop or destroy that one instance. A watchdog on the instance reads a deadline file every 30 s and destroys its own instance with that key. Commands: `instr-vast timer 2h|off`, and `--timer` at rent time; defaults 3 h (`7b`) and 2 h (`32b`).
- **Checked 26-11-18** [verified]:
  - `origin` is public and HEAD is pushed.
  - vLLM 0.34.0 supports Python 3.14.
  - The image `vastai/vllm:v0.34.0-cuda-13.0` exists. CUDA 13 hosts: 145 of 148 offers with at least 44 GB.
  - No instance is running on the account.
- **Unknown until the test rental:** whether the bare vLLM image starts `vllm serve` at boot (vast.ai's template does, with a default DeepSeek model), and whether the watchdog uses the `vastai` CLI or curl.
- **Flag:** `uv.lock` is untracked. That matters once Inspect runs on the instance.

## Open (waiting on Julian)

Confirm the `--script` reading of "renting and running some script"; OK for about 2 min of read-only inspection during the test rental (est. $0.10-0.30); go-ahead for the plan.

- LOG: `convos/julian/26-11-18_vast_gpu_runner_LOG.md` (entries *reference launcher survey and questions before implementing*, *implementation plan after Julian's answers*)
- See also: `convos/julian/26-11-18_local_olmo_inspect_SUMMARY.md` — the vLLM-vs-llama.cpp answer that motivated the move to a rented GPU; `tasks/hello.py` from there is the planned first real job.
- See also: `convos/julian/26-11-16_rlvr_instrumental_convergence_SUMMARY.md` — hosting and price analysis, GPU sizing for the 7B and 32B models.
