C: (transcribed from chat) new convo. Can you use the vastai installation from `/home/jx/projects/targeted-parameter-decomposition` as a reference and do the same here. Also check the coding.md there. Also ask a lot of questions before you start implemeting

---

26-11-18, Claude Opus 5.5 — *reference launcher survey and questions before implementing*; context: this repo's README, all SUMMARYs, the end of `convos/julian/26-11-18_local_olmo_inspect_LOG.md` (vLLM vs llama.cpp answer), `tasks/hello.py`, `pyproject.toml`; in the reference repo `targeted-parameter-decomposition` (from here on "the SPD repo"): `spd/scripts/run_vast.py` in full, its YAML configs and blacklist, `convos/julian/26-10-05_vast_rentals_SUMMARY.md`, its `docs/CODING.md` (diffed against ours), the vast-related entries of its FEEDBACK.md and FUTURE_WORK.md. Nothing implemented yet.

## 1. What the SPD repo's launcher does

`spd-vast` (`spd/scripts/run_vast.py`, 1,082 lines, plus YAML machine configs) rents one GPU on vast.ai and prepares it [verified: code read 26-11-18]:

1. Loads a git-tracked machine config (`vast_<name>_config.yaml`, validated with pydantic): GPU name, price ceiling, min GPU memory, disk, Docker image, min reliability, datacenter-only, excluded countries (CN: Hugging Face is DNS-poisoned there), min CUDA, sort order, `uv sync` time budget. CLI flags override single fields.
2. Searches offers (`verified=true`, direct ssh port, blacklisted hosts excluded) and rents the first one that is still available, walking down the list because vast.ai's index lags the market.
3. Waits for boot, attaches the ssh public key through vast.ai, writes `~/.ssh/config.d/vastai.conf` (alias `vastai`), polls until sshd accepts the key.
4. Writes the WandB key to `/etc/profile.d/spd_env.sh` (read by login shells only).
5. Syncs code: the instance clones the public GitHub repo and is put on the local HEAD commit; rsync then uploads only the working tree without `.git` (Julian's uplink is slow, about 79 KB/s measured on 26-11-11).
6. Runs `uv sync` under a time budget (10 min).
7. Modes: `run` (stream the job), `detached`, `provision` (rent and prepare only), `sync` (re-upload the working tree to the current instance), plus `--list_offers`, `--dry_run`, `--offer_id`, `--destroy_on_exit`.
8. **Host failures** (instance vanished, not booted after 15 min, ssh failing after 5 min, `uv sync` over budget) put the host on a git-tracked blacklist and destroy the instance. Nothing is re-rented automatically (Julian's choice there: "No restarts").
9. Workarounds for CLI behaviour that cost real time there: `vastai destroy` prompts unless given `-y` and exits 0 even on failure, so the output is checked; stdin is closed so hidden prompts cannot hang; `--raw` failures show as empty stdout.

Almost every guard in it traces back to a failed rental recorded in its vast-rentals LOG. That is the main reason to port it rather than write something short from scratch.

## 2. What is different here

- **The job is serving, not training.** Here the GPU runs a vLLM server for Olmo 3 (one model checkpoint at a time, chosen by Hugging Face revision), and Inspect sends it prompts. There is no WandB and no experiment registry.
- **Weights come from Hugging Face** on every rental: 14.6 GB per 7B checkpoint, 64.5 GB per 32B checkpoint [verified: Hugging Face API, RLVR SUMMARY 26-11-16].
- **Results are Inspect `.eval` logs**, which must end up on the laptop before the instance is destroyed.
- **Secrets differ:** possibly a judge API key and an `HF_TOKEN`, no WandB key.

## 3. Facts checked today

- [verified: `git ls-remote` without credentials, 26-11-18] `origin` (`github.com/julxi/bluedot-technical-ai-safety-project`) is public over https, and local HEAD `0e589b4` is on it. So the SPD repo's clone-then-rsync sync works here unchanged.
- [verified: PyPI JSON 26-11-18] vLLM 0.34.0 is current; `requires_python >=3.11,<3.15`, one `cp38-abi3` Linux wheel. It installs on this project's Python 3.14. [assumed] that its pinned torch version also has 3.14 wheels; `uv lock` would show this before any rental.
- [verified: Docker Hub API 26-11-18] vast.ai publishes `vastai/vllm:v0.34.0-cuda-13.0` (updated 26-11-17), and older tags down to v0.29.0.
- [verified: `vastai search offers` 26-11-18, single GPU, verified hosts, reliability > 0.98, direct ssh port, CUDA >= 12.8, 100 GB disk, CN excluded; prices include the disk; snapshot, prices move hourly]:

  | GPU | offers | $/h | memory |
  |---|---|---|---|
  | RTX 4090 | 46 | 0.42-2.73 | 24 or 48 GB |
  | RTX A6000 | 2 | 0.53-0.57 | 48 GB |
  | L40S | 4 | 0.82-1.00 | 45 GB |
  | A100 SXM4 | 6 | 0.59-1.70 | 40 or 80 GB |
  | H100 SXM | 3 | 2.36-4.53 | 80 GB |
  | H200 | 5 | 3.77-6.35 | 140 GB |
  | 2x A100 80 GB | 2 | 2.36, 3.35 | 2x 80 GB |

- [verified: `vastai show instances` 26-11-18] No instances are running on the account, so nothing is billing. The SPD repo's `~/.ssh/config.d/vastai.conf` still points at instance 60932116 from 26-11-16, which no longer exists.
- [verified] `vastai` CLI 1.2.0 is installed locally with an API key. It now prints a deprecation notice for `show instances` (plural); the SPD launcher only uses `show instance <id>`, so this does not affect it yet.
- [verified: `pyproject.toml`, `find src`] `pyproject.toml` has no `[build-system]`, so `src/instr_eval/` (currently empty) is not installed as a package. A launcher with a command-line entry point needs one added.
- Flag: `uv.lock` is untracked. A lock file is normally committed, so that the rented machine and the laptop resolve the same versions. With the SPD repo's sync it would still reach the instance (rsync uploads untracked, non-ignored files), but it would not be in git history. Intended?

## 4. Questions

Each has my recommendation; answer with a `C:` line beneath it, or in chat. The ones marked **(blocking)** decide the design; the rest have defaults I would use if you don't care.

### A. Scope

**A1 (blocking). Do I write the launcher, or do you write it with a guide, like the laptop setup?** The laptop topic was for learning the tools yourself. Recommendation: I write it, because renting machinery is infrastructure, not what you want to learn; you keep writing the Inspect tasks.  
C: you write

**A2 (blocking). How much of the SPD launcher to port?**
- (a) Nearly all of section 1: blacklist with auto-destroy, walking down offers, boot/ssh/`uv sync` timeouts, clone-then-rsync sync, all modes, dry run, `--offer_id`. Drop WandB, the experiment registry and the `papers/` special case.
- (b) A slim version, about 300 lines: search, rent, ssh, sync, destroy. No blacklist, no timeouts.

C: (a)

Recommendation: (a). Each guard in it came from a lost hour or a billing instance; (b) would re-learn those lessons at your cost.

**A3. Copy the code into this repo, or share one package between both repos?** Recommendation: copy and adapt. Shared code couples two projects with different jobs and release rhythms, and a change for one could break the other.  
C: copy but see if it can be improved here (I don't care much if something breaks it can easily be fixed and don't cost anything). I want an extra feature though. An extra setting / additional command that sets a timer on the vm itself which destroys the instance after the timer runs out. Timer should also be easily deactivated / updated.

Answer (26-11-18, Claude Opus 5.5): Yes, and it is safer than I feared under E3 (b). [verified: vast.ai docs, *Docker environment* and API *hello world* pages, read 26-11-18] Every instance gets its own key in the env var `CONTAINER_API_KEY`, which "can only start, stop, or destroy that specific instance", and its id in `CONTAINER_ID`. The docs show `vastai destroy instance $CONTAINER_ID` run from inside the container. So the timer needs no account key on the machine. vast.ai has no built-in auto-destroy or end date [verified: not mentioned on any page read]. Design in the plan entry at the bottom (*implementation plan after Julian's answers*), section *Self-destruct timer*.

### B. Workflow on the GPU

**B1 (blocking). Where does Inspect run?**
- (a) **On the laptop**, talking to vLLM on the instance through an ssh tunnel (`ssh -L 8000:localhost:8000`). Logs land in your `logs/` directly; a judge API key never leaves the laptop. But the laptop must stay awake and online for the whole run, and a dropped tunnel fails the run. The traffic is only text, so your slow uplink is not a problem [concluded: a 10K-token response is roughly 40 KB].
- (b) **On the instance.** Survives laptop sleep and network drops. The judge key has to go to the instance, and the `.eval` logs must be copied back before destroying.
- (c) Both: start with (a), add (b) when runs get long.

Recommendation: (c), starting with (a). The pilot runs are short, and (a) has nothing to copy back.  
C: exactly (c), starting with (a) which is basically (a).

**B2 (blocking). What should the launcher start after renting?**
- (a) Nothing: it rents and prepares the machine, and you run `vllm serve …` by hand over ssh.
- (b) It also starts `vllm serve <model> --revision <checkpoint>` detached, waits until vLLM's `/health` answers, and opens the tunnel. vLLM flags (max model length, GPU memory share, reasoning parser, sampling defaults) live in a git-tracked config so they are recorded per run.

Recommendation: (b), plus (a) as `--mode provision`. vLLM silently takes sampling defaults from the model's `generation_config.json` and changes behaviour between versions (see the vLLM pros/cons answer in `convos/julian/26-11-18_local_olmo_inspect_LOG.md`), so flags typed by hand are an easy way to get runs that differ without anyone noticing.

C: I think there should be two modes for now. Simply renting + renting and running some script

Answer (26-11-18, Claude Opus 5.5): Understood as: `instr-vast` rents and prepares; `instr-vast --script <repo path>` additionally runs that script from the repo on the instance (in a login shell, detached, output to a log file). A `vllm serve` script would then be one such script, written later. The SPD repo's `sync` mode (re-upload edits to a running instance) is dropped for now. Say if you meant something else by "some script".

**B3 (blocking). How does vLLM get onto the machine?**
- (a) vast.ai's `vastai/vllm:v0.34.0-cuda-13.0` image: vLLM is preinstalled. But its version sits outside our `uv.lock`, and I don't know whether the image has `uv` and Python 3.14 (needed if Inspect runs there, B1 b).
- (b) A plain CUDA image, with vLLM as an optional dependency group in `pyproject.toml` that only the instance installs (`uv sync --group gpu`). The version is pinned in `uv.lock` and in git. The cost is a multi-GB download per rental, the step the SPD launcher puts under a 10-minute budget because slow hosts stall there.
- (c) `uv tool install vllm==0.34.0` on the instance, separate from the project environment.

Recommendation: (b), for one recorded version on every machine. If the download turns out slow in practice, switch to (a) with the image tag pinned in the config.  
C: I prefer (a). The more that's preinstalled the better. I understand that there is a problem with the uv.lock but can you explain again what exactly? Maybe we can explicitely remove it in the vastai script? Is there a cleaner solution?

Answer (26-11-18, Claude Opus 5.5): The "problem" was only about where the vLLM version is recorded, and it goes away with (a).
- With (b), vLLM would be a dependency in `pyproject.toml`, so its exact version would be in `uv.lock`, and every machine would install that version.
- With (a), vLLM comes from the image, in the image's own Python environment. `uv.lock` doesn't know about it. That is fine as long as the image **tag** is fixed in the git-tracked machine config (`vastai/vllm:v0.34.0-cuda-13.0`, never `latest`): the tag then records the version, in git, just as `uv.lock` would.
- So the clean solution: vLLM stays out of `pyproject.toml` entirely, and nothing needs removing. Our own Python environment and vLLM's never meet. vLLM runs as a server, and Inspect talks to it over HTTP, from the laptop for now.
- The one leftover: for now nothing on the instance needs our own Python environment at all, so the launcher skips `uv sync`. It comes back when Inspect runs on the instance (B1 b). Then `uv.lock` matters, and it should be committed (see the flag in section 3).
- Side effect of the CUDA 13.0 tag: the host's driver must support CUDA 13. [verified: offer search 26-11-18] That costs almost nothing: 145 of 148 single-GPU offers with at least 44 GB qualify.
- One open point: [verified: vast.ai vLLM template docs] vast.ai's vLLM template starts `vllm serve` by itself at boot, with the model from `VLLM_MODEL` (default `deepseek-ai/DeepSeek-R1-Distill-Llama-8B`). Whether the bare image does the same without the template, and how to switch it off, isn't documented. I'd look during the test rental (see G1).

**B4. Switching checkpoints.** A session will often cover several checkpoints (e.g. SFT, DPO, final). Should the launcher get a mode that restarts vLLM on the current instance with another model or revision, without renting again? Recommendation: yes (`--mode serve --revision …`). Each switch downloads 14.6 GB from Hugging Face. [assumed: 0.5-3 min at typical datacenter speeds, not measured]  
C: I don't know. That is too far in the future that I don't want to think about it yet

**B5. Hugging Face token.** The Olmo models are public, so no token is needed, but a token raises download rate limits. Do you have one you want sent to the instance?  
C: it's already done in the reference solution, right? I would do the same here then.

Answer (26-11-18, Claude Opus 5.5): No. [verified: `_forwarded_env_vars` in the SPD repo's `run_vast.py`, and its `.env.example`] The SPD launcher forwards only `WANDB_API_KEY` and `WANDB_ENTITY`; its Hugging Face downloads ran without a token. "The same" here therefore means no token. With Inspect on the laptop, nothing else needs forwarding either, so the launcher won't forward any secrets for now. If downloads hit rate limits, add `HF_TOKEN` then, over ssh (E1).

### C. Machine configs

**C1 (blocking). Which GPU configs?** Proposal:
- `7b` (default): any single GPU with at least 44 GB, among RTX A6000, L40S, 48 GB RTX 4090, A100. The SPD configs take one `gpu_name` each; vast.ai's query language also accepts a list (`gpu_name in [...]`), which matters here because each of these cards has few offers today (table in section 3). A 24 GB card holds the 7B's 14.6 GB of weights but leaves only about 8 GB for the attention cache, so few long responses at a time. [concluded: arithmetic]
- `32b`: H200 (140 GB). The RLVR SUMMARY already concluded that one 80 GB card leaves too little attention cache for the 32B.
- Two GPUs (2x A100 80 GB, for the 32B with tensor parallelism) need a `num_gpus` field; the SPD launcher hardcodes 1. Recommendation: leave it out until a 32B run is planned.

Disk: about 80 GB for `7b` (venv about 10 GB [assumed], several checkpoints at 14.6 GB), 200 GB for `32b`.

**C2. Datacenter-only?** In the SPD repo, consumer RTX 4090 hosts often failed (ssh never connected, slow PyPI). Recommendation: off, as there, with reliability above 0.98 and CN excluded. CN exclusion matters even more here, because every rental downloads from Hugging Face.

C: none of this is particularly important as configs are easily changeable. Do what you like here.

### D. State shared with the SPD repo

**D1 (blocking). The ssh alias.** The SPD launcher writes `~/.ssh/config.d/vastai.conf` with host alias `vastai`. If this launcher uses the same file, renting here overwrites the ssh entry of a running SPD instance (and the other way round). Recommendation: alias `bluedot-vast`, file `~/.ssh/config.d/bluedot-vast.conf`.  
C: yes new alias `bluedot-vast`

**D2. Host blacklist.** Options: (a) own file, empty; (b) own file, seeded with a copy of the SPD repo's 10 hosts [verified: `spd/scripts/vast_blacklist.yaml` there, 26-11-18], each `reason` noting where it came from; (c) read the SPD repo's file as well. Recommendation: (b). The failures there were the hosts' networks, which hurt any workload; (c) would make this repo depend on a path on your laptop.  
C: (a).

**D3. ssh key.** The SPD launcher reads `SPD_VAST_SSH_KEY` from `.env` (default `~/.ssh/id_rsa`). Recommendation: the same default key, variable `VAST_SSH_KEY`.  
C: yes, same default key

### E. Secrets, results, cost safety

**E1. How secrets reach the instance.** The SPD launcher sends the WandB key twice: as a container env var (so vast.ai's servers store it in the instance metadata) and in `/etc/profile.d/` over ssh. Its FUTURE_WORK.md notes that the first copy looks unnecessary. Recommendation: send secrets only over ssh, never via `--env`.  
C: yes, send secters only via ssh. Also write in coding that a secure route should always be taken except authorised by me.

**E2. Results back to the laptop.** If Inspect runs on the instance (B1 b), copy `logs/` back with rsync before destroying, and refuse to destroy if that copy fails. Agreed?  
C: Who is refusing. If I run `vastai destroy` there is nothing to refuse, I suppose. I'd say no code for this for now.

Answer (26-11-18, Claude Opus 5.5): I meant the launcher, in its own destroy paths (`--destroy_on_exit`). A plain `vastai destroy` can't be stopped, as you say. Agreed: no code for it now.

**E3 (blocking). Protection against a forgotten instance.** The largest cost risk is an H200 billing overnight. Options:
- (a) As in the SPD repo: the destroy command is printed, and `--destroy_on_exit` for jobs that run to completion.
- (b) Additionally an idle self-destruct: the instance destroys itself after N hours or after M minutes without vLLM requests. That needs a vast.ai API key on the instance, which can rent and destroy anything on your account. A scoped key would limit that, if vast.ai offers one; I have not checked.
- (c) Additionally a local check: every launcher call first lists your running instances and their hourly cost.

Recommendation: (a) + (c) now; (b) only if you plan unattended overnight runs.  
C: I think I already made a suggestion for this. yes to (a). something similar to (c), in the summary after a succesful provision also add the hourly costs.

Answer (26-11-18, Claude Opus 5.5): Yes: your timer (A3) is option (b), with the per-instance key instead of the account key. The summary will show the $/h including disk, the timer deadline, and the most the rental can cost before the timer fires ($/h × hours left).

### F. Coding rules from the SPD repo's `docs/CODING.md`

**F1 (blocking). Which parts go into this repo's `docs/CODING.md` §Additional instructions?** The SPD file adds four blocks to the template we both share:
- (a) **Research-code principles:** fail fast, no legacy fallbacks, narrow types (avoid `| None` without meaning), no try/except for control flow, YAGNI; `match` over `if/elif`; PEP 604 unions; no `from __future__ import annotations`; few default arguments, kept high in the call stack; no bare dicts for mixed-value structures.
- (b) **Wrapping an external CLI:** read its `--help` for prompts, assert on the success output rather than the exit code. Directly relevant here.
- (c) **"Running jobs on a rented vast.ai GPU"**, adapted (WandB parts dropped): check the GPU power limit after renting (a capped H100 ran 40% slower); launch over ssh as a login shell (`bash -lc`) so secrets from `/etc/profile.d/` load; detach with `ssh -n -f host 'setsid nohup … > log 2>&1 < /dev/null &'` (the `-f` comes from a FEEDBACK.md entry there; without it the call hung); `pkill` with a bracket pattern (`"[v]llm serve"`) because a plain pattern matches the ssh command itself; wall times are only comparable on one machine; compare the container's CPU quota with `nproc` (a 23-CPU quota on a 192-core host throttled jobs badly).
- (d) **Tooling:** basedpyright (type checking) and ruff (lint and format), run with `make check`.
- Also there: **no run artifacts in `convos/`**, only Markdown records.

Recommendation: (a), (b), (c) and the no-artifacts rule; (d) only if you want type checking. The launcher would be written to pass ruff and basedpyright either way.  
C: I want this to be a vastai change only. So in my understanding just (c)

Answer (26-11-18, Claude Opus 5.5): Agreed: (c) plus your secrets rule from E1, both under one vast.ai heading in `docs/CODING.md`. The launcher's own code still follows (b) (CLI output checked, not exit codes) in its comments, but that doesn't become a project-wide rule.

**F2. Dependencies and entry point.** The port needs `pydantic`, `pyyaml`, `fire` (command-line parsing from function arguments, as in the SPD repo) and `python-dotenv`. Proposed layout: `src/instr_eval/vast.py`, configs in `src/instr_eval/vast_configs/`, blacklist next to them, command `instr-vast` via `[project.scripts]`, and a `[build-system]` added to `pyproject.toml` so `src/instr_eval/` is installed. All right?  
C: not all right because too terse. Can you explain a a bit more detailed?

Answer (26-11-18, Claude Opus 5.5): Four parts.

**1. Where the files go.** `docs/CODING.md` already fixes `src/instr_eval/` as this project's Python package. The launcher would be one module in it, with its YAML files next to it:
```
src/instr_eval/
├── __init__.py               # empty, marks the package
├── vast.py                   # the launcher (~800 lines, port of the SPD run_vast.py)
└── vast_configs/             # not `vast/`: a folder named like the module next to it confuses imports
    ├── 7b.yaml               # machine config, the default: >= 44 GB card for the 7B
    ├── 32b.yaml              # machine config: H200 for the 32B
    └── blacklist.yaml        # failed hosts, starts empty (D2)
```

**2. Why `pyproject.toml` needs a `[build-system]` section.** `uv init` created an "application" project: `uv sync` installs the dependencies (inspect-ai, openai) into `.venv`, but not our own code. So `import instr_eval` fails, and no command of ours exists. A `[build-system]` section (3 lines, naming uv's own build backend `uv_build`) tells uv that the project is a package. `uv sync` then also installs `src/instr_eval/` into `.venv` in editable mode: edits take effect without reinstalling, and imports work from any directory. Later Inspect tasks in `tasks/` can import shared code from `instr_eval` the same way.

**3. Why a command `instr-vast`.** A `[project.scripts]` line `instr-vast = "instr_eval.vast:cli"` makes uv create `.venv/bin/instr-vast`. You then run `uv run instr-vast --list_offers` (or plain `instr-vast …` with the venv active) from any directory. The alternative without parts 2 and 3: a plain script, `uv run python src/instr_eval/vast.py …`, which works only with the right path. I recommend the command; it is the SPD repo's `spd-vast` setup.

**4. Dependencies**, all for the laptop. Nothing is installed on the instance.
- `pydantic`: checks the YAML config against a typed class, so a typo'd field or a string in a number field fails at once instead of producing a wrong offer search. [verified: `uv.lock`, 26-11-18] Already installed, as a dependency of inspect-ai; now listed explicitly, because our code imports it.
- `pyyaml`: reads the YAML files. Already installed (same reason).
- `python-dotenv`: reads `VAST_SSH_KEY` from `.env`. Already installed (same reason).
- `fire`: the only new package. It turns the launcher's function arguments into command-line flags (`--config 32b --max_price 5`), as in the SPD repo. The alternative is Python's built-in `argparse` with ~40 more lines of flag definitions. I'd keep fire, so the two launchers stay alike.
- The `vastai` CLI stays outside the project, as now (`~/.local/bin/vastai`, version 1.2.0). The launcher parses its output, whose format can change between versions. So the launcher logs the version it runs with.

### G. Testing

**G1 (blocking). A live test rental.** Several bugs in the SPD launcher only showed on real rentals (the hidden destroy prompt, wrong host fault attribution). After a dry run and offer searches (free), I'd do one short real rental on a 48 GB card: rent, start vLLM with the 7B final model, run `tasks/hello.py` through the tunnel, destroy. Estimated cost $0.50-1 [assumed: 30-60 min at the table's $0.42-1.00/h]. May I?  
C: Only a rental run + timeout check. Other checks come later

Answer (26-11-18, Claude Opus 5.5): OK. Test sequence in the plan entry below, section *Live test*. It adds one thing I'd like your OK for: about two minutes of read-only commands on the rented machine (what the vLLM image starts at boot; whether `CONTAINER_API_KEY` is visible over ssh). Without them, the launcher can't be finished correctly for this image.

Next step: wait for your answers, then write the implementation plan as a new entry here before coding.

---

26-11-18, Claude Opus 5.5 — *implementation plan after Julian's answers*; context: Julian's `C:` answers above (my in-place replies beneath them), the vast.ai docs on the per-instance key and the vLLM template (read 26-11-18 via a fetch sub-agent; pages listed under *Sources* below), an offer search by CUDA version, `uv.lock`. Not implemented yet.

## Decided (Julian's `C:` answers above)

- [decided: A1] I write the launcher. [decided: A2] Port nearly all of the SPD launcher. [decided: A3] Copy and adapt, improve where it helps, plus a **self-destruct timer** on the instance that is easy to update and switch off.
- [decided: B1] Inspect runs on the laptop for now, through an ssh tunnel; on the instance later. [decided: B2] Two modes: rent only, and rent + run a script. [decided: B3] vLLM comes preinstalled in vast.ai's image. [decided: B5] No Hugging Face token, as in the SPD repo (which turned out to forward none).
- [decided: C1/C2] Configs are my choice.
- [decided: D1] ssh alias `bluedot-vast`. [decided: D2] Own blacklist, starting empty. [decided: D3] Same default key `~/.ssh/id_rsa`.
- [decided: E1] Secrets reach the instance only over ssh, and `docs/CODING.md` says so. [decided: E2] No copy-back code for now. [decided: E3] Print the destroy command, `--destroy_on_exit`, the timer, and the hourly cost in the summary.
- [decided: F1] `docs/CODING.md` gets only the vast.ai job rules (block c), plus the E1 rule.
- [decided: G1] Live test: one rental plus a timer check, nothing else.

## What the launcher does (`instr-vast`, in `src/instr_eval/vast.py`)

**Ported from the SPD launcher, unchanged in substance:**
- Machine config in git-tracked YAML, checked by pydantic, single fields overridable by flags.
- Offer search: verified hosts, direct ssh port, reliability, CUDA, disk, price, CN excluded, blacklisted hosts excluded (with a check that vast.ai honoured it).
- Renting walks down the offers when one is gone; `--offer_id` with the same checks; `--list_offers` with host ids; `--dry_run`.
- Boot wait (15 min), detection of vanished and dead instances, ssh key attach with one re-attach, ssh wait (5 min).
- Host failures go on the blacklist and the instance is destroyed; no automatic re-rent.
- Destroy with `-y` and a check of its output; stdin closed for every `vastai` call.
- Code sync: clone from GitHub, put on the local HEAD commit, rsync the working tree without `.git`. HEAD must be pushed.

**Dropped:**
- WandB, the experiment registry, the `papers/` special case.
- `uv sync` and its 10-min budget. Nothing on the instance uses our Python environment yet; it returns with B1 (b).
- The `run`/`detached`/`sync` modes, and passing env vars through `vastai create --env` (no secrets to send).

**New:**
- `--script <repo path>`: after preparing, run that repo script on the instance as a login shell, detached, output to `/root/bluedot/logs/remote/<script>_<time>.log`. The launcher prints the `tail -f` command. Without `--script`: rent and prepare only.
- `gpu_names` in the config is a **list** (vast.ai's `gpu_name in [...]`), because each 48 GB card has only a few offers.
- Configs:
  - `7b` (default): RTX A6000, L40S, RTX 4090 (48 GB), A100, RTX PRO 5000, at least 44 GB, under $1.20/h, 80 GB disk.
  - `32b`: H200 / H200 NVL, under $7/h, 200 GB disk.
  - Both: image `vastai/vllm:v0.34.0-cuda-13.0`, CUDA >= 13.0, reliability > 0.98, no datacenter filter, cheapest first.
  - The RTX PRO 5000 was not in my first proposal. It is the most common card with at least 44 GB today (20 offers) [verified: offer search 26-11-18].
- Improvements:
  - From the SPD SUMMARY's open items (e) and (f): fail at once when the boot status shows a DNS error, and print the boot status only when it changes. On "Permission denied (publickey)", read `vastai logs` for the host-fault message "bad ownership or modes" and put the cause in the blacklist reason.
  - From the CODING lessons: the summary also shows the GPU power limit and the container's CPU quota next to `nproc`.
- **Summary after renting:** instance, host, GPU, $/h including disk, timer deadline, the most the rental can cost before the timer fires, and the ssh, tunnel and destroy commands.

## Self-destruct timer

- **On the instance:**
  - A small watchdog script, written by the launcher and started detached at rent time. Every 30 s it reads `/root/destroy_at` (a unix time). File missing = timer off.
  - Once the time has passed, it destroys its own instance with `CONTAINER_ID` and `CONTAINER_API_KEY`, the per-instance key that can only start, stop or destroy this one instance. Failed attempts are retried every 30 s and logged to `/root/self_destruct.log`.
  - It reads both variables from PID 1's environment (`/proc/1/environ`). The vast.ai docs warn that container env vars don't always reach ssh sessions.
- **Checked before the timer counts:** the launcher confirms the key works with `vastai start instance $CONTAINER_ID`, which the docs give as a harmless test on a running instance. If the check fails, the launcher destroys the instance from the laptop and stops, because the safety net is missing.
  - Open detail, settled in the live test: whether the image has the `vastai` CLI, or the watchdog uses curl against the REST endpoint `DELETE /api/v0/instances/<id>/`. The docs show that endpoint with the account key only.
- **From the laptop**, all over the `bluedot-vast` alias:
  - `instr-vast timer 2h` (or `90m`) sets or moves the deadline to now + duration.
  - `instr-vast timer off` switches it off.
  - `instr-vast timer` shows the deadline, time left, and whether the watchdog is alive, and restarts it if it died.
- **At rent time:** `--timer 2h` or `--timer off`. The default comes from the config: 3 h for `7b`, 2 h for `32b` (my choice).
- **`--destroy_on_exit`** with `--script`: when the script ends, the deadline is set to "now", so the timer destroys the instance within 30 s.
- **Limits:**
  - A host that has lost its network can't reach vast.ai, so it can't destroy itself. The printed laptop command stays the fallback.
  - A *stopped* instance runs nothing, so its timer is frozen, and stopped instances still bill for disk.

## `docs/CODING.md` additions (one heading: *Rented vast.ai GPUs*)

- **Secrets go to rented machines only over ssh.** That means `/etc/profile.d/` written over ssh. Never through vast.ai instance settings (`--env`, which vast.ai stores), command-line arguments, git, or the synced working tree. Any other route only with Julian's explicit authorisation.
- **The SPD repo's job rules, adapted:**
  - Check the GPU power limit after renting.
  - Launch remote commands as a login shell (`bash -lc`).
  - Detach with `ssh -n -f bluedot-vast 'setsid nohup … > log 2>&1 < /dev/null &'`.
  - Use `pkill` with a bracket pattern (`"[v]llm serve"`).
  - Compare wall times only on the same machine.
  - Compare the container's CPU quota (`/sys/fs/cgroup/cpu.max`) with `nproc`.

## Live test (G1)

1. Free steps: `uv sync`, `instr-vast --list_offers` for both configs, `--dry_run`.
2. One rental with the `7b` config, cheapest offer. Then:
   - about two minutes of read-only inspection: what the image started at boot (`supervisorctl status`, `nvidia-smi`), the vLLM and Python versions, whether `CONTAINER_ID`/`CONTAINER_API_KEY` are visible, whether `vastai` is installed.
   - Timer check: `instr-vast timer` (shows the default), `timer off` (watchdog stays alive, nothing happens), then `timer 3m`. Then check from the laptop that the instance disappears within about 4 minutes (`vastai show instance`).
   - If it doesn't disappear, I destroy it from the laptop and record the failure.
3. Estimated cost: $0.10-0.30. [assumed: 15-25 min at the $0.42-0.60/h of the cheapest 48 GB offers on 26-11-18; boot time with a large image pull not measured]

## Waiting on Julian

1. Is the `--script` reading of "renting and running some script" right (B2)?
2. OK for the two minutes of read-only inspection during the test rental (G1)?
3. Anything to change in the plan, e.g. the default timer lengths? If not: go, and I implement and run the free steps, then the test rental.

Sources (vast.ai docs, read 26-11-18): https://docs.vast.ai/guides/instances/docker-environment, https://docs.vast.ai/api-reference/hello-world, https://docs.vast.ai/cli/reference/destroy-instance, https://docs.vast.ai/vllm-llm-inference-and-serving

C: I changed the structure. `instr_eval` is now `ic_eval`  
C: Ok, F2 is alright  
C: B2 and G1 are fine.

---

26-11-18, Claude Opus 5.5 — *launcher implemented; free checks; before the test rental*; context: Julian's three comments above, the plan entry, the SPD launcher.

**Implemented** (not committed):
- `src/ic_eval/vast.py`: command `ic-vast` with subcommands `rent`, `offers`, `timer`. Subcommands rather than the plan's flags, so a bare `ic-vast` only prints help and never spends money. The command is named after the package, since Julian renamed `instr_eval` to `ic_eval`.
- Configs `src/ic_eval/vast_configs/7b.yaml` and `32b.yaml`, and an empty `blacklist.yaml`.
- `pyproject.toml`: `[project.scripts]`, a `[build-system]` with `uv_build` and `module-name = "ic_eval"`, and the dependencies fire, pydantic, pyyaml, python-dotenv (`uv add`; `uv.lock` updated).
- `docs/CODING.md`: §*Rented vast.ai GPUs* (the secrets rule and the SPD repo's job rules), and the package name `ic_eval` in the layout line.
- Deviations from the plan:
  - Any failure before the watchdog runs destroys the instance from the laptop. The SPD launcher left "our" failures running. Here nothing else would stop them.
  - The watchdog is Python (standard library only), not shell. It calls vast.ai's REST API with `CONTAINER_API_KEY`.
  - `instance.json` on the instance holds the price, so `ic-vast timer` can show the remaining cost.
  - `ssh -G` checks that ssh actually resolves the alias. A missing `Include` would otherwise look like a host failure and blacklist an innocent host.
  - The offer search asserts that every returned GPU is in `gpu_names`.

**Free checks** [verified: run 26-11-18]:
- `ruff check` and `ruff format`: clean. basedpyright: 0 errors; 103 warnings from its strict defaults (mostly `Any` from vastai's JSON).
- The watchdog source parses as Python 3.8.
- Both configs load; the duration parser rejects `3`, `'3'`, `'2d'` and `'0.5m'`.
- `ic-vast offers`: 20 offers for `7b` from $0.474/h, 6 for `32b` from $4.397/h.
- `ic-vast rent --dry_run` stops, as intended, on the unpushed HEAD (local `main` 2 commits ahead of origin).
- Found: the three cheapest `7b` offers are on hosts 124072 and 135676. Both are on the SPD repo's blacklist with "not running after 900s".

C: (transcribed from chat) [selected option] "You may push main" — in answer to how local HEAD gets pushed before the test rental.
C: (transcribed from chat) [selected option] "Keep empty, skip via --offer_id" — in answer to what the test does about SPD-blacklisted hosts 124072 and 135676.

---

C: (transcribed from chat) No, Image pulling can be really fast on some hosts. This host is just slow. I have further plans for the blacklists that make this better, but we don't do it there. If a host gets blacklistet just use another one, that's fine. Actually for this test I'd like you to be quite agressive in weeding out slow hosts (you can keep your own blacklist for this task if you need).

C: (transcribed from chat) can you create a gitignored scratch folder in this repo and keep the list there

---

26-11-18, Claude Opus 5.5 — *test rentals: launcher works, timer destroys the instance, container restart kills the watchdog (fixed, untested)*; context: this LOG, the launcher output of both rentals, read-only inspection of the second instance.

**Rental 1, aborted** (instance 61289926, offer 40187939, L40, host 169171, Vietnam):
- [verified: launcher log] Rented at 18:06:44. The `vastai/vllm` image (10.86 GB compressed for amd64 [verified: Docker Hub API]) was still being pulled at 18:18:22, 11.5 min in.
- Per Julian's comments above, I stopped the launcher and destroyed the instance by hand ("destroying instance 61289926.", none left running).
- The host is on a test-only skip list, `scratch/vast_test_slow_hosts.txt`, together with the SPD repo's 10 blacklisted hosts. `scratch/` was already gitignored; its `.gitignore` comment now says it is for local working files generally. This repo's blacklist stays empty.
- Fixed meanwhile: `--offer_id` showed the price for vast.ai's default 5 GB disk ($0.456/h) instead of the 80 GB we rent ($0.490/h). The lookup now passes `--storage`.

**Rental 2** (instance 61292124, offer 51338031, A40 48 GB, host 682584, Belgium, $0.702/h including disk, chosen for its advertised 9.4 Gbit/s):
- [verified: launcher log] Rented 18:20:15; image pulled by about 18:24:30; vast.ai's own build step (apt-get) until 18:26:20; running 18:26:31; ssh accepted the key within seconds; watchdog check passed and the timer was set to 3 h at 18:26:47-48; clone + rsync done; summary at 18:26:52. **6.5 min from renting to ready.**
- Summary values: GPU power limit 300 W (the A40's full rating), CPU quota 61.2 CPUs of `nproc` 255.
- [verified: read-only inspection 26-11-18]
  - The bare image does **not** start a vLLM server: no vllm process, no supervisor, GPU memory 0 MiB, no `VLLM_MODEL` set. vast.ai starts it through its ssh launch script (`bash /.launch`), not the template's.
  - vLLM 0.34.0 (package metadata); Python 3.12.3; `uv`, `vastai`, git and rsync present.
  - `CONTAINER_ID` and `CONTAINER_API_KEY` are **not** in ssh sessions, only in PID 1's environment. So the watchdog reading `/proc/1/environ` was necessary.
  - The launch script also writes `CONTAINER_API_KEY` to `~/.vast_api_key`.
  - The repo arrived at `afebdf6` with the local uncommitted changes showing as such.
- **The timer works** [verified: one test]. `ic-vast timer` showed the deadline and cost; `timer off` removed the deadline; `timer 2m` at 18:27:47 set 18:29:47. vast.ai reported the instance gone (`{"instances": null}`) at 18:30:26, with laptop polls every ~16 s. The REST call with the per-instance key works for both the check (`PUT state=running`) and the destroy (`DELETE`).

**Found and fixed, not yet tested:**
- The container **restarted** at 17:27:19 UTC (PID 1's start time), 27 s after the launcher finished. This cut my inspection's ssh session ("closed by remote host") and killed the watchdog. `/root` survived. The first `ic-vast timer` call reported the watchdog dead and restarted it, as designed. Without that call, the 3 h timer would never have fired. Why the container restarted is unknown. My `vllm --version` was running at that moment; I think it is unlikely to be the cause, but I did not check.
- Fix: the launcher now also appends the watchdog's start command to `/root/onstart.sh`, which vast.ai's `/.launch` runs on every container start. It uses the absolute `python3` path, because onstart runs with PID 1's environment. This needs one more rental to verify, e.g. with `vastai reboot instance`.

**Cost of both rentals:** about $0.20-0.25 [assumed: from 12 min at $0.49/h and 10 min at $0.70/h; billing not checked].

---

C: (transcribed from chat) I think I'd like the configs to be more technical named not by the model

---

26-11-18, Claude Opus 5.5 — *configs renamed by hardware*; context: the comment above.

Renamed `src/ic_eval/vast_configs/7b.yaml` → `48gb.yaml` (still the default) and `32b.yaml` → `h200.yaml`, following the SPD repo's hardware names (`h100`, `a100`). The model sizes stay in each file's header comment as the reason for the card class. Updated `DEFAULT_CONFIG`, the docstrings and the YAML comments. [verified: `ic-vast offers` with both new names; `--config 7b` now fails, listing `48gb, h200`.]

Also answered in chat: `openai` stays in `dependencies`. inspect-ai doesn't depend on it, but Inspect's vLLM provider and its `openai-api/...` provider import it [verified: `uv.lock`; inspect_ai `model/_providers/vllm.py` line 10].

---

C: (transcribed from chat) There is no `ic-vast --sync` command?

(After I confirmed there is none and offered to add one:)

C: (transcribed from chat) Yes please

---

26-11-21, Claude Opus 5.5 — *ic-vast sync added (re-upload to a running instance)*; context: `cli.py`, `remote.py`, `docs/CODING.md`, this topic's SUMMARY, the local_olmo_inspect LOG entry that hit the missing re-sync (a new `scripts/serve_vllm.sh` was not on the rented instance).

**Why:** the working tree was synced only once, inside `rent`. The run/detached/sync modes of the SPD launcher had been dropped at the start (Julian's answers above). A script written after renting therefore had to be copied by hand.

**What:** `uv run ic-vast sync [--allow_delete]` (`cli.py`, function `sync`). It reuses `sync_repo` from `rent`: the instance's clone is put on our branch and HEAD commit (fetched from GitHub, so HEAD must be pushed), then rsync makes the files match our working tree, uncommitted changes included. `build_checkout_script` was already written to be safe on a re-sync (`update-ref` + `symbolic-ref` + `reset --mixed`, which never touch the working tree).

**Added guard (my addition, not asked for):** the rsync runs with `--delete`. At rent time that only touches the fresh clone. On a used instance it would silently remove any file under `/root/bluedot` that we don't have locally and that the instance's `.gitignore` doesn't cover, e.g. outputs written to a tracked path. So `sync` first does a dry run of the same rsync (`--dry-run --itemize-changes`, `remote.py`: `files_a_sync_would_delete`, `parse_rsync_deletions`) and stops with the list of paths unless `--allow_delete` is passed. Not guarded: edits made on the instance to files we also have are overwritten (rsync can't tell them from our own edits). Running processes are not affected: a sync changes files only.

**Found while writing the test** [verified: local rsync 3.2.7, 26-11-21]: `--delete` respects the *receiving* side's `.gitignore` files. A destination without `.gitignore` had its `*.log` file listed for deletion even though the source ignored it. On the instance the clone carries the committed `.gitignore`, so it protects `logs/` and the like; the test gives both sides a `.gitignore`.

**Checks:**
- [verified: `make check` 26-11-21] format, lint, basedpyright 0/0, 46 tests passed (2 new in `tests/vast/test_resync.py`; they run the production rsync flags between two local temp directories).
- [verified: live, instance 61848825, 26-11-21, one run each]
  - `ic-vast sync` with nothing to delete: fetch + rsync ran (21 KB sent), `scripts/serve_vllm.sh` arrived, and the instance's `git status --short` matched the laptop's exactly (HEAD `a9636c0`).
  - With a probe file `zz probe.txt` (a space in the name) placed on the instance: the sync stopped, printed `/root/bluedot/zz probe.txt` as the one path it would delete, and exited 1 without syncing. The probe file was removed by hand afterwards.
  - `--allow_delete` itself was not run live; it only skips the assert.

---

C: (transcribed from chat) I have stopped the machine. Can you write a script that spins up the machine and sets the tunnel?

---

26-11-22, Claude Opus 5.5 — *scripts/gpu_up.sh: rent, serve, tunnel in one command*; context: the InstrumentalEval harness topic (`convos/julian/26-11-21_instrumental_eval_harness_LOG.md`), where Julian ran vLLM on instance 62001064

`scripts/gpu_up.sh [ic-vast rent options]` on the laptop:
1. Refuses to start while `scratch/vast_current_instance.json` exists, because renting again would overwrite it and the old session would never be recorded (and might still be billing). Use `ic-vast destroy` first.
2. Kills a leftover tunnel on port 8000 (`pkill -f "[l]ocalhost:8000 bluedot-vast"`; exit 1 = none found is accepted, other errors fail).
3. `uv run ic-vast rent --script scripts/serve_vllm.sh "$@"`, which blocks until the instance is ready and starts vLLM detached.
4. Opens the tunnel with `ssh -f -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 8000:localhost:8000 bluedot-vast`.
5. Polls `localhost:8000/health` every 10 s for up to 15 min. It stops early with the end of the server log if ic-vast's wrapper line "[ic-vast] script exited" appears in `/root/bluedot/logs/remote/serve_vllm_*.log`, and prints the log on timeout too.

Checks: `bash -n` passes; shellcheck is not installed; not run end to end, since that rents a machine [assumed: works; needs one real rental]. My attempt to run it locally to test the guard in step 1 was blocked by the permission system, correctly, because a failing guard would have rented.

Open: at the time of writing, `scratch/vast_current_instance.json` still lists instance 62001064, although Julian says he stopped the machine. If he stopped it outside `ic-vast destroy`, the rental is not recorded in `rentals.jsonl` and a stopped vast.ai instance still bills for disk.

---

C: (transcribed from chat) I'd also like to distinguish the scripts between vm scripts and laptop scripts

---

26-11-22, Claude Opus 5.5 — *scripts split into scripts/vm/ and scripts/laptop/*

Moved `scripts/serve_vllm.sh` → `scripts/vm/serve_vllm.sh` and `scripts/gpu_up.sh` → `scripts/laptop/gpu_up.sh` (plain `mv`, no git operation; git will show the tracked `serve_vllm.sh` as deleted plus a new untracked file until Julian stages the move). Updated: the usage comments in both scripts, `gpu_up.sh`'s repo-root `cd` (now `../..`) and its `--script` path, the `ic-vast` docstrings in `cli.py`, the README index, both affected SUMMARYs, and a convention paragraph in `docs/CODING.md` §Rented vast.ai GPUs. Older LOG entries keep the old paths (append-only). [verified: `bash -n` on both scripts; ruff clean on `cli.py`]

The remote log name is unchanged (`serve_vllm_<timestamp>.log`, from the script's file stem), so `gpu_up.sh`'s log checks still match.

---

C: (transcribed from chat) If I run `bash scripts/laptop/gpu_up.sh` it checks some `json` in scratch. That is a bit annoying. I often destroy vastai instances over the vastai console and then I have to remember to delete something in scratch. Can this be fixed?

---

26-11-22, Claude Opus 5.5 — *rent forgets an instance destroyed in the console*; context: read README, this topic's SUMMARY, `gpu_up.sh`, `cli.py` (rent, destroy), `market.py`, `records.py`, `model.py`'s use of records

Change: the check moved from `gpu_up.sh` into `ic-vast rent` (new `_forget_instance_if_gone()` in `cli.py`, called after the CLI version check, skipped under `--dry_run`). If `scratch/vast_current_instance.json` exists, rent asks vast.ai (`show_instance`):
- Instance gone (console destroy, `vastai destroy`, timer, host): appends an `End` record with the new reason `"gone"` to `rentals.jsonl`, deletes the scratch file, rents as usual.
- Instance still exists, in any status (a stopped one still bills for disk): refuses, naming its status and `ic-vast destroy`. This is the old behaviour of `gpu_up.sh`; plain `ic-vast rent` had no such check before and silently overwrote the record.

Why record an End rather than just deleting the file: the session's end would otherwise be missing from the history. `End` records are not read by the host model (`model.py` only uses `Attempt`), so the new reason value changes nothing there; it is a new Literal value, and old records still parse [concluded: `End` appears only in type hints in `model.py`].

`gpu_up.sh`: its own check is removed, and the leftover-tunnel `pkill` now runs after the rent, so a refused rent no longer closes a working tunnel to the still-alive instance.

Checks:
- [verified: `uv run pytest tests/vast`, 49 passed, 26-11-22] new `tests/vast/test_stale_instance.py` (gone → End recorded and file removed; existing instance → refusal, nothing written; no file → vast.ai not asked).
- [verified: live read-only call 26-11-22] `show_instance(61848825)` (the instance of the 26-11-21 sync test, since destroyed) returns `None`, the case the new code treats as gone.
- [verified: live read-only call 26-11-22] the record currently in scratch, instance 62015437 (host 500527), is gone from vast.ai: Julian's exact case. I left it alone; the next rent will record and clear it.
- ruff check/format clean; `bash -n` on `gpu_up.sh`. Not run end to end (that rents a machine).
