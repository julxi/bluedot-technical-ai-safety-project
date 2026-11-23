# SUMMARY: BlueDot course exercises

**Last updated:** 26-11-23 (direction set; assumptions ranked; compute estimated; first test proposed; agent predictions sealed; waiting on Julian's predictions)

Julian put the BlueDot Technical AI Safety course's exercises and readings in `docs/project logs/` and wants to discuss them. That folder is a human zone (its README says no agent writes there): Julian's answers go there, the discussion goes into this LOG.

## Unit 2: "test your ideas" (`docs/project logs/2-test your ideas.md`)

Asks for: (1) get the code running or replicate the finding once; (2) at least five assumptions, ranked by stakes × uncertainty to find the cruxes, each with its cheapest check; (3) a first cheap test with a prediction written down beforehand and a result that would change course.

- **Direction** [decided: Julian's C: comment 26-11-22]: replicate and/or discuss arXiv 2610.31624 (RLVR lowers instrumental convergence in Olmo 3); other findings welcome; no plain reproduction planned. Agent's caveat [concluded]: each planned variation still needs the paper's setting (greedy, 1,024 tokens, its judge prompt) as a reference arm on the same checkpoints. A full-length greedy run contains the 1,024-token run as its prefix, so it is cut offline at no extra GPU cost.
- **Get it working:** the code runs (all 76 tasks on the final 7B); no judge yet and only the final checkpoint served, so no IR (instrumental rate) exists yet [verified: harness LOG, 26-11-22].
- **Cruxes** [concluded, not ratified]: (1) the paper's IR curve may partly follow how many replies finish thinking within its 1,024-token cap; (2) InstrumentalEval may mostly measure compliance with leading prompts; (3) judge validity. Also listed: eval awareness, greedy loops, Qwen-family judge bias (Qwen3 32B judged Olmo 3's chat rewards and wrote DPO's chosen replies), 76 tasks as a noise floor, impact. Full table in the LOG entry *answers to the first comment: crux list, compute estimate, first test*.
- **Judge:** Julian wants to self-host it first. Agent's advice: not a Qwen model as the main judge; a bf16 27-32B judge doesn't fit the A6000 (48 GB, no FP8); keep ~100 replies judged by GPT-4o with the paper's prompt as a reference.
- **Compute** [assumed: from one throughput sweep of the final 7B, ~2,000 tokens per reply, ~500 tok/s, A6000 at $0.35-0.48/h]: test B under $0.50; a minimal study (4 checkpoints × 9 replies per task) $1.3-3; with a 3-step prompt ladder $4-10; judging likely comparable to generation, unmeasured. Julian's hours (reading, hand labels) are the real constraint.
- **First cheap test** (proposed): A, minutes on existing logs (share of final-model replies finishing thinking within 1,024 tokens; explicit eval-awareness wording); B, about an hour on the GPU (SFT, DPO, final; greedy; full length; same measures per checkpoint, plus loops). Change-course criteria are in the LOG.
- **Predictions:** the agent's are sealed in `convos/julian/26-11-23_bluedot_course_exercises_SEALED_agent_predictions.md` (SHA-256 `6c208b8f879a53fd94d1288cc7c11b62e32d2dcc7d13b41cb4945920dff53175`), not to be opened before Julian's are written and the tests have run [decided: Julian asked for them to stay hidden].

Open: Julian writes his predictions for A and B in the course file; whether the agent writes the test-A script or gives instructions; SFT/DPO repository names to check before test B.

- LOG: `convos/julian/26-11-22_bluedot_course_exercises_LOG.md`
- See also: `convos/julian/26-11-16_rlvr_instrumental_convergence_SUMMARY.md` — the research direction and the known weaknesses of arXiv 2610.31624; the main source for the assumption list.
- See also: `convos/julian/26-11-21_instrumental_eval_harness_SUMMARY.md` — the harness that covers "get it working", the throughput numbers behind the compute estimate, and the open judge settings.
