# BlueDot Technical AI Safety Project

Julian Bitterlich's project for the BlueDot Impact Technical AI Safety course. The specific research topic has not been chosen yet (as of 26-11-15); choosing it is the first real piece of work. A new reader should start with the Conversation Index below.

This project uses the [Epistemic Memory](https://github.com/FlorianDietz/EpistemicMemory) conventions: all project memory lives in LOG/SUMMARY file pairs under `convos/`, governed by [CLAUDE.md](CLAUDE.md). Human guide: [docs/HOW_TO_USE.md](docs/HOW_TO_USE.md). Open ideas and deferred items: [FUTURE_WORK.md](FUTURE_WORK.md). Workflow problems and lessons: [FEEDBACK.md](FEEDBACK.md). Reference papers as Markdown: [papers/](papers/README.md).

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
| 26-11-16 | julian | RLVR side-effects and instrumental convergence (candidate topic) | Feasibility check done; core experiment already published (arXiv 2610.31624), replication-with-better-protocol recommended; waiting on Julian's budget and choice of angle | [SUMMARY](convos/julian/26-11-16_rlvr_instrumental_convergence_SUMMARY.md) | [LOG](convos/julian/26-11-16_rlvr_instrumental_convergence_LOG.md) |
