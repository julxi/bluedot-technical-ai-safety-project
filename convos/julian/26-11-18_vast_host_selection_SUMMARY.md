# SUMMARY: vast.ai host selection beyond a blacklist (bandit-style)

**Last updated:** 26-11-21 (code committed as e5f4b19; three live tests done. Since then, committed in a second commit: two boot bugs fixed; the abort uses the upper bound of the pull speed with a 2× budget margin; the model learns from replayed polls with censored speeds; quieter output; 12-min pull cap + 6-min build cap. Mode names ratified 26-11-21. Live test 4 found a false abort (fixed). The ssh "bad ownership or modes" fault is fixed by an onstart loop, caught and fixed live on host 314882; 44 tests. The extra layer is the image's provenance attestation, harmless. The two ssh-failure records were deleted (Julian's decision). Open: a full `ic-vast rent` check)

Julian found the permanent host blacklist of `ic-vast` too crude: a host with one bad day was never tried again. He wanted host choice treated as an exploration-exploitation (bandit) problem with hard limits, a Bayesian approach, "a nice clever system", and more precise metrics per rental.

## Decided (Julian's `C:` answers in the LOG)

- **What is optimised:** setup time (renting to usable machine). Differences under max(3 min, 20%) count nothing.
- **The value of waiting**, from his choices in the A2 examples: about $6/h when watching, $0.5/h when away.
- **Failures:** every failure type counts. No host is excluded for good: a bad host is forgiven gradually and sampled again.
- **Early abort:** speed-based, with automatic re-renting (3 attempts, 30-min boot budget).
  - Since the live tests, it uses Julian's upper bound on the speed so far, with a 2× margin against the pull budget left [decided: chat 26-11-18, transcribed in the LOG].
- **Boot caps:** 12 min for the pull (download and unpack), then 6 min for vast.ai's build step, abort margin still 2× [decided: Julian's answers 26-11-21, transcribed in the LOG].
- **`explore` keeps scoring at the watching rate** (Julian asked whether it should use the away rate, then kept the watching rate) [decided: 26-11-21, transcribed in the LOG]. It is meant to be run when away.
- **Hard filters:** loosened (reliability > 0.8, advertised download ≥ 10 Mbit/s, unverified hosts allowed, CN excluded), so our own data decides.
- **Modes:** an exploiting default, explorative and safe modes, offer scores shown, `--offer_id`.
- **Data:** the history is git-tracked in this repo. Probes are on by default.
- **Parameters:** half-lives 14 days (speed) and 30 days (failures); the safe mode keeps memory twice as long and counts failures 3×.

## What exists [verified: `make check` 26-11-21, 44 tests; three live test runs on 26-11-18, see below]

Committed as e5f4b19; everything since the live tests (the fixes and changes listed under Live tests, and the ssh fix) in a second commit on 26-11-21.

- **Package `src/ic_eval/vast/`**, command `uv run ic-vast offers | rent | timer | destroy | stats`. Usage in `cli.py`; each module's role in its docstring.
- **History:** `src/ic_eval/vast/data/rentals.jsonl`, append-only; never edit it.
  - One `attempt` record per rented instance: the full offer, every boot status poll, pull statistics, the outcome, the probes, and the selection with each candidate's predicted setup interval and selection probability.
  - An `end` record from `ic-vast destroy`, with container restarts.
- **Pull measurement** (`pull.py`): layer sizes from Docker Hub; "Pull complete" messages give the bytes unpacked, and vast.ai's build lines (BuildKit or legacy builder) end the pull. While a pull runs, its speed is a range:
  - low = unpacked bytes / time;
  - high = (unpacked + the layer in progress) / time.
- **Model** (`model.py`, a Gibbs sampler; numpy, scipy for truncated normals):
  - per-host log pull speed, hierarchical on log(advertised speed);
  - pooled overhead and image-cache probability;
  - a per-host failure probability around a pooled mean.
  - Speeds are re-derived from each record's polls, so parser fixes reach the whole history. An unfinished pull counts as an interval (censored), not a value.

  Every observation is down-weighted by its age (weight = 0.5^(age / half-life)).
- **Cost and modes** (`policy.py`). The cost of an offer is price × (hours + setup/60), plus λ × (setup beyond the band), plus the expected failure cost. Modes [names decided: Julian, chat 26-11-21, transcribed in the LOG]:
  - `exploit`: lowest mean cost.
  - `balance` (default): tempered Thompson sampling.
  - `explore`: full Thompson sampling.
  - `hedge`: 90th-percentile cost, failure aversion, longer memory.
