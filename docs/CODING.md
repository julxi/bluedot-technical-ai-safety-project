# Coding Guidelines — Reference

Read this in full before writing code or running an experiment in this project. The critical rules that are easy to violate (Fail Loudly; Observe & Verify; never hardcode keys; no git writes unless asked) live in CLAUDE.md; this file holds the how-to.

## Project Structure

Each coding project lives in its own folder under `projects/`. An example layout for Python projects — adapt or replace it for your stack:

```
projects/<project_name>/
├── pyproject.toml          # All dependencies (don't pin versions unless necessary)
├── .env                    # API keys — the user provides this; NEVER hardcode keys
├── .gitignore              # Exclude .venv/, .env, __pycache__/, large data folders
├── src/
│   ├── __init__.py
│   └── utils.py            # See below
├── scripts/                # Runnable entry points
├── data/
│   ├── input/              # External data sources
│   ├── results/            # Raw outputs (often largest; use subfolders)
│   └── analysis/           # KPIs, summaries, graphs
├── logs/                   # Runtime logs
└── tests/                  # Optional; discuss with the user what's worth testing
```

**Setup**: install with `pip install -e .` in a project-local `.venv` so all imports work regardless of working directory.

**`src/utils.py` should contain**:
- Environment variable loading (from `.env`)
- Path definitions using `pathlib.Path` relative to `__file__` — critical for scripts to work from any directory
- Shared utility functions and classes

**If `.env` is missing or keys don't work**: ask the user to provide it. Do not proceed with hardcoded keys. List the keys your project expects in the project's own documentation.

## User Interaction for Coding Projects

The workflow:
1. The user describes the project in a LOG file; most interaction happens there
2. Design decisions: the agent writes options and questions into the LOG, the user responds with `C:` comments
3. Once decisions are made: implement, optionally run, document what you did in the LOG

(The git rule — no git write operations unless explicitly asked — is in CLAUDE.md.)

**Coding project SUMMARYs** should additionally include (beyond the general SUMMARY guidelines in CLAUDE.md):
- What the project does and what its data formats look like (with JSON examples)
- What is implemented vs. planned
- Any refactorings or convention changes that explain why older code may look different

If a project grows large, split the SUMMARY into focused sub-documents.

## Code Comments

Code should be self-documenting about *what* it does; comments document what is NOT in the code — for a future agent with zero history:

- **Why, not what.** Reasons, constraints, invariants ("must run before X because Y"). Never narrate the code ("loop over users") and never narrate the *change* ("now handles the edge case") — that addresses today's reviewer, not the next reader.
- **Guard deliberate deviations.** Anything intentionally non-canonical — a missing retry, an odd ordering, a "redundant" check — WILL look like a bug to a future agent and get "fixed". Mark it: "intentionally X, not Y, because Z."
- **Record what was skipped or tried.** "Deliberately no caching — tried, reverted (see the topic LOG)" closes dead ends a fresh agent would re-enter.
- **Document contracts at boundaries.** Docstrings with units, shapes, invariants, side effects; one top-of-file line on what the module does and who reads/writes its data. Agents edit from partial reads — the contract line is what makes that safe.
- **Comments are part of the edit.** When you change code, updating the adjacent comments is part of the change — a stale comment misleads the next agent worse than no comment.
- **Placement follows P(seen when needed):** what must be known at the point of edit goes in the code; narrative, alternatives, and results go to LOG/SUMMARY. Comments must stand alone (Self-Contained Artifacts rule in CLAUDE.md): state what was chosen and why in place; add a LOG reference only for decisions important enough to warrant the full discussion.
- TODOs in code only when tied to that exact spot and short-lived; anything else goes to FUTURE_WORK.md — in-code TODOs rot invisibly.

## Logging & Observability

This is the how-to for the Observe & Verify rule in CLAUDE.md — the rule for operations that fail *silently* by producing plausible-but-wrong output of the right shape instead of crashing. "Ran without errors" proves nothing for these; you only catch them by logging the actual input/output and reading it on real data.

Where this matters most: regexes, fuzzy matching, truncation, normalization, encoding round-trips, parsing model output, and **prompt composition** — a subtly malformed prompt (a dropped section, a misplaced join) silently degrades every result in a batch. For prompts, log the exact final string with visible delimiters around each composed section, then read it.

Structure hints:
- Log *both sides* of a decision boundary — the cases that matched **and** the cases that didn't. False positives hide in "matched," false negatives in "didn't."
- For high volume, aggregate with counts, and keep a few raw examples per bucket so correctness can still be checked by eye.
- Log the score next to each fuzzy match and sort by it — errors cluster near the threshold.
- Log a stable id linking each output back to its input, so a suspicious aggregate is traceable to a concrete case.

## Additional instructions

