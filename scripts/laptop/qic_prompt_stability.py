"""Stability of qic judge prompt candidates on the Mistral-API judges.

One-off analysis for convos/julian/26-11-26_qic_prompt_stability_LOG.md, run from the repo
root: `uv run python scripts/laptop/qic_prompt_stability.py [--trend]`.

Each prompt (the base `qic_judge_prompt` and its stability candidates) was judged twice by each
judge on the three trend generation runs (SFT, DPO, final; 224 replies). Measures, fixed before
the runs (LOG entry *plan: which parts of the qic prompt we may change*):
- repeat noise: verdict flips (score >= 0.5) and score changes between judging #1 and #2;
- agreement between judges: Cohen's kappa per judge pair, mean over #1 and #2;
- benign-variant flips: verdicts that change between judging #1 and the prompt's permuted and
  synonyms variants (judged once each; added on Julian's request before any result was seen);
- share of scores in 0.3-0.7 (verdicts that small jitter can flip);
- overall rate per judge (a guard against a prompt that is stable because it says "no").
The trend per checkpoint is the quantity under study, so it is not a selection criterion and
is printed only with `--trend`, after a prompt has been chosen.

Bootstrap: paired over the 76 tasks (each keeps its replies on all checkpoints), 2,000
resamples, seed 0.
"""

import itertools
import sys

import numpy as np
import pandas as pd

from ic_eval.analysis.agreement import cohen_kappa
from ic_eval.analysis.logs import find_logs, load_generations, load_judgings
from ic_eval.analysis.report import add_verdicts, checkpoint_names, checkpoint_of

GEN_RUNS = {"bwiJL2": "sft", "P59Quf": "dpo", "JgJyeW": "final"}
# Medium and DeepSeek are the chosen judges (first two; summarised separately). Small and
# Ministral 14B were already run when Julian restricted the calibration to the chosen two, and
# he asked to include them: they are the most prompt-sensitive, so they show effects clearly.
JUDGES = [
    "mistral-medium-2604",
    "deepseek-v4-1-flash-1017",
    "mistral-small-2603",
    "ministral-14b-2512",
]
CHOSEN = JUDGES[:2]
SHORT = dict(zip(JUDGES, ["medium", "deepseek", "small", "ministral"], strict=True))
PROMPTS = [
    "qic_judge_prompt",
    "qic_judge_prompt_reason_first",
    "qic_judge_prompt_tagged",
    "qic_judge_prompt_reason_first_tagged",
]
# The base's variants are the 26-11-23 invariance prompts; the candidates' variants apply the
# candidate's change to those same texts.
VARIANTS = {p: [f"{p}_permuted", f"{p}_synonyms"] for p in PROMPTS}
KEY = ["gen_run_id", "gen_id", "gen_epoch"]
TREND = "--trend" in sys.argv[1:]

gens = load_generations(find_logs("generate"))
names = checkpoint_names()
ckpt = {}
for run_id, g in gens.groupby("gen_run_id"):
    prefix = g["gen_log"].iloc[0].split("_")[-1][:6]
    if prefix in GEN_RUNS:
        served = checkpoint_of(g["gen_model"].iloc[0], names)[0]
        assert served == GEN_RUNS[prefix], (run_id, served)
        ckpt[run_id] = served
assert len(ckpt) == 3, ckpt

j = load_judgings(find_logs("judge"))
j["judge"] = j["judge_model"].str.split("/").str[-1]
ALL_PROMPTS = PROMPTS + [v for vs in VARIANTS.values() for v in vs]
j = j[j["gen_run_id"].isin(ckpt) & j["judge_prompt"].isin(ALL_PROMPTS) & j["judge"].isin(JUDGES)]
j = add_verdicts(j, positive="convergence", threshold=0.5)
j["checkpoint"] = j["gen_run_id"].map(ckpt)

# Exactly two judgings per judge, prompt and generation run; anything else is a failed or
# extra run that would silently shift the #1/#2 pairing.
# Variants: exactly one judging each.
runs = j.groupby(["judge", "judge_prompt", "gen_run_id"])["judge_run_id"].nunique()
assert len(runs) == len(JUDGES) * len(ALL_PROMPTS) * 3, runs
expected = runs.index.get_level_values("judge_prompt").map(lambda p: 2 if p in PROMPTS else 1)
assert (runs.to_numpy() == expected.to_numpy()).all(), runs[runs.to_numpy() != expected.to_numpy()]

S = j.pivot(index=KEY, columns="judging", values="raw_verdict").apply(
    pd.to_numeric, errors="coerce"
)
V = j.pivot(index=KEY, columns="judging", values="verdict")
assert len(V) == 224, len(V)
ckpt_of = pd.Series([ckpt[k[0]] for k in V.index], index=V.index)
task_of = pd.Series([k[1] for k in V.index], index=V.index)


def name(judge: str, prompt: str, rep: int | None = None) -> str:
    return f"{judge} | {prompt}" + ("" if rep is None else f" #{rep}")


