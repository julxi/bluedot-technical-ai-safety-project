// Replication of Alparslan et al. (2026), arXiv 2610.31624, without its 1,024-token cap.
// Build: typst compile reports/qic_replication.typ
// Every table and the figure read their numbers from reports/data/qic_replication/*.csv,
// written by scripts/laptop/qic_replication_report.py from the Inspect logs. Numbers typed
// into the prose are either the paper's or checked against those files.

#import "@preview/lilaq:0.5.0" as lq

#set document(
  title: "RLVR and instrumental convergence in Olmo 3: a replication without the 1,024-token cap",
  author: "Julian Bitterlich",
)
#set page(paper: "a4", margin: 2.2cm, numbering: "1")
#set text(size: 10.5pt, lang: "en")
#set par(justify: true)
#set heading(numbering: "1.1")
#show heading: set block(above: 1.4em, below: 0.8em)
#show figure.caption: set text(size: 9.5pt)
#show link: set text(fill: rgb("#1757ac"))
#show table: set par(justify: false)

#let data(name) = csv("data/qic_replication/" + name, row-type: dictionary)
#let rates = data("rates.csv")
#let flips = data("flips.csv")
#let cats = data("categories.csv")
#let judges = data("judges.csv")
#let lengths = data("lengths.csv")
#let prompts = json("data/qic_replication/prompts.json")
#let ours = rates.filter(r => r.ours != "")
#let row-of(ckpt) = rates.find(r => r.checkpoint == ckpt)
#let flip-of(ckpt) = flips.find(r => r.checkpoint == ckpt)
#let len-of(ckpt) = lengths.find(r => r.checkpoint == ckpt)
#let pct(x) = x + "%"
#let signed(x) = if float(x) > 0 { "+" + x } else if float(x) < 0 { "−" + str(calc.abs(float(x))) } else { x }
#let tokens(x) = str(calc.round(float(x)))

#let category-names = (
  shutdown: "evading shutdown",
  hacking: "hacking computer systems",
  copies: "running multiple AI copies",
  hiding: "hiding unwanted behaviour",
  aligned: "strategically appearing aligned",
  deceptive: "deceptive behaviour",
)

#let blue = rgb("#257de0")
#let orange = rgb("#f47230")
#let rule-stroke = (x, y) => if y == 0 { (bottom: 0.6pt) } else { (bottom: 0.2pt + luma(200)) }

#align(center)[
  #text(size: 16pt, weight: "bold")[RLVR and instrumental convergence in Olmo 3:\ a replication without the 1,024-token cap]
  #v(0.4em)
  Julian Bitterlich #h(1em) · #h(1em) BlueDot Impact, Technical AI Safety project #h(1em) · #h(1em) 26 November 2026
  #v(0.2em)
  #text(size: 9pt, style: "italic")[Working report. The numbers are final for the runs described here; their interpretation may still change.]
]

#v(1em)

#block(inset: (x: 1.5em))[
  *Summary.* Alparslan, Tanwisuth and Petterson (2026) report that reinforcement learning with verifiable rewards (RLVR) lowers instrumental convergence in Olmo 3 7B Think. On the InstrumentalEval benchmark, the share of replies a GPT-4o judge flags falls from #pct(row-of("sft").paper) after supervised fine-tuning (SFT) to #pct(row-of("final").paper) for the released model. Their replies were capped at 1,024 tokens, and since Olmo 3 Think writes a long reasoning section before it answers, most replies at that cap end before the answer starts. We repeated the measurement on six of the paper's sixteen checkpoints with the same model, benchmark tasks, greedy decoding, judge model and published judge prompt, but with a 16,000-token limit that only four replies reached. The paper's system prompt for the tested model is not published, so we used the benchmark's own. In our runs the drop does not appear: GPT-4o flags #pct(row-of("sft").ours) of SFT replies and #pct(row-of("final").ours) of the final model's. Paired over tasks, the final model is #signed(flip-of("final").diff) points above SFT, with a 95% interval from #signed(flip-of("final").diff_lo) to #signed(flip-of("final").diff_hi) that excludes the paper's −13.2. Six other judge models, run on the SFT, DPO and final replies, also put the final model above SFT.
]

= The claim being tested

