# SUMMARY: vast.ai GPU launcher `ic-vast` (port of the SPD repo's `spd-vast`)

**Last updated:** 26-11-18 (launcher rebuilt as a package with Bayesian host choice, see the host-selection topic; timer self-destroy verified; watchdog restart fix untested)

Julian asked to set up vast.ai GPU rentals here the way his other project, `/home/jx/projects/targeted-parameter-decomposition` ("the SPD repo"), does them, adopt the relevant part of that repo's `docs/CODING.md`, and ask many questions first. The questions, Julian's `C:` answers and the plan are in the LOG.

## What exists (uncommitted)

- **Code: package `src/ic_eval/vast/`** since the host-selection topic rebuilt it (`vast.py` was split into modules; usage in `cli.py`). Command `uv run ic-vast`:
  - `ic-vast offers` lists matching offers and rents nothing.
  - `ic-vast rent [--script x.sh] [--config h200] [--timer 2h|off] [--offer_id N] [--dry_run]` rents and prepares a machine, and with `--script` runs that repo script on it.
  - `ic-vast timer [2h|90m|off]` shows or changes the self-destruct timer.
  - Ported from the SPD launcher: the offer search, walking down unavailable offers, boot and ssh timeouts, the destroy-output check, and code sync (GitHub clone plus rsync of the working tree; HEAD must be pushed). The host blacklist was first ported, then replaced by the rental history and host model of `convos/julian/26-11-18_vast_host_selection_SUMMARY.md`.
  - Dropped for now [decided: Julian's answers]: WandB, `uv sync` on the instance, the run/detached/sync modes, forwarding secrets.
- **Configs**, now in `src/ic_eval/vast/configs/` (filters since loosened, see the host-selection topic):
  - `48gb.yaml` (default; sized for Olmo 3 7B): one of nine 44-48 GB card types, under $1.20/h, 80 GB disk, 3 h timer.
  - `h200.yaml` (sized for Olmo 3 32B): H200, under $7/h, 200 GB disk, 2 h timer.
  - Named by hardware, not by model [decided: Julian, chat 26-11-18, transcribed in the LOG]; first named `7b`/`32b`.
  - Both use `vastai/vllm:v0.34.0-cuda-13.0`, with vLLM preinstalled [decided: B3]. The pinned tag records the vLLM version, so vLLM stays out of `pyproject.toml`.
- **Self-destruct timer** [decided: Julian's feature request]:
  - A Python watchdog on the instance destroys the instance once the deadline in `/root/self_destruct/destroy_at` has passed.
  - It uses vast.ai's per-instance key `CONTAINER_API_KEY`, which can only start, stop or destroy that instance, so no account key goes to the machine.
  - Before arming, the launcher checks that the key works and that the instance's `CONTAINER_ID` equals the rented id. Any failure before then destroys the instance from the laptop.
  - The summary shows $/h including disk, the deadline, and the cost until the deadline.
- **ssh alias `bluedot-vast`** (file `~/.ssh/config.d/bluedot-vast.conf`), separate from the SPD launcher's `vastai` [decided: D1].
- **`pyproject.toml`:** `[project.scripts]`, a `uv_build` `[build-system]` with `module-name = "ic_eval"`, and the dependencies fire, pydantic, pyyaml, python-dotenv.
- **`docs/CODING.md`** §*Rented vast.ai GPUs*:
  - Secrets go only over ssh stdin, never via `vastai create --env`, command lines, git or logs, unless Julian authorises otherwise [decided: E1].
  - The SPD repo's job rules: power limit, login shell, detaching with `ssh -n -f`, `pkill` with a bracket pattern, comparing wall times only on one machine, CPU quota [decided: F1].
- `scratch/` (gitignored) holds `vast_test_slow_hosts.txt`, the test's own skip list of slow hosts. The repo blacklist stays empty, per Julian.

## Test results (26-11-18)

- [verified: launcher log] An A40 in Belgium went from rented to ready in 6.5 min. The first host (L40, Vietnam) was still pulling the 10.86 GB image after 11.5 min. It was aborted and destroyed by hand, per Julian's request to weed out slow hosts aggressively.
- [verified: inspection] The bare `vastai/vllm` image starts no vLLM server. It has vLLM 0.34.0, Python 3.12.3, `uv`, `vastai`, git and rsync. `CONTAINER_ID` and `CONTAINER_API_KEY` are visible only in PID 1's environment, not in ssh sessions.
- [verified: one test] `ic-vast timer` show, off, and `2m` all work. The instance destroyed itself within 40 s of the deadline.
- **Open:** the container restarted on its own 27 s after it was ready, and that killed the watchdog. Cause unknown. **Fix, untested:** the watchdog is now also started from `/root/onstart.sh`, which vast.ai runs on every container start. Verifying it needs one more short rental, e.g. with `vastai reboot instance`.
- Both test rentals cost about $0.20-0.25 [assumed: from durations].

## Next

- Julian: review the diff and commit (nothing is committed).
- Verify the onstart restart fix on a rental.
- A `vllm serve` script for `--script`, and pointing Inspect at it through the tunnel. Not done: Julian said "other checks come later".

- LOG: `convos/julian/26-11-18_vast_gpu_runner_LOG.md` (entries *reference launcher survey and questions before implementing*, *implementation plan after Julian's answers*, *launcher implemented; free checks; before the test rental*, *test rentals: launcher works, …*)
- See also: `convos/julian/26-11-18_vast_host_selection_SUMMARY.md` — replaced the blacklist with a Bayesian host model, four renting modes, speed-based abort with automatic re-rent, probes, and a testing setup.
- See also: `convos/julian/26-11-18_local_olmo_inspect_SUMMARY.md` — the vLLM-vs-llama.cpp answer that motivated the move to a rented GPU; `tasks/hello.py` from there is the planned first real job.
- See also: `convos/julian/26-11-16_rlvr_instrumental_convergence_SUMMARY.md` — hosting and price analysis, GPU sizing for the 7B and 32B models.
