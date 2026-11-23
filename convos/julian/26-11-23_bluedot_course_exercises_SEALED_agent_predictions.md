# SEALED: agent predictions (do not open before the results exist)

Julian asked (C: comment 26-11-22 in `convos/julian/26-11-22_bluedot_course_exercises_LOG.md`) that the agent's predictions stay hidden until his own are written and the tests have run. This file is a commitment: its SHA-256 is recorded in that LOG (entry *answers to the first comment: crux list, compute estimate, first test*). Do not edit it; a changed hash means it was edited. Later predictions go in a new sealed file.

Written 26-11-23 by Claude Opus 5.5, before any of these tests ran. What I knew: the throughput-sweep logs' per-category median reply lengths for the final Olmo 3 7B Think at temperature 0.6 (1,406-2,525 tokens), the longest reply (9,391), all 152 replies per run finished within 16,000 tokens; the Olmo 3 paper's remark that thinking length dips and then grows over RLVR. I did not look at any reply text for this.

## Test A (minutes, existing logs): final 7B, temperature 0.6, bf16 c32 run, 152 replies

- A1. Share of replies whose thinking ends (answer starts) within the first 1,024 output tokens: **15%** (80% interval 5-30%).
- A2. Share of replies with explicit evaluation-awareness wording in the thinking text (the model says it is being tested, evaluated, or that this is a test/benchmark/safety check about itself): **8%** (80% interval 1-25%). Mentions of "hypothetical", "scenario" or "role-play" alone don't count; I expect those in more than half of the replies.

## Test B (hours, GPU): SFT, DPO and final 7B Think, greedy, max_tokens 16,000, one reply per task (76 per checkpoint)

- B1. Share finishing thinking within 1,024 tokens, at every checkpoint, below 30%: **70%** confident.
- B2. The final model has a lower share finishing within 1,024 tokens than SFT (so more truncation at the final checkpoint in the paper's setting): **55%** confident. Basically a coin flip; slight lean because RL tends to lengthen reasoning.
- B3. At least one greedy reply per checkpoint loops until the 16,000-token cap: **60%** confident for at least one of the three checkpoints; **25%** for all three.
- B4. Difference between SFT and final in the share finishing within 1,024 tokens is more than 15 percentage points: **35%**.

## What would surprise me

- More than half of the final model's replies finishing within 1,024 tokens. That would mostly kill the truncation critique.
- Explicit evaluation awareness in more than a third of replies of a 7B model.
