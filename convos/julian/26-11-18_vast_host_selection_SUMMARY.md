# SUMMARY: vast.ai host selection beyond a blacklist (bandit-style)

**Last updated:** 26-11-18 (implemented with tests and simulation; `make check` set up; history backfilled with 2 real rentals; mode names and one design deviation await ratification; not yet tested on a live rental; nothing committed)

Julian found the permanent host blacklist of `ic-vast` too crude: a host with one bad day was never tried again. He wanted host choice treated as an exploration-exploitation (bandit) problem with hard limits, a Bayesian approach, "a nice clever system", and more precise metrics per rental.

## Decided (Julian's `C:` answers in the LOG)

- **What is optimised:** setup time (renting to usable machine). Differences under max(3 min, 20%) count nothing.
- **The value of waiting**, from his choices in the A2 examples: about $6/h when watching, $0.5/h when away.
- **Failures:** every failure type counts. No host is excluded for good: a bad host is forgiven gradually and sampled again.
- **Early abort:** speed-based, with automatic re-renting (3 attempts, 30-min boot budget).
- **Hard filters:** loosened (reliability > 0.8, advertised download ≥ 10 Mbit/s, unverified hosts allowed, CN excluded), so our own data decides.
- **Modes:** an exploiting default, explorative and safe modes, offer scores shown, `--offer_id`.
- **Data:** the history is git-tracked in this repo. Probes are on by default.
- **Parameters:** half-lives 14 days (speed) and 30 days (failures); the safe mode keeps memory twice as long and counts failures 3×.

## What exists (uncommitted) [verified: 21 tests pass; offers, stats and dry run against the live market, 26-11-18]

- **Package `src/ic_eval/vast/`**, command `uv run ic-vast offers | rent | timer | destroy | stats`. Usage in `cli.py`; each module's role in its docstring.
- **History:** `src/ic_eval/vast/data/rentals.jsonl`, append-only; never edit it.
  - One `attempt` record per rented instance: the full offer, every boot status poll, pull statistics, the outcome, the probes, and the selection with each candidate's predicted setup interval and selection probability.
  - An `end` record from `ic-vast destroy`, with container restarts.
- **Model** (`model.py`, a numpy Gibbs sampler):
  - per-host log pull speed, hierarchical on log(advertised speed);
  - pooled overhead and image-cache probability;
  - a per-host failure probability around a pooled mean.

  Every observation is down-weighted by its age (weight = 0.5^(age / half-life)).
- **Cost and modes** (`policy.py`). The cost of an offer is price × (hours + setup/60), plus λ × (setup beyond the band), plus the expected failure cost. Modes [names concluded, not ratified]:
  - `exploit`: lowest mean cost.
  - `balance` (default): tempered Thompson sampling.
  - `explore`: full Thompson sampling.
  - `hedge`: 90th-percentile cost, failure aversion, longer memory.
- **Abort** (`boot.py`): the image's layer sizes come from Docker Hub, and "Pull complete" messages give the bytes unpacked. After 90 s of pulling, the launcher compares the predicted remaining time with the next-best offer's expected setup time plus the band. Caps: 15 min per boot, 4 min with an unchanged status.
- **Probes** (`probes.py`, ~45 s): Hugging Face download speed (fixed file, 30 s), GPU bf16 TFLOPS and copy bandwidth, nvidia-smi, CPU quota.
- **Testing and checks:** pytest, ruff and basedpyright are dev dependencies with explicit settings in `pyproject.toml`. `make check` (format check, lint, types with 0 errors and 0 warnings, tests) must pass before a code change is finished [decided: Julian, chat 26-11-18, transcribed in the LOG]. Rules are in `docs/CODING.md` §Testing and checks. The simulator (`simulate.py`) is a fake market with known truth. The checks cover `src/`, `tests/` and `tasks/`.

## Findings

- [concluded: simulation, 3 seeded markets] **`explore` must value time at the watching rate.**
  - At the away rate it rarely tried fast-but-pricier hosts, and `hedge` afterwards did as badly as random in one market.
  - At the watching rate, `hedge` afterwards found the best host in all three.
  - Implemented this way. It deviates from the approved design, so it awaits ratification.
- [verified: simulation] **`hedge` never explores.** From an empty history it sticks to its first choice. Run `explore` now and then, so `hedge` has known hosts.
- [verified: status logs] **Two real rentals backfilled** (mode `manual`, no predictions): host 169171 pulled at 8.8 MB/s (aborted), host 682584 at 35.1 MB/s (ready in 6.6 min). The model now puts typical speeds at ~18 MB/s for 1000 Mbit/s advertised, and `hedge` picks host 682584.
- [verified: Docker Hub] The image repeats one tiny layer; handled.

## Open (Julian)

1. Ratify the mode names and the `explore` deviation.
2. Approve a live test: one `ic-vast rent` plus `ic-vast destroy`, about $0.10-0.20. Optionally with a forced reboot, to test the watchdog restart fix from the launcher topic.
3. Commit the code with `rentals.jsonl`.

- LOG: `convos/julian/26-11-18_vast_host_selection_LOG.md` (entries *framing host selection as a bandit, and questions*, *design: discounted hierarchical Bayesian host model, …*, *implementation, simulation findings, backfilled history*)
- See also: `convos/julian/26-11-18_vast_gpu_runner_SUMMARY.md` — the launcher this topic rebuilt: renting, sync, timer, and the first test rentals.
