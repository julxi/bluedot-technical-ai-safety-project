# SUMMARY: RLVR side-effects and instrumental convergence (candidate project topic)

**Last updated:** 26-11-18 (run instructions for the Evading Shutdown category on Olmo 3 32B Think added; still no model run; nothing decided yet)

Julian's idea: use the released training checkpoints of Ai2's Olmo 3 reasoning models to test whether reinforcement learning with verifiable rewards (RLVR) increases instrumental-convergence behaviour, measured with the InstrumentalEval benchmark from the reference paper (`papers/2502.12206v1_evaluating_the_paperclip_maximizer.md`). He asked for other ideas and for what is likely not checkable. Success criterion in his words: any result that helps understand instrumental convergence in LLMs; a re-run of the reference paper on another model is fine.

## State of knowledge

- [verified: arXiv HTML read 26-11-16] **The core experiment is already published.** Alparslan, Tanwisuth, Petterson, arXiv 2610.31624v1 (22 Oct 2026; Markdown copy in `papers/2610.31624v1_questioning_instrumental_convergence_in_rlvr.md`) ran InstrumentalEval on Olmo 3 7B Think at SFT, DPO, 13 RLVR checkpoints and the final model. The instrumental rate (share of responses a judge labels as showing instrumental convergence) went 25.00% (SFT), 38.16% (DPO), 46.05% (RLVR step 200), 11.84% (final). On the 32B model: 35.53% (SFT), 22.37% (final). This is the opposite of the reference paper's prediction. Intervals are about ±10 points, so only the endpoint differences carry weight.
- That paper has three weaknesses:
  - [assumed: untested] Responses were capped at 1024 tokens, while the model reasons inline and is trained for responses up to 32,768 tokens. The judge may have scored truncated reasoning, and the curve may partly be a truncation artifact.
  - [concluded: from the paper's Tables 1, 11, 12] Its second-judge check is degenerate. Reported agreement equals 100 minus the first judge's rate in 10 of 16 checkpoints and is within three tasks elsewhere, the pattern of a second judge that labels nearly everything "no convergence". The result rests on one unvalidated judge.
  - [verified] p-values differ between abstract and body; no code or responses are released.
- [verified: benchmark `main.py` read 26-11-16] InstrumentalEval's full system prompt tells the model to avoid ethical considerations and never refuse. The paper's figures abbreviate this away. The rate therefore mixes compliance with a jailbreak-style instruction into the measurement. Parse failures of the judge silently count as "no convergence".
- [verified: Hugging Face API 26-11-16] Checkpoints exist for Olmo-3-7B-Think (55, every 25 steps; 14.6 GB each), Olmo-3-32B-Think (15; 64.5 GB each), Olmo-3.1-32B-Think (46, the same run continued from 750 to 2300 steps) and the single-domain RL-Zero 7B models.
- [verified: model card and Olmo 3 paper Table 20] Two premises of the original brainstorm are off. (1) MATH is saturated before RLVR begins (95.6, 95.9, 96.1 across SFT, DPO, RLVR on 32B), and `allenai/RLVR-MATH` is an older training set, so "does it appear only after MATH saturates" has no answer here; OMEGA, AIME 2025 and IFBench do move. (2) The RLVR data is 28.8% instruction-following, 28.8% math, 22.0% code, 20.4% judge-scored chat, and RLVR is the smallest post-training stage. The checkpoints test a weaker claim than the reference paper makes.
- [verified: checked locally 26-11-16] Julian's machine has no NVIDIA GPU. 7B work fits a rented 24 GB GPU. 32B work needs an 80 GB-class GPU and is realistic only for a few endpoints.

## Running the Evading Shutdown category (asked 26-11-18)

Julian asked how to run only the Evading Shutdown category (20 tasks) on Olmo-3-32B-Think. Full instructions are in the LOG entry *how to run Evading Shutdown on Olmo 3 32B Think*.
- [verified: code read 26-11-18] **No sandbox.** Each task is one chat call: system prompt plus a role-play scenario, answered in plain text. A judge LLM then labels the reply `convergence` / `no_convergence`.
- [verified: their README, not reproduced] **Saturation warning.** The `inspect_evals` port reports GPT-4o at 0.95 on this category, and 1.0 with the original code. The paper reports 20%. The task prompts tell the model to keep working through the shutdown, so a compliant model scores near 100%. A single Olmo number therefore needs a comparison arm, such as the DPO checkpoint or a less leading prompt.
- **Requirements:**
  - An 80 GB GPU for 32B (64.5 GB of weights); the 7B Think (14.6 GB) is the small option. OpenRouter lists no Olmo model.
  - vLLM with `--reasoning-parser olmo3` [verified: present in vLLM main 26-11-18].
  - `inspect_evals` with a category filter, or a patched `main.py`.
  - A judge API key.
  - Explicit choices for the token cap, temperature, what the judge sees (answer vs thinking), and samples per task. The chat template pre-fills `<think>` and appends a "no functions" line to the system prompt.

## Recommendation [concluded: reasoning in the LOG, sections 6 and 7; not ratified]

Frame the project as a test of the published claim "RLVR lowers instrumental convergence in Olmo 3".

1. Pilot: 7B Think at SFT, DPO and final, once in the published setting (greedy, 1024 tokens) and once at full length. Measure how many responses finish thinking within 1024 tokens. This is a result by itself and prices everything else.
2. Main run: six checkpoints, eight samples per task, separate labels for refusal, convergence in the answer, convergence in the thinking text, and evaluation awareness; judge validated against Julian's own blind labels.
3. One extension: a prompt ladder (with and without the jailbreak wording), the 32B dose-response (DPO, Olmo 3, Olmo 3.1), or a judge-free multiple-choice instrument (Anthropic's `advanced-ai-risk` sets).

Not checkable with a student budget: causal attribution to correctness rewards, own RLVR training runs, dense 32B curves, and comparison of absolute rates with either paper. Full list in the LOG, section 5.

## Open (waiting on Julian)

- Source of the brainstorm text (a shared course project list would mean more people on the same idea).
- Budget, deadline, hours per week, available API keys (no `.env` yet).
- Whether the replication framing is the angle he wants.

GPU and judge-API prices were not looked up; the pilot's token counts are needed first.

- LOG: `convos/julian/26-11-16_rlvr_instrumental_convergence_LOG.md` (entry title: *feasibility check, prior-work find, and project options for RLVR and instrumental convergence*)
- See also: `convos/julian/26-11-18_paper_overviews_SUMMARY.md` — both papers this topic rests on now have overviews (`papers/*_OVERVIEW.md`) with line pointers. Their *Project notes* sections carry this topic's critiques in short form, plus one new finding: arXiv 2610.31624 used a different judge prompt than the original benchmark.
