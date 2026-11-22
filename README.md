# BlueDot Technical AI Safety Project

Julian Bitterlich's project for the BlueDot Impact Technical AI Safety course. The specific research topic has not been chosen yet (as of 26-11-15); choosing it is the first real piece of work. A new reader should start with the Conversation Index below.

This project uses the [Epistemic Memory](https://github.com/FlorianDietz/EpistemicMemory) conventions: all project memory lives in LOG/SUMMARY file pairs under `convos/`, governed by [CLAUDE.md](CLAUDE.md). Human guide: [docs/HOW_TO_USE.md](docs/HOW_TO_USE.md). Open ideas and deferred items: [FUTURE_WORK.md](FUTURE_WORK.md). Workflow problems and lessons: [FEEDBACK.md](FEEDBACK.md). Reference papers as Markdown, each with a short living overview to read first: [papers/](papers/README.md).

## Team

A team of one, so agents don't need a user-identification step.

- Julian Bitterlich: `convos/julian/`

Private records (`convos/julian/private/`) are not set up yet. Julian chose to skip them during setup; they can be added later (see CLAUDE.md §Privacy).

## Current status and goals

- Choose the project topic. One candidate is under evaluation: RLVR side-effects and instrumental convergence on the Olmo 3 checkpoints (see the Conversation Index).

## Maintenance

Recurring tasks:

| Task | Last run | Due when | Notes |
|------|----------|----------|-------|
| Sync (LOG/SUMMARY drift) | — | After many LOG changes, or ~monthly | `!sync`; procedure: `docs/procedures/sync.md` |
| LLM-ism checklist refresh (delete this row if the project publishes nothing) | — | ~Monthly while you publish regularly; otherwise before any high-stakes submission | Update the checklist and Known-screening sections of `docs/procedures/outward_text.md` from full primary sources (see the file's refresh rule); bump its refresh date |

## Conversation Index

All discussions live in `convos/{user}/`. **When starting a new topic, add a row here.** Read the SUMMARY first; open the LOG only if the SUMMARY is insufficient. Status cells describe current state only — rewrite them on update, don't append.

| Date | User | Topic | Status | SUMMARY | LOG |
|------|------|-------|--------|---------|-----|
| 26-11-15 | julian | Project setup | Done; template configured | [SUMMARY](convos/julian/26-11-15_project_setup_SUMMARY.md) | [LOG](convos/julian/26-11-15_project_setup_LOG.md) |
| 26-11-16 | julian | Public research log | Google Doc created and shared by link; adding entries needs the Google Docs connector | [SUMMARY](convos/julian/26-11-16_public_research_log_SUMMARY.md) | [LOG](convos/julian/26-11-16_public_research_log_LOG.md) |
| 26-11-16 | julian | RLVR side-effects and instrumental convergence (candidate topic) | Feasibility check done; core experiment already published (arXiv 2610.31624), replication-with-better-protocol recommended; run instructions, hosting/price options (incl. Vast.ai) and Olmo 3 training details written; own eval harness and judge comparison proposed; no run yet; waiting on Julian's go-ahead, judge provider and API key | [SUMMARY](convos/julian/26-11-16_rlvr_instrumental_convergence_SUMMARY.md) | [LOG](convos/julian/26-11-16_rlvr_instrumental_convergence_LOG.md) |
| 26-11-18 | julian | Paper overviews (living indexes with line pointers into `papers/`) | Convention set up, both overviews written, checker passes; waiting on Julian's ratification | [SUMMARY](convos/julian/26-11-18_paper_overviews_SUMMARY.md) | [LOG](convos/julian/26-11-18_paper_overviews_LOG.md) |
| 26-11-18 | julian | Running Olmo 3 7B Think locally with Inspect (learning guide) | Steps 1-5 done locally (14-16 tok/s; own `</think>` split); vLLM serving on a rented A6000 via `scripts/vm/serve_vllm.sh` (ready in 2 min 40 s); Inspect via tunnel next; code at repo root (decided) | [SUMMARY](convos/julian/26-11-18_local_olmo_inspect_SUMMARY.md) | [LOG](convos/julian/26-11-18_local_olmo_inspect_LOG.md) |
| 26-11-18 | julian | vast.ai GPU launcher (port of the SPD repo's `spd-vast`) | `scripts/laptop/gpu_up.sh` added 26-11-22 (rent + vLLM + tunnel in one command; untested); `ic-vast sync` added 26-11-21 (verified live); launcher rebuilt by the host-selection topic; self-destruct timer verified on a rental; watchdog restart fix untested | [SUMMARY](convos/julian/26-11-18_vast_gpu_runner_SUMMARY.md) | [LOG](convos/julian/26-11-18_vast_gpu_runner_LOG.md) |
| 26-11-18 | julian | vast.ai host selection beyond a blacklist (bandit-style) | Committed 26-11-21 (fixes after 4 live tests): upper-bound abort (2× margin), censored speeds, 12 + 6 min caps (decided), false-abort fix; ssh 'bad ownership' fault fixed by an onstart loop (caught live on host 314882); extra layer explained (provenance attestation, harmless); the two ssh-failure records deleted (decided); open: a full `ic-vast rent` check | [SUMMARY](convos/julian/26-11-18_vast_host_selection_SUMMARY.md) | [LOG](convos/julian/26-11-18_vast_host_selection_LOG.md) |
| 26-11-21 | julian | Our own InstrumentalEval harness on Inspect | Guide written (6 steps); step 1 data done (tracked `data/input/instrumental_eval.json`, 76 tasks + system prompt); step 3 done (parser splits finished replies; cut-off thinking lands in `content`, so the scorer must use `finish_reason`; rendered prompt checked); step 4 done (task with category filter, judge-free scorer, tests); step 5 (all 76 on the GPU) next; design, judge provider and run settings open | [SUMMARY](convos/julian/26-11-21_instrumental_eval_harness_SUMMARY.md) | [LOG](convos/julian/26-11-21_instrumental_eval_harness_LOG.md) |
