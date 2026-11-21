# FUTURE_WORK

This file holds open ideas and deferred work items that don't belong to any single topic; agents add entries here instead of leaving TODOs scattered in code or chat. Entries carry enough context that a future agent can pick them up cold.

---

- **Cap-aware host choice for `ic-vast`** (26-11-21, from `convos/julian/26-11-18_vast_host_selection_LOG.md`, entry *9 + 6 caps: what they break, and explore's rate*). The policy (`src/ic_eval/vast/policy.py`) scores offers by predicted setup time but ignores the boot caps (`max_pull_minutes`, `max_build_minutes` in `configs/policy.yaml`). So it may rent hosts it expects to exceed a cap, and each time-out restarts the boot on the next offer. Fix: in `evaluate`, count each posterior draw in which an offer's pull exceeds the pull cap as a failure that costs the cap's minutes. Needed before the caps can go below about 12 min: Julian wanted 9 + 6, but a typical host needs about 10 min to pull the current image. Lowering the pull cap also needs a larger abort margin (3× kept the good hosts in the 26-11-21 replay; 2× aborted host 314882).
