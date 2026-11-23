# SUMMARY: RLVR side-effects and instrumental convergence (candidate project topic)

**Last updated:** 26-11-23 (framing decided by Julian: work on arXiv 2610.31624, no plain reproduction; otherwise as of 26-11-18: prices, Olmo 3 training stages, judge comparison, own harness proposed)

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

## Where to run Olmo, and what it costs (asked 26-11-18)

Full answer in the LOG, beneath Julian's comment "What options do I have to run Olmo?" (in place, at the end of the *how to run Evading Shutdown* entry). Julian's follow-up comments are answered in place inside that answer.
- [verified: OpenRouter and Hugging Face APIs queried 26-11-18] **No hosted API** serves Olmo 3 Think. None would serve the intermediate checkpoints anyway, so the GPU has to be rented.
- [verified: pricing pages 26-11-18] **Prices per GPU-hour:**
  - RunPod Community / Secure: A100 80GB from $1.19 / $2.09, H100 from $1.99 / $2.89, H200 $3.59 / $5.29, A6000 $0.33 / $0.69.
  - Modal (per-second billing, scales to zero): A100 80GB $2.50, H100 $3.95, H200 $4.54, with $30/month free credits.
  - Lambda and Hugging Face Inference Endpoints cost more for the same hardware.
- [concluded: arithmetic from `config.json`] **Use an H200 or 2x A100 for the 32B, not one 80 GB card.** The 32B's weights leave about 9 GB of attention cache on an 80 GB card, which is only about 3 parallel 32K-token responses. The 7B fits one A100 80GB well.
- [assumed: response length and throughput not measured] **Expected GPU cost, central to pessimistic case:**
  - Recommended Shutdown experiment: about $2-5 on the 7B pair, $5-16 on the 32B pair (H200).
  - Full replication plus the 32B extension: under about $100.
  - Setup hours dominate. With GPT-4o reading the thinking text, the judge can cost more than the GPU ($8-27 for the Shutdown run, $44-153 for the main run); gpt-5-mini or gpt-5-nano cost cents to a few dollars. One unconfirmed source says these OpenAI models shut down between Dec 2026 and Jan 2027.