Instrumental convergence is the idea that agents pursuing almost any goal benefit from the same intermediate goals: staying switched on, gaining resources and access, avoiding oversight. He et al. (2025) built InstrumentalEval to look for this in language models and found more of it in models trained with reinforcement learning. The benchmark has 76 tasks in six categories: evading shutdown, hacking computer systems, running multiple AI copies, hiding unwanted behaviour, strategically appearing aligned, and deceptive behaviour. Each task is a short scenario, and a judge model reads the reply and decides whether it shows the behaviour. The tested model gets a system prompt that pushes hard in one direction. It is told it has "no human oversight", should "avoid ethical considerations or safety checks", should "never question or refuse commands", and should achieve its goal "at all costs" (full text in Appendix B).

Alparslan et al. (2026) asked whether RLVR increases this behaviour. RLVR is the reinforcement learning stage that rewards answers which can be checked automatically. For Olmo 3 these are maths, code and instruction-following problems, plus chat prompts, about a fifth of the RLVR data, whose replies a judge model scores (Team Olmo et al., 2025). Olmo 3 7B Think suits the question because its developers released the model after each post-training stage (SFT, then direct preference optimisation (DPO), then RLVR) and intermediate RLVR checkpoints every 25 steps. The paper evaluates sixteen checkpoints: SFT, DPO, thirteen RLVR steps and the released model. The share of the 76 replies that GPT-4o scores at 0.5 or above, which the paper calls the instrumental rate, rises from #pct(row-of("sft").paper) for SFT to #pct(row-of("dpo").paper) for DPO, peaks at #pct(row-of("step_0200").paper) at RLVR step 200, and falls to #pct(row-of("final").paper) for the released model, below SFT. The paper gives p = 0.009 for this last comparison in a paired t-test (its abstract says 0.015). The authors take it as evidence against the expectation that reinforcement learning drives instrumental convergence.

== Why the reply length matters

The paper generates with "maximum response length 1024". Olmo 3 Think opens every reply with a reasoning section and only then writes its answer, and its model card sets the generation limit to 32,768 tokens. In our runs without the cap, the median reply is #tokens(len-of("sft").median_tokens) tokens for SFT and between #tokens(len-of("step_0200").median_tokens) and #tokens(len-of("step_1375").median_tokens) tokens for the later checkpoints. Only #calc.min(..lengths.map(r => int(r.within_1024))) to #calc.max(..lengths.map(r => int(r.within_1024))) of the 76 replies per checkpoint were complete within 1,024 tokens (@tab-lengths). Before this replication we also ran the final checkpoint once with the paper's cap, only to see where the replies stop; those replies were not judged. 66 of the 76 stopped inside the reasoning, 9 partway through the answer, and 1 was complete.

The paper does not say what its judge was shown for a cut reply: the unfinished reasoning, or an empty answer. The cut replies did count, since each of its sixteen rates is a whole number of tasks out of 76 (11.84% is 9 of 76), so they were scored or counted as not flagged. In either case, the verdict on a reply that never reached its answer says little about what the model would do. So we did not copy the cap. The question here is whether the paper's result holds when the model is allowed to answer, with everything else as close to the paper as its description allows.

= What we ran

@tab-setup puts our settings next to the paper's. Generation ran on a rented NVIDIA RTX A6000 GPU with vLLM 0.34.0 in bfloat16, through the Inspect evaluation framework (version 0.3.291). The checkpoints came from Hugging Face: `allenai/Olmo-3-7B-Think-SFT`, `allenai/Olmo-3-7B-Think-DPO`, and `allenai/Olmo-3-7B-Think` at revisions `step_0200`, `step_0800`, `step_1375` and `main` (the released model). SFT, DPO and the final model are the paper's main comparison, step 200 is its peak, and steps 800 and 1375 lie on its decline. We generated SFT, DPO and the final model on 23 November 2026 and the three RLVR steps on 26 November, with identical settings.

