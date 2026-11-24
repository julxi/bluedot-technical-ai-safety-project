# SUMMARY: Fixes for problems found in the first invariance run

**Last updated:** 26-11-23 (all four fixes done, `make check` passes; fix 1 not yet tried on a real rental)

Julian asked to fix the problems met while running the judge-reliability invariance run (`convos/julian/26-11-23_judge_reliability_LOG.md`, entry *first invariance run: three qic prompts, Phi-4*). Problems: LOG entry *the problems found during the first invariance run*; fixes: entry *all four fixes done*.

1. **`ic-serve up` didn't end while vLLM ran** [verified: local reproduction]: the remote launch `mkdir … && setsid nohup … > log &` backgrounded the whole `&&` list, whose subshell kept the ssh session open; the local `ssh -f` then held the caller's output pipe (cost ~10 min idle GPU). Same form also hid a failing mkdir (exit 0). Fixed in `build_script_command` (`mkdir … || exit 1; setsid nohup … &`), `ssh_detached` stdout to DEVNULL as a partial guard, rule added to `docs/CODING.md`. Tests run the real command locally and fail on the old form [verified]. Still to see on the next real `ic-serve up`.
2. **Repeated judgings didn't line up in the report**: named by judge run id, which differs per checkpoint. Now `#1`, `#2` by start time within each generation run (`judging_names` in `report.py`; `judge_created` added in `logs.py`). Test fails on the old naming [verified].
3. **Variant comparison was a scratch script**: `pairwise_agreement` now gives `only_a` / `only_b` (direction of disagreements). The report reproduces all scratch-script numbers [verified: 26-11-23].
4. **Stale harness SUMMARY**: Data bullet rewritten to current state.

`make check` passes (126 tests) [verified: 26-11-23].

- See also: `convos/julian/26-11-23_judge_reliability_SUMMARY.md` — the run where these problems showed up.
- See also: `convos/julian/26-11-18_vast_gpu_runner_SUMMARY.md` — the launcher whose remote command is at fault in problem 1.