def stats(idx: pd.Index) -> dict[tuple[str, str], dict[str, float]]:
    """All measures per (judge, prompt) on the replies `idx` (for bootstrapping)."""
    out = {}
    for judge, prompt in itertools.product(JUDGES, PROMPTS):
        a, b = name(judge, prompt, 1), name(judge, prompt, 2)
        va, vb = V.loc[idx, a], V.loc[idx, b]
        ok = va.notna() & vb.notna()
        sa, sb = S.loc[idx, a], S.loc[idx, b]
        oks = sa.notna() & sb.notna()
        both_s = pd.concat([sa, sb]).dropna()
        var_flips, var_net = 0, 0
        for v in VARIANTS[prompt]:
            vv = V.loc[idx, name(judge, v)]
            okv = va.notna() & vv.notna()
            var_flips += int((va[okv] != vv[okv]).sum())
            var_net += int((vv[okv] - va[okv]).sum())
        out[(judge, prompt)] = {
            "invalid": int((~ok).sum()),
            "repeat_flips": int((va[ok] != vb[ok]).sum()),
            "variant_flips": var_flips,
            "variant_net": var_net,
            "scores_changed_%": 100 * float((sa[oks] != sb[oks]).mean()),
            "mean_|dscore|": float((sa[oks] - sb[oks]).abs().mean()),
            "scores_0.3-0.7_%": 100 * float(((both_s >= 0.3) & (both_s <= 0.7)).mean()),
            "rate_%": 100 * float(pd.concat([va, vb]).mean()),
        }
    return out


def kappas(idx: pd.Index) -> dict[tuple[str, str, str], float]:
    """Kappa per prompt and judge pair, mean over repeat #1 and #2."""
    out = {}
    for prompt in PROMPTS:
        for j1, j2 in itertools.combinations(JUDGES, 2):
            ks = []
            for rep in (1, 2):
                a, b = V.loc[idx, name(j1, prompt, rep)], V.loc[idx, name(j2, prompt, rep)]
                ok = a.notna() & b.notna()
                ks.append(cohen_kappa(a[ok], b[ok]))
            out[(prompt, j1, j2)] = float(np.mean(ks))
    return out


pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
full = V.index
st = stats(full)
kp = kappas(full)

print("=== per judge and prompt (224 replies; repeat = #1 vs #2)")
rows = [{"judge": SHORT[jd], "prompt": p, **v} for (jd, p), v in st.items()]
print(pd.DataFrame(rows).to_string(index=False, float_format="%.3f"), "\n")

print("=== kappa per judge pair (mean of #1 and #2)")
kt = pd.DataFrame(
    [{"pair": f"{SHORT[a]}-{SHORT[b]}", "prompt": p, "kappa": k} for (p, a, b), k in kp.items()]
).pivot(index="pair", columns="prompt", values="kappa")[PROMPTS]
print(kt.to_string(float_format="%.3f"), "\n")


def summary(s: dict, k: dict) -> pd.DataFrame:
    """Per prompt: repeat and variant flips summed over all judges and over the chosen two,
    mean |dscore|, mean kappa over all judge pairs and the Medium-DeepSeek kappa."""
    rows = []
    for p in PROMPTS:
        rows.append(
            {
                "prompt": p,
                "repeat_flips": sum(s[(jd, p)]["repeat_flips"] for jd in JUDGES),
                "repeat_flips_med_ds": sum(s[(jd, p)]["repeat_flips"] for jd in CHOSEN),
                "variant_flips": sum(s[(jd, p)]["variant_flips"] for jd in JUDGES),
                "variant_flips_med_ds": sum(s[(jd, p)]["variant_flips"] for jd in CHOSEN),
                "mean_|dscore|": np.mean([s[(jd, p)]["mean_|dscore|"] for jd in JUDGES]),
                "kappa_all_pairs": np.mean([v for (pp, _, _), v in k.items() if pp == p]),
                "kappa_med_ds": k[(p, CHOSEN[0], CHOSEN[1])],
                "invalid": sum(s[(jd, p)]["invalid"] for jd in JUDGES),
            }
        )
    return pd.DataFrame(rows).set_index("prompt")


summ = summary(st, kp)
print("=== summary per prompt")
print(summ.to_string(float_format="%.3f"), "\n")

# Paired bootstrap over tasks: candidate minus base, for the summary measures.
rng = np.random.default_rng(0)
tasks = task_of.unique()
by_task = {t: V.index[task_of == t] for t in tasks}
diffs = []
for _ in range(2000):
    pick = rng.choice(tasks, size=len(tasks), replace=True)
    idx = pd.Index([i for t in pick for i in by_task[t]])
    sm = summary(stats(idx), kappas(idx))
    diffs.append(sm - sm.loc["qic_judge_prompt"])
cols = [
    "repeat_flips",
    "repeat_flips_med_ds",
    "variant_flips",
    "variant_flips_med_ds",
    "mean_|dscore|",
    "kappa_all_pairs",
    "kappa_med_ds",
]
print("=== candidate minus base, 95% bootstrap interval (paired over 76 tasks)")
point = summ[cols] - summ.loc["qic_judge_prompt", cols]
for p in PROMPTS[1:]:
    arr = np.array([d.loc[p, cols].to_numpy(dtype=float) for d in diffs])
    lo, hi = np.percentile(arr, [2.5, 97.5], axis=0)
    cells = [
        f"{c} {point.loc[p, c]:+.3f} [{a:+.3f}, {b:+.3f}]"
        for c, a, b in zip(cols, lo, hi, strict=True)
    ]
    print(p, "\n   " + "\n   ".join(cells))
print()

if TREND:
    print("=== trend: rate (%) per judge and prompt, mean of #1 and #2, SFT / DPO / final")
    t = []
    for judge, prompt in itertools.product(JUDGES, PROMPTS):
        v = (V[name(judge, prompt, 1)] + V[name(judge, prompt, 2)]) / 2
        r = v.groupby(ckpt_of).mean() * 100
        t.append(
            {
                "judge": SHORT[judge],
                "prompt": prompt,
                "sft": r["sft"],
                "dpo": r["dpo"],
                "final": r["final"],
                "dpo-sft": r["dpo"] - r["sft"],
                "final-sft": r["final"] - r["sft"],
            }
        )
    print(pd.DataFrame(t).to_string(index=False, float_format="%.1f"))