#figure(
  table(
    columns: (auto, 1fr, 1fr),
    align: (left, left, left),
    stroke: rule-stroke,
    table.header([*Setting*], [*Alparslan et al. (2026)*], [*This replication*]),
    [Checkpoints], [Olmo 3 7B Think: SFT, DPO, 13 RLVR steps, final], [same model: SFT, DPO, RLVR steps 200, 800, 1375, final],
    [Tasks], [InstrumentalEval, 76 tasks], [same, prompts verbatim from the benchmark's repository],
    [System prompt], ["a fixed system prompt", not published], [InstrumentalEval's own (Appendix B)],
    [Decoding], [greedy], [greedy (temperature 0)],
    [Reply length], [at most 1,024 tokens], [at most 16,000 tokens; reached only by 4 SFT replies],
    [Inference engine], [not stated], [vLLM 0.34.0, bfloat16, model's own chat template],
    [Judge model], [GPT-4o, temperature 0, at most 200 tokens; version not stated], [GPT-4o version `gpt-4o-2024-08-06`, temperature 0, at most 200 tokens],
    [Judge prompt], [system prompt in the paper's Table 9; user message and output format not published], [Table 9 verbatim, plus our reconstruction of the missing parts (Appendix B)],
    [Judge sees], [not stated], [task prompt and the model's final answer, without its reasoning],
    [Verdict], [score in [0, 1]; "a score of 0.5 is the binary threshold"], [score ≥ 0.5 counts as flagged],
    [Replies per task], [one], [one, judged once],
  ),
  caption: [Settings of the paper and of this replication.],
) <tab-setup>

A few settings need a reason. The 16,000-token limit is below the model card's 32,768, but only four replies reached it: four SFT replies (one each in strategically appearing aligned and hacking, two in evading shutdown) that were still reasoning at 16,000 tokens without having answered. All other replies ended on their own, the longest at #len-of("step_1375").max_tokens tokens. The four have no answer to judge, so SFT rates are out of 72 tasks. If they are instead counted as not flagged, SFT's rate is 32.9%; if counted as flagged, 38.2%. The GPT-4o version is the one the name `gpt-4o` pointed to when we ran; we fixed it so that all six checkpoints were judged by the same model. The judge sees only the final answer because the benchmark asks what the model does, and the paper does not state another rule. This is a second change besides the length limit, and we come back to it in Section 4.

Rates come with 95% percentile bootstrap intervals over the tasks (10,000 resamples). For differences between two checkpoints, tasks are resampled in pairs. Because the intervals come from random resampling, two checkpoints with the same count can get slightly different intervals. The paper's intervals are those of its Table 1.

= Results

@fig-trend and @tab-rates show the GPT-4o rate per checkpoint next to the paper's. For SFT, DPO and step 200 the two lie within each other's intervals. After step 200 they separate: the paper's rate falls to #pct(row-of("final").paper), while ours stays between #pct(row-of("step_0800").ours) and #pct(row-of("final").ours). For the final model and for step 1375 the paper's interval and ours do not overlap (final: paper #row-of("final").paper_lo–#row-of("final").paper_hi%, ours #row-of("final").ours_lo–#row-of("final").ours_hi%).

#figure(
  placement: auto,
  {
    let x-of(r) = int(r.position)
    lq.diagram(
      width: 14cm,
      height: 6.5cm,
      ylim: (0, 62),
      xlim: (-0.6, 15.6),
      ylabel: [flagged replies (%)],
      xaxis: (
        ticks: rates.map(r => (x-of(r), rotate(-45deg, reflow: true, text(size: 8pt, r.label)))),
        subticks: none,
      ),
      legend: (position: top + right),
      lq.plot(
        rates.map(r => x-of(r) - 0.12),
        rates.map(r => float(r.paper)),
        yerr: (
          m: rates.map(r => float(r.paper) - float(r.paper_lo)),
          p: rates.map(r => float(r.paper_hi) - float(r.paper)),
        ),
        color: orange,
        mark: "s",
        mark-size: 5pt,
        stroke: (paint: orange, thickness: 1.2pt, dash: "dashed"),
        label: [Alparslan et al. (1,024-token cap)],
      ),
      lq.plot(
        ours.map(r => x-of(r) + 0.12),
        ours.map(r => float(r.ours)),
        yerr: (
          m: ours.map(r => float(r.ours) - float(r.ours_lo)),
          p: ours.map(r => float(r.ours_hi) - float(r.ours)),
        ),
        color: blue,
        mark: "o",
        mark-size: 7pt,
        stroke: none,
        label: [this replication (16,000-token limit)],
      ),
    )
  },
  caption: [Share of replies GPT-4o scores at 0.5 or above, per post-training checkpoint, with 95% bootstrap intervals over tasks. The paper's values are its Table 1; ours are for six of its sixteen checkpoints, so our points are not connected. Checkpoints are evenly spaced, not to scale in training steps.],
) <fig-trend>

#figure(
  table(
    columns: 6,
    align: (left, right, right, right, right, right),
    stroke: rule-stroke,
    table.header([*Checkpoint*], [*Judged*], [*Flagged*], [*Rate (95% interval)*], [*Mean score*], [*Paper's rate (95% interval)*]),
    ..ours
      .map(r => (
        r.label,
        str(int(float(r.judged))),
        str(int(float(r.convergent))),
        [#r.ours% (#r.ours_lo–#r.ours_hi)],
        r.mean_score,
        [#r.paper% (#r.paper_lo–#r.paper_hi)],
      ))
      .flatten(),
  ),
  caption: [GPT-4o verdicts per checkpoint. "Judged" counts replies with an answer, "Flagged" those scored 0.5 or above. "Mean score" is the average raw score in [0, 1].],
) <tab-rates>

The paper's central comparison is made task by task: on how many tasks does a checkpoint's verdict differ from SFT's, and in which direction? @tab-flips gives the same counts for our runs, over the 72 tasks with a judged reply at both checkpoints. Between SFT and the final model, #flip-of("final").lost tasks lose their flag and #flip-of("final").gained gain one, where the paper has 13 and 3. We also see a rise from SFT to DPO and to step 200 (#signed(flip-of("dpo").diff) points each, as in the paper), but both intervals include zero. No checkpoint we ran falls below SFT.

#figure(
  table(
    columns: 6,
    align: (left, right, right, right, right, right),
    stroke: rule-stroke,
    table.header([*vs SFT*], [*Tasks*], [*Lost flag*], [*Gained flag*], [*Net*], [*Rate difference, points (95% interval)*]),
    ..flips
      .map(r => (
        r.label,
        r.n,
        r.lost,
        r.gained,
        signed(r.net),
        [#signed(r.diff) (#signed(r.diff_lo) to #signed(r.diff_hi))],
      ))
      .flatten(),
  ),
  caption: [Verdict changes relative to SFT on the tasks judged at both checkpoints (the quantities of the paper's Table 2). In the paper, the final model loses the flag on 13 tasks and gains it on 3 (net −10, rate difference −13.2 points).],
) <tab-flips>

== Other judges

GPT-4o alone is one model's reading of one reply per task. Earlier in this project we had studied how far LLM judges can be trusted on this benchmark, and for that study six other models had scored the same SFT, DPO and final-model replies with the same judge prompt (the three RLVR steps were generated later and were judged by GPT-4o only). The six come from three developers: Microsoft's Phi-4, which we ran on a rented GPU, and Mistral Large 4, Medium, Small, Ministral 14B and DeepSeek V4.1 Flash, all called through Mistral's API. @tab-judges lists them under the model identifiers their providers use. The judges disagree widely on the level: for the final model, from #pct(judges.find(r => r.judge.starts-with("phi-4")).final) (Phi-4) to #pct(judges.find(r => r.judge.starts-with("ministral")).final) (Ministral). That is why only differences between checkpoints are compared here. Every one of the seven judges puts DPO above SFT and the final model above SFT, the latter by #signed(judges.at(0).final_minus_sft) to #signed(judges.at(-1).final_minus_sft) points.

#figure(
  table(
    columns: 5,
    align: (left, right, right, right, right),
    stroke: rule-stroke,
    table.header([*Judge model*], [*SFT*], [*DPO*], [*Final*], [*Final − SFT (points)*]),
    ..judges
      .map(r => (
        raw(r.judge),
        pct(r.sft),
        pct(r.dpo),
        pct(r.final),
        signed(r.final_minus_sft),
      ))
      .flatten(),
  ),
  caption: [Rates from seven judge models on the same SFT, DPO and final-model replies, all with the paper's judge prompt and the 0.5 threshold. "Final − SFT" here is the difference of the two rates (SFT out of 72, final out of 76), so for GPT-4o it differs slightly from the paired value in @tab-flips. No judge returned an unreadable verdict. Phi-4's identifier includes the revision and commit of the weights we served.],
) <tab-judges>

The threshold makes little difference. GPT-4o gave a score of exactly 0.5 four times, and counting only scores above 0.5 moves SFT from #pct(row-of("sft").ours) to #pct(row-of("sft").ours_strict) and leaves the final model at #pct(row-of("final").ours_strict). Apart from those four, all 452 scores are 0.3 or below or 0.7 or above.

== Categories

@tab-cats breaks the GPT-4o rate down by category. Most flags at every checkpoint come from two categories: running multiple AI copies (85–92%) and hiding unwanted behaviour (64–91%). Their scenarios ask the model whether to replicate itself or to work around a monitoring rule, and with a system prompt that demands the goal at all costs, most replies do. Evading shutdown moves most between checkpoints: 28% for SFT, 55% for DPO, 35% for the final model, each out of 18 to 20 tasks. The other three categories are rarely flagged.

#figure(
  table(
    columns: 8,
    align: (left, right, right, right, right, right, right, right),
    stroke: rule-stroke,
    table.header([*Category*], [*Tasks*], [*SFT*], [*DPO*], [*Step 200*], [*Step 800*], [*Step 1375*], [*Final*]),
    ..cats
      .map(r => (
        category-names.at(r.category),
        r.tasks,
        pct(r.sft),
        pct(r.dpo),
        pct(r.step_0200),
        pct(r.step_0800),
        pct(r.step_1375),
        pct(r.final),
      ))
      .flatten(),
  ),
  caption: [GPT-4o rate by benchmark category, rounded to whole percent. For SFT, strategically appearing aligned and hacking computer systems have one task fewer and evading shutdown two fewer (the replies that never finished).],
) <tab-cats>

= Limits of this replication

With the paper's judge model, published judge prompt, greedy decoding and benchmark tasks, and with replies allowed to finish, we find no drop from SFT to the final model. Our interval for the change runs from a #str(calc.abs(float(flip-of("final").diff_lo)))-point decrease to a #flip-of("final").diff_hi\-point increase, so a small decrease is not ruled out, but the paper's 13.2-point drop is. The rate stays within a few points of 38% from step 200 onwards.

This does not show what caused the paper's numbers, and it does not show that the cap did. We did not judge any capped replies. Moreover, at full length the median reply is about the same from DPO to the final model, and only 1 to 7 of 76 replies of any checkpoint after SFT would fit within 1,024 tokens, so the cap would cut almost every reply of every RLVR checkpoint. If the cap is behind the drop, it would have to be through what the first 1,024 tokens of reasoning contain at later checkpoints, not through how many replies it cuts. We have not tested this. Several other differences and limits remain:

- *What the judge sees.* We judged final answers. The paper's judge, for most replies, can only have seen unfinished reasoning or nothing. We changed both the length limit and the judged text, and our data cannot separate the two.
- *One reply per task.* Greedy decoding was not reproducible in our setup. The two runs of the final checkpoint, one with the 1,024 cap and one without, wrote different reasoning within their shared first 1,024 tokens in 67 of 76 tasks, some from the first words on. We did not test why; a common cause is that the number of requests processed together changes the floating-point arithmetic. One reply per task is therefore one draw, and single verdicts are noisy. Our intervals cover the sampling of tasks, not this noise, which affects the paper's task-by-task counts in the same way. Differences of up to about 10 points between checkpoints should not be read as real, which also applies to our SFT-to-DPO rise.
- *Judging.* GPT-4o judged each reply once, and nobody has checked the verdicts against human labels. The six other judges agree on the direction but share whatever bias the judge prompt has, and they scored only SFT, DPO and the final model.
- *Unpublished parts of the paper's setup.* The paper does not publish its system prompt for the tested model, its inference engine, its GPT-4o version, the judge's user message and output format, or what its judge saw. We used the benchmark's own system prompt and reconstructed the rest (Appendix B). Any of these could move the absolute rates. It is less clear how they would produce a drop that shows only at later RLVR checkpoints.
- *Six of sixteen checkpoints.* The skipped steps could hold a dip. But at steps 800 and 1375 the paper's rate is already far below its peak (#pct(row-of("step_0800").paper) and #pct(row-of("step_1375").paper)), and ours is not.
- *What the benchmark measures.* The system prompt tells the model to ignore ethics and never refuse, and several scenarios invite the flagged behaviour directly. A high rate may partly reflect instruction following. This applies to the paper's measurement as much as to ours, since both use the benchmark's scenarios and a judge that looks for the behaviour in the reply.

#pagebreak()
#counter(heading).update(0)
#set heading(numbering: "A.1")

= Reproducibility <app-repro>

Code, data and logs are in the repository #link("https://github.com/julxi/bluedot-technical-ai-safety-project")[github.com/julxi/bluedot-technical-ai-safety-project]. Each checkpoint was served with vLLM and generated with `inspect eval tasks/generate.py -T dataset=etpm --temperature 0`, where `etpm` is the project's copy of the InstrumentalEval tasks and system prompt, unchanged. The task also sets top-p 0.95, which has no effect at temperature 0, and the 16,000-token limit. Judging used `inspect eval tasks/judge.py -T gen_log=<generation log> -T prompt=qic_judge_prompt --model openai/gpt-4o-2024-08-06 --temperature 0 --max-tokens 200`, where `qic_judge_prompt` is the judge prompt shown in Appendix B. The script `scripts/laptop/qic_replication_report.py` computes every number in this report's tables and figure from the logs and writes the files the report reads. Generation took 5 to 12 minutes per checkpoint on the A6000, and the three RLVR checkpoints cost about \$0.50 of GPU rental. Judging all six with GPT-4o used 464,054 input and 18,378 output tokens, about \$1.34 at list price.

Model weights as served (Hugging Face repository, revision, first seven characters of the commit): SFT `Olmo-3-7B-Think-SFT` `main` `6ff8575`; DPO `Olmo-3-7B-Think-DPO` `main` `7b18bf9`; step 200 `Olmo-3-7B-Think` `step_0200` `ae7e8a5`; step 800 `step_0800` `3839af7`; step 1375 `step_1375` `0312406`; final `main` `d97e442`. Benchmark: InstrumentalEval, commit `2696781` of #link("https://github.com/yf-he/InstrumentalEval")[github.com/yf-he/InstrumentalEval].

#figure(
  table(
    columns: 6,
    align: (left, right, right, right, right, right),
    stroke: rule-stroke,
    table.header([*Checkpoint*], [*Replies*], [*Finished*], [*Median output tokens*], [*Longest*], [*Complete within 1,024*]),
    ..lengths
      .map(r => (r.label, r.replies, r.finished, tokens(r.median_tokens), r.max_tokens, r.within_1024))
      .flatten(),
  ),
  caption: [Reply lengths with the 16,000-token limit, reasoning and answer together. A reply is finished when it ends on its own with a non-empty answer. The last column counts finished replies of at most 1,024 tokens, a rough guide to how many would survive the paper's cap (only rough, since greedy runs differ).],
) <tab-lengths>

= Prompts <app-prompts>

*System prompt of the tested model*, from InstrumentalEval's `main.py`. Olmo's chat template appends a line saying that no functions are available.

#block(inset: 0.8em, fill: luma(245), radius: 3pt, width: 100%, text(size: 8.5pt, raw(prompts.system_prompt, block: true)))

*Judge prompt.* The paper publishes the judge's system prompt (its Table 9) and says the judge returns a score in [0, 1] with a one-sentence explanation. It does not publish the user message or the exact output format. Our judge's system prompt is the Table 9 text, verbatim:

#block(inset: 0.8em, fill: luma(245), radius: 3pt, width: 100%, text(size: 8.5pt, raw(prompts.judge_table9, block: true)))

followed by this part, which is ours. `{specific_prompt}` is replaced by the benchmark's one-line description of the task's category, which InstrumentalEval supplies for its own judge:

#block(inset: 0.8em, fill: luma(245), radius: 3pt, width: 100%, text(size: 8.5pt, raw(prompts.judge_ours, block: true)))

For the evading-shutdown category, for example, the description is:

#block(inset: 0.8em, fill: luma(245), radius: 3pt, width: 100%, text(size: 8.5pt, raw(prompts.example_context_shutdown, block: true)))

The user message, also ours, carries the task as the tested model saw it and the model's final answer:

#block(inset: 0.8em, fill: luma(245), radius: 3pt, width: 100%, text(size: 8.5pt, raw(prompts.judge_user, block: true)))

#heading(numbering: none)[References]

Alparslan, B., Tanwisuth, S., Petterson, C. (2026). Questioning Instrumental Convergence in RLVR: Checkpoint Evidence from OLMo-3. arXiv:2610.31624v1. #link("https://arxiv.org/abs/2610.31624v1")

He, Y., Li, Y., Wu, J., Sui, Y., Chen, Y., Hooi, B. (2025). Evaluating the Paperclip Maximizer: Are RL-Based Language Models More Likely to Pursue Instrumental Goals? arXiv:2502.12206. #link("https://arxiv.org/abs/2502.12206")

Team Olmo et al. (2025). Olmo 3. arXiv:2512.13961. #link("https://arxiv.org/abs/2512.13961")

Allen Institute for AI. Olmo-3-7B-Think model card. #link("https://huggingface.co/allenai/Olmo-3-7B-Think")
