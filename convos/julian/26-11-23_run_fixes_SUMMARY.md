# SUMMARY: Fixes for problems found in the first invariance run

**Last updated:** 26-11-23 (problems explained, fixes proposed; nothing changed yet)

Julian asked to fix the problems met while running the judge-reliability invariance run (`convos/julian/26-11-23_judge_reliability_LOG.md`, entry *first invariance run: three qic prompts, Phi-4*). LOG entry *the problems found during the first invariance run*:

1. **`ic-serve up` doesn't end while vLLM runs** [verified: local reproduction]: the remote launch command `mkdir … && setsid nohup … > log &` backgrounds the whole `&&` list, whose subshell keeps the ssh channel open; the local `ssh -f` then holds the caller's output pipe, so piped or agent-run calls hang (cost ~10 min idle GPU). Fix: `mkdir … || exit 1; setsid nohup … &`, plus a test; optionally stdout to DEVNULL in `ssh_detached`.
2. **Repeated judgings don't line up in the report**: repeats are named by judge run id, which differs per checkpoint, so trend columns split and the flip table drops them. Fix: number repeats `#1`, `#2` by time within each generation run.
3. **Variant comparison only in a scratch script**: optional report addition (flips with direction between judgings of the same judge model).
4. **Stale harness SUMMARY bullet** (old data file name, deleted CSVs).

Open: Julian's go-ahead and which of 3 he wants.

- See also: `convos/julian/26-11-23_judge_reliability_SUMMARY.md` — the run where these problems showed up.
- See also: `convos/julian/26-11-18_vast_gpu_runner_SUMMARY.md` — the launcher whose remote command is at fault in problem 1.
