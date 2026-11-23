C: (transcribed from chat) (new convo) So, let's fix the problems that you have encountered. Can you explain them to me again?

---

26-11-23, Claude Opus 5.5 — *the problems found during the first invariance run*; context: I ran the invariance run in `convos/julian/26-11-23_judge_reliability_LOG.md` (entry *first invariance run: three qic prompts, Phi-4*) in this session. Re-read `ssh_detached`, `build_script_command`, `_watchdog_start_command` in `src/ic_eval/vast/remote.py` and `add_verdicts`, `trend` in `src/ic_eval/analysis/report.py`.

## Problem 1: `ic-serve up` doesn't end while vLLM runs

**Symptom.** Started as a background command, `uv run ic-serve up phi-4 | tee …` printed "wrote serve_session.env" at 20:06 but the command only ended when the instance was destroyed (20:19). The agent waited for that end, so the GPU sat idle ~10 min. In a terminal it goes unnoticed, since the prompt comes back when the Python process exits; only a caller that waits for the *output* to close (a pipe, `tee`, an agent's background runner, `subprocess.run(capture_output=True)`) hangs.

**Root cause** [verified: local reproduction 26-11-23, below]. `launch_script` sends this remote command through `ssh -n -f`:

    mkdir -p <log dir> && setsid nohup bash -lc '<serve_vllm.sh …>' > <log> 2>&1 < /dev/null &

In shell grammar `&&` binds tighter than `&`, so the whole `mkdir && setsid …` list goes to the background as one subshell, and the redirection applies only to its last command. The subshell itself keeps the ssh session's stdout until vLLM exits, so the remote session never closes, so the local `ssh -f` stays alive, and it holds ic-serve's stdout/stderr pipe (seen as fds 5/6 of the leftover ssh process). The watchdog command (`setsid nohup python … > … 2>&1 < /dev/null & echo $! > pid`) has no `&&` list in front and is not affected, matching the observation that only the vLLM launcher ssh lingered.

Local reproduction, a pipe standing in for the ssh channel (`bash -c '<cmd>' | cat`, time until the pipe closes, with `sleep 3` for vLLM):

| command form | pipe closes after |
|---|---|
| `mkdir -p d && setsid nohup sleep 3 > /dev/null 2>&1 < /dev/null &` (current) | 3.0 s |
| `{ mkdir -p d && setsid nohup sleep 3; } > /dev/null 2>&1 < /dev/null &` | 0.003 s |
| `mkdir -p d \|\| exit 1; setsid nohup sleep 3 > /dev/null 2>&1 < /dev/null &` | 0.014 s |

**Proposed fix.** (a) Remote: `mkdir -p <dir> || exit 1; setsid nohup … > <log> 2>&1 < /dev/null &` — returns at once, and a failing mkdir still prints its error and makes ssh exit non-zero, so `check=True` raises (verified for the exit code). (b) A test that runs `build_script_command(...)` through local `bash -c … | cat` with a short sleep instead of the script and asserts the pipe closes within a second. Optional (c), defence in depth: `ssh_detached` passes stdout to DEVNULL, so even a future remote command with the same mistake can't hold the caller's output (stderr kept, for connection errors).

## Problem 2: repeated judgings don't line up across checkpoints in the report

**Symptom.** The run judged each of the three generation runs a second time with `qic_judge_prompt`. The report's trend table then has six `qic_judge_prompt #<id>` columns, each filled for one checkpoint only (NaN elsewhere), and the flip table (SFT → final) has no `qic_judge_prompt` row at all.

**Cause.** `add_verdicts` names a judging `<judge> | <prompt>`, and when the same name occurs twice on one generation run it appends the judge run id (`#2HtbtQ`). Judge run ids differ on every generation run, so the names differ across checkpoints, and `trend` pivots and pairs judgings by name.

**Proposed fix.** Number repeats by time within each generation run (`#1` = the earliest judging with that judge and prompt, `#2` = the next), so `#1` and `#2` line up across checkpoints. Caveat: the numbering assumes repeats were made in the same order on every checkpoint ("first trend session, then today"); true here, and the reading file names the judge log anyway. Test: two fake generation runs, each judged twice with the same prompt → two columns, both filled on both runs; flip rows for both.

## Problem 3 (not a bug; missing piece): variant comparison was a scratch script

The numbers for the invariance run (flips of permuted and synonyms against the same-session `qic_judge_prompt`, mean score change, lost/gained) came from a throwaway script over the report's tables. Proposal: the report also prints, per generation run, the verdict flips between every pair of judgings that share a judge model (same-checkpoint noise and variant effects). The pairwise agreement table already has most of it; adding lost/gained (direction) there is the small version.

## Problem 4: stale documentation

`convos/julian/26-11-21_instrumental_eval_harness_SUMMARY.md` still describes the data file as `data/input/instrumental_eval.json` (now `etpm.json`) and says `data.py` loads it "from the six upstream CSVs" (deleted). Fix: rewrite that bullet to current state.

## Order

1 (costs money on every rental), 2, 4, then 3 if wanted.