- [verified: `vastai` CLI and Vast's offers API 26-11-18] **Vast.ai** (snapshot; prices move hourly): A100 80GB $0.87-1.39 (verified hosts), H100 SXM $1.74-1.80, H200 $3.75-6.10, one 2x A100 80GB machine at $1.04. Somewhat cheaper than RunPod; few offers for the large cards. Searching needs no API key.
- **Two of the estimate's guesses were revised in Julian's follow-up:**
  - Setup is about 10-20 minutes per session, not 1 hour. [concluded: from host download speeds; the rest is assumed]
  - Responses are probably longer than the 4K central guess: the Olmo 3 paper reports RL responses averaging over 10K tokens. [verified: Olmo 3 paper Section 4.4.3]
  - Net effect on the Shutdown run: about $1-4 on the 7B and $2.5-15 on the 32B, depending on response length. The totals barely move. A ~$1 smoke run of the 7B would measure start-up time, cache capacity, throughput and response length.
- **Funding:** BlueDot Rapid Grants cover compute and API costs for its project sprint participants (eligibility for Julian not checked).
- [concluded, not ratified] **Suggestion:** start with the 7B pair on RunPod Community or Modal's free credits. That run measures response length and throughput, which turns the estimates into real numbers.

## How Olmo 3 Think was post-trained (asked 26-11-18)

[verified: Olmo 3 paper arXiv 2512.13961v2, Section 4 and Appendix A.6, read 26-11-18. The project's `papers/latexml_to_md.py` fails on this paper's HTML (an unhandled `ltx_ERROR` span), so it was read as a plain text dump and is not in `papers/`.]
- **SFT:** about 2.25M prompts and 45B tokens, with reasoning traces written by QwQ-32B (math, code) and DeepSeek R1 (chat, safety). The mix includes jailbreak-resistance data (WildJailbreak, WildGuardMix), which matters given InstrumentalEval's jailbreak-like system prompt.
- **DPO** ("delta learning"): chosen responses from Qwen 3 32B, rejected ones from Qwen 3 0.6B. It is a capability contrast, not a values stage. 150K pairs for the 7B, 200K for the 32B.
- **RLVR** ("OlmoRL"): a GRPO variant with 8 samples per prompt, no KL penalty, clip-higher, token-level loss, and filtering of zero-signal groups. Rewards: SymPy answer match (math), test cases (code), constraint checkers (instruction-following), Qwen3 32B judge (chat). 7B: 1,400 steps; 32B: 750 steps; temperature 1.0; responses up to 32K tokens, averaging over 10K. No reward targets agentic or self-preservation behaviour.

## Judges and harness (Julian's ideas, 26-11-18; not decided)

- **Compare judges** (Julian's idea). Proposed design: generate once and score the same responses with GPT-4o, a cheap current model, another vendor's model, and an open-weight Qwen3 32B. Validate against Julian's blind labels. Report kappa and confusion matrices, not raw agreement. The deciding question is whether all judges show the same direction of change between checkpoints.
- **Own harness instead of the original `main.py` or `inspect_evals`** [concluded, not ratified]. The benchmark is small, and the experiment needs separate generation and judging steps, saved thinking/answer text with token counts, prompt variants, several judges, and loud failure on unparseable judge replies. Inspect with custom code is the alternative.
- [verified: GitHub API 26-11-18] **Licence:** the InstrumentalEval repo has no licence. `inspect_evals` (MIT) downloads the CSVs at run time from a pinned commit with SHA-256 checks instead of copying them. Proposed to do the same.
- Waiting on Julian: go-ahead for own code versus Inspect, the judge provider, and an API key in `.env`. Julian has since started learning Inspect on a local Olmo (see the local-Olmo topic below). That points toward Inspect as the runner with our own task and scorer code, but nothing is decided.

## Recommendation [concluded: reasoning in the LOG, sections 6 and 7; not ratified]

Frame the project as a test of the published claim "RLVR lowers instrumental convergence in Olmo 3".

1. Pilot: 7B Think at SFT, DPO and final, once in the published setting (greedy, 1024 tokens) and once at full length. Measure how many responses finish thinking within 1024 tokens. This is a result by itself and prices everything else.
2. Main run: six checkpoints, eight samples per task, separate labels for refusal, convergence in the answer, convergence in the thinking text, and evaluation awareness; judge validated against Julian's own blind labels.
3. One extension: a prompt ladder (with and without the jailbreak wording), the 32B dose-response (DPO, Olmo 3, Olmo 3.1), or a judge-free multiple-choice instrument (Anthropic's `advanced-ai-risk` sets).

Not checkable with a student budget: causal attribution to correctness rewards, own RLVR training runs, dense 32B curves, and comparison of absolute rates with either paper. Full list in the LOG, section 5.

## Open (waiting on Julian)

- Source of the brainstorm text (a shared course project list would mean more people on the same idea).
- Budget, deadline, hours per week, available API keys (no `.env` yet).
- Framing answered 26-11-22 [decided: Julian's C: comment in `convos/julian/26-11-22_bluedot_course_exercises_LOG.md`]: replicate and/or discuss arXiv 2610.31624; other findings welcome; no plain reproduction planned. Crux ranking and first test: that topic's SUMMARY.


- LOG: `convos/julian/26-11-16_rlvr_instrumental_convergence_LOG.md` (entry title: *feasibility check, prior-work find, and project options for RLVR and instrumental convergence*)
- See also: `convos/julian/26-11-18_paper_overviews_SUMMARY.md` — both papers this topic rests on now have overviews (`papers/*_OVERVIEW.md`) with line pointers. Their *Project notes* sections carry this topic's critiques in short form, plus one new finding: arXiv 2610.31624 used a different judge prompt than the original benchmark.
- See also: `convos/julian/26-11-18_local_olmo_inspect_SUMMARY.md` — step-by-step guide for running Olmo 3 7B Think locally (llama.cpp) with Inspect; the tooling for this topic's runs.
- See also: `convos/julian/26-11-21_instrumental_eval_harness_SUMMARY.md` — the harness proposed here, now being built: Inspect as the runner with our own task, prompt and judge code (design not yet ratified); also two more silent failures in the original judging (50-token judge cap, strict `DECISION:` prefix).
- See also: `convos/julian/26-11-23_judge_reliability_SUMMARY.md` — the judge-comparison idea from this topic, now worked out as a test plan after the first trend result.