- **Abort** (`boot.py`, `policy.abort_reason`). After 90 s of pulling, the launcher computes the best-case pull time left at the upper-bound speed. It aborts if:
  - that plus the pooled build overhead exceeds the next-best offer's expected setup time + switch + band, or
  - the pull time left alone exceeds 2× the pull budget left.

  The host's prior is not used, so no host is given up on for what the model expected.
- **Caps** (`configs/policy.yaml`), all failing as `boot_timeout`:
  - `max_pull_minutes: 12`, from renting until the pull ends. It is also the budget the abort compares against.
  - `max_build_minutes: 6`, from the pull's end until `running`. Observed builds took 0.7 min (BuildKit) and 5.4 min (Docker's legacy builder), so a legacy-builder host on a slow day may hit this cap. If logs show "build step not done", raise it first.
  - Both within the 30 min per `rent` across attempts; 4 min with an unchanged status ends a boot in either phase.
  - How the values were chosen: I first proposed 15 + 10; Julian found that too long and suggested 9 + 6. A replay of the recorded boots showed that a 9-min pull cap with the 2× margin aborts the good host 314882 at 3.1 min. The fitted typical host (17.6 MB/s) also needs 10.3 min to pull our image, and the host choice does not know about the caps. Julian then chose 12 + 6 with the 2× margin: the good hosts are kept and the slow host is stopped at 3.8 min. Not chosen: 9 + 6 with a 3× margin and cap-aware host choice (each posterior draw beyond the cap counted as a failure). That would be the way to go if shorter caps are wanted later.
- **Probes** (`probes.py`, ~45 s): Hugging Face download speed (fixed file, 30 s), GPU bf16 TFLOPS and copy bandwidth, nvidia-smi, CPU quota.
- **Testing and checks:** pytest, ruff and basedpyright are dev dependencies with explicit settings in `pyproject.toml`. `make check` (format check, lint, types with 0 errors and 0 warnings, tests) must pass before a code change is finished [decided: Julian, chat 26-11-18, transcribed in the LOG]. Rules are in `docs/CODING.md` §Testing and checks. The checks cover `src/`, `tests/` and `tasks/`.
  - The simulator (`simulate.py`) is a fake market with known truth.
  - `tests/vast/test_recorded_boots.py` replays six real boots through the boot loop. Good hosts must survive; the slow one must be stopped within 6 min (it is, at 3.8 min). A mutation check (margin 1.0 or 100) makes it fail.
  - Scripted boots test the two caps: an 11-min pull followed by a 5-min build must survive, a hanging build and a hanging pull are stopped on time, and the total budget limits both. Counting the build cap from renting makes them fail.

## Findings

- [concluded: simulation, 3 seeded markets] **`explore` must value time at the watching rate.**
  - At the away rate it rarely tried fast-but-pricier hosts, and `hedge` afterwards did as badly as random in one market.
  - At the watching rate, `hedge` afterwards found the best host in all three.
  - Implemented this way. It deviates from the approved design, so it awaits ratification.
- [verified: simulation] **`hedge` never explores.** From an empty history it sticks to its first choice. Run `explore` now and then, so `hedge` has known hosts.
- [verified: Docker Hub] The image repeats one tiny layer; handled.

## Live tests (26-11-18; about $0.30 estimated, no instance left running)

- **Test 1 (`balance`): no machine after 3 attempts.** Host 169171 aborted slow (5.8 min), 701831 aborted slow (2.2 min), 314882 running after 12.4 min, then a host-side ssh fault ("bad ownership or modes" on authorized_keys).
- **Test 2 (`explore`): ready in 4.6 min** on new host 134600 (RTX 6000 Ada, $0.649/h), predicted 11.9 [2.3, 24.1].
- **Test 3 (`hedge`): ready in 0.7 min,** same host 134600 on another machine, image cached; predicted 4.7 [0.8, 9.6].
- Verified end to end: scoring and choice per mode, re-choose when an offer is gone, speed abort, auto re-rent, ssh host-fault detection, watchdog and timer, sync, probes, `destroy` with its record, cache-hit prediction. Not exercised: watchdog restart after a reboot, `--script`, `--offer_id`, the stall and boot-timeout caps.
- **Fixed since (second commit, 26-11-21):**
  - **Crash:** the boot loop crashed when the first pull message came in the first poll (0 s elapsed).
  - **Legacy builder:** on hosts using Docker's legacy builder, the build step counted as pull time.
  - **Staircase progress** [concluded: progress traces in the LOG]. Only fully unpacked layers count, and the image has 4.15 and 3.33 GB layers after its first 0.37 GB. So the old live speed decayed between steps, and the abort stopped host 701831 about 100 s into its pull on no evidence. Fixed by:
    - the upper-bound abort with the 2× margin;
    - censored speeds;
    - replayed history.

    Effect [verified: `ic-vast stats`, no record edited]: host 314882 went from 15.2 to 28 MB/s, and 701831 from 3.9 MB/s to the interval 4-19 MB/s. The typical speed at 1000 Mbit/s rose from 12.7 to 18.1 MB/s, and the day-to-day spread fell from 0.77 to 0.40 (log).
  - **Output:** quieter (ssh `LogLevel=ERROR`, rsync totals instead of progress when not on a terminal).