> Put additional instructions here, based on the needs of the project and the policies of the user or their company: preferred languages and frameworks, API-call patterns, data-handling and provider policies, testing standards, CI conventions. The template deliberately leaves this open — these choices are yours.

- **One project, at the repo root** (decided by Julian 26-11-18; see `convos/julian/26-11-18_local_olmo_inspect_LOG.md`, entry *code layout: one project at the repo root*). This repository holds a single coding project, so the `projects/<name>/` layout under §Project Structure does not apply. Code lives at the root: `pyproject.toml` (managed with `uv`), `src/ic_eval/` for the package (Julian renamed it from `instr_eval` on 26-11-18), `tasks/` for Inspect tasks, with `.venv/`, `.env` and `logs/` at the root. Don't create a `projects/` folder.

## Rented vast.ai GPUs

Rent with `uv run ic-vast rent` (package `src/ic_eval/vast/`; all commands in `cli.py`'s module docstring), and end the session with `ic-vast destroy`, which records it before destroying. `rent` chooses the host with a Bayesian model of past rentals and re-rents automatically when a host is slow or fails. It writes the ssh alias `bluedot-vast` and arms a self-destruct timer on the instance (`ic-vast timer`).

- Design and history: `convos/julian/26-11-18_vast_gpu_runner_SUMMARY.md` (renting, sync, timer) and `convos/julian/26-11-18_vast_host_selection_SUMMARY.md` (host choice).

- **Secrets take a secure route, always** (decided by Julian 26-11-18, same LOG, answer E1). Secrets go to a rented machine only over ssh, on the command's stdin (e.g. into a mode-600 file under `/etc/profile.d/`). Never send them through vast.ai's instance settings (`vastai create --env`, which vast.ai stores on its servers), command-line arguments (visible in process lists), git, logs, or the synced working tree. Any other route only with Julian's explicit authorisation.
- The rules below were carried over from Julian's targeted-parameter-decomposition repo, where each cost time once:
  - **Check the GPU's power limit after renting.** `ic-vast rent` prints it. In the other repo, an H100 capped at 500 W ran 40% slower than one at ~600 W.
  - **Launch remote commands as a login shell**: `ssh bluedot-vast 'bash -lc "<cmd>"'`. A plain `ssh bluedot-vast '<cmd>'` skips `/etc/profile.d/`, so secrets installed there are missing.
  - **Detach long jobs** with `ssh -n -f bluedot-vast 'setsid nohup <cmd> > <log> 2>&1 < /dev/null &'`. Without `-f`, the local ssh call can hang until the remote job ends. Don't chain other commands after a launch call.
  - **Kill by a bracket pattern or PID**: `pkill -f "[v]llm serve"`. A plain `pkill -f "vllm serve"` inside `ssh bluedot-vast '...'` matches its own command line and kills the ssh session. Kill-then-relaunch in one call still matches the relaunch text, so run the kill in a call of its own.
  - **Wall times are only comparable on the same machine.** Compare speed with measurements from one instance.
  - **Compare the container's CPU quota with `nproc`** (`cat /sys/fs/cgroup/cpu.max`; `ic-vast rent` prints both). A container allowed 23 CPUs on a 192-core host throttled jobs that started one thread per core; cap `OMP_NUM_THREADS` to the quota.

## Testing and checks

Set up 26-11-18 at Julian's request.

- **`make check` must pass before a code change is finished** (Julian, 26-11-18: linting is "part of dependencies and checked"). It runs, and changes nothing: `ruff format --check`, `ruff check`, `basedpyright` (0 errors and 0 warnings), and `pytest`. `make format` fixes what ruff can fix. ruff and basedpyright are dev dependencies; their settings live in `pyproject.toml` (`[tool.ruff]`, `[tool.basedpyright]`). Keep those settings explicit, so that a tool update cannot silently change what counts as clean.
- Scope: `src/`, `tests/` and `tasks/` (Inspect tasks).
- Run `uv run pytest` from the repo root. pytest is a dev dependency, configured in `pyproject.toml` (`[tool.pytest.ini_options]`).
- Tests live in `tests/`, mirroring the package (`tests/vast/` for `src/ic_eval/vast/`). Shared fixtures go in each folder's `conftest.py`.
- **Tests never rent, never call vast.ai, never spend money.** Code that talks to vast.ai or ssh (`market.py`, `remote.py`, `probes.py`) is checked on real rentals instead, and the result is recorded in the topic LOG. Pure logic (models, policies, parsers) gets unit tests. Behaviour over many decisions gets a simulation test, e.g. `src/ic_eval/vast/simulate.py`, a fake market with known truth.
- Seed every random generator, so a test is deterministic. Choose thresholds that a correct implementation passes by a wide margin and a broken one clearly fails. Say in the test's docstring which bug it would catch.
- Parsers get tests on real inputs copied from logs (e.g. vast.ai status messages), not invented ones.