- **Unpacking, not download, dominated:** host 314882 had both big layers downloaded within 78 s, but unpacked only by 205 s and 329 s. Its build step (legacy builder) took 5.4 min, against 0.7 min on a BuildKit host.
- **Smaller, not fixed:**
  - The `obs` column counts speed plus failure observations, so one rental shows as about 2.
  - A crash inside the boot loop loses that attempt's polls.

## Open (Julian)

1. **Live test 4 (26-11-21) found a false abort**, fixed but not yet live-checked: small layers can finish unseen between polls, so the upper bound now runs through the next layer of at least 100 MB (`pull.VISIBLE_LAYER_BYTES`). Details in the LOG entry *live test 4: ...*.
2. **ssh "bad ownership or modes": fixed** ( it hit 2 of the first 4 rentals that reached `running`).
   - **Cause** [verified: trial rental on host 314882, 26-11-21, one rental]: vast.ai's daemon on the host writes `/root/.ssh/authorized_keys` as its own uid (115:999 there), and sshd refuses a key file not owned by root.
   - **Fix** (`src/ic_eval/vast/sshmodes.py`): every rental gets an `--onstart-cmd` loop that, for 15 min from container start, re-owns to root and removes group/other write from `/`, `/root`, `/root/.ssh` and `authorized_keys`. It logs each fix to `vastai logs`. With it, 314882 took the key at the first try. Each attempt records the loop's report in the new field `Attempt.ssh_modes` (schema 2).
   - A `vastai reboot` showed that lines appended to `/root/onstart.sh` (the watchdog's) survive a restart and run.
   - **The two past ssh-failure records were deleted** from `rentals.jsonl` [decided: Julian, 26-11-21, transcribed in the LOG], a one-off exception to the append-only rule. Their pull speeds (28 and 61 MB/s) went with them, so hosts 314882 and 679583 are unknown to the model again. Speeds quoted for them elsewhere in this SUMMARY describe the history before the deletion.
3. Still unverified: the watchdog restart after a container restart the host triggers (launcher topic), a full `ic-vast rent` with the new code (the trial used its own loop and a small image, not recorded in `rentals.jsonl`).
4. Committed 26-11-21 at Julian's request (the commit after e5f4b19), before the full `ic-vast rent` check in item 3.
5. **The extra layer `16b73de6e8ad`** (seen on host 679583): the 9 KB SLSA provenance attestation that Docker Hub lists next to the amd64 image, downloaded during the pull, probably by hosts using Docker's containerd image store [assumed]. The pull tracker ignores it; nothing to fix.

- LOG: `convos/julian/26-11-18_vast_host_selection_LOG.md` (entries *framing host selection as a bandit, and questions*, *design: discounted hierarchical Bayesian host model, …*, *implementation, simulation findings, backfilled history*, *live test 1: two boot bugs fixed, staircase pull progress found*, *live tests 2 and 3, and the model after all three*, *upper-bound abort, censored speeds, replayed history, quiet output; facts on the 15-min cap*, *separate pull and build caps*, *9 + 6 caps: what they break, and explore's rate*, *12 + 6 caps implemented, explore help text*, *live test 4: ...*, *the extra layer 16b73de6e8ad is the image's provenance attestation*, *ssh mode fix: onstart loop, caught on host 314882*, *the two ssh-failure records deleted*)
- See also: `convos/julian/26-11-18_vast_gpu_runner_SUMMARY.md` — the launcher this topic rebuilt: renting, sync, timer, and the first test rentals.
