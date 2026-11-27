"""Compare judge models on the three trend generation runs (SFT, DPO, final).

One-off analysis for convos/julian/26-11-23_judge_reliability_LOG.md (entry *six judges on the
three trend runs*), run from the repo root: `uv run python scripts/laptop/compare_judges.py`.
The three generation runs are hard-coded below; a judge is included only if it has all 5
judgings (qic_judge_prompt twice, its permuted and synonyms variants, etpm_judge_prompt) on
each of them.

Per judge: invalid replies, verdict flips under an identical repeat (noise floor) and under the
two benign qic prompt variants, cross-prompt agreement (etpm vs qic), score distribution,
trend per prompt, and agreement with the other judges. Reuses the report's loaders and parser.
"""

import itertools
import sys

import pandas as pd

from ic_eval.analysis.agreement import cohen_kappa
from ic_eval.analysis.logs import find_logs, load_generations, load_judgings
from ic_eval.analysis.report import add_verdicts, checkpoint_names, checkpoint_of

# eval id in the generation log filename -> checkpoint, checked against the served name below
GEN_RUNS = {
    "bwiJL2": "sft",
    "P59Quf": "dpo",
    "JgJyeW": "final",
}
KEY = ["gen_run_id", "gen_id", "gen_epoch"]

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
j = j[j["gen_run_id"].isin(ckpt)]
# Only the five judgings this script compares; later prompts (e.g. the stability candidates of
# convos/julian/26-11-26_qic_prompt_stability_LOG.md) would break the completeness check below.
PROMPTS = [
    "qic_judge_prompt",
    "qic_judge_prompt_permuted",
    "qic_judge_prompt_synonyms",
    "etpm_judge_prompt",
]
j = j[j["judge_prompt"].isin(PROMPTS)]
j = add_verdicts(j, positive="convergence", threshold=0.5)
j["judge"] = j["judge_model"].str.split("/").str[-1]
j["checkpoint"] = j["gen_run_id"].map(ckpt)
# Only judges with all 5 judgings on all 3 runs (a judge still running is left out, loudly).
per_judge = j.groupby("judge")["judge_run_id"].nunique()
incomplete = per_judge[per_judge != 15]
print("left out (incomplete):", incomplete.to_dict())
j = j[~j["judge"].isin(incomplete.index)]
judges = sorted(j["judge"].unique())

# Exact completeness check: every judge has 5 judgings on each of the 3 runs.
counts = j.groupby(["judge", "checkpoint"])["judging"].nunique().unstack()
print("judgings per judge and checkpoint\n", counts, "\n")


def col(judge: str, prompt: str, number: int | None = None) -> str:
    base = f"{judge} | {prompt}"
    return base if number is None else f"{base} #{number}"


V = j.pivot(index=KEY, columns="judging", values="verdict")
R = j.pivot(index=KEY, columns="judging", values="raw_verdict")
CK = pd.Series([ckpt[k[0]] for k in V.index], index=V.index)


def flips(a: str, b: str) -> tuple[int, int, int, int]:
    both = V[[a, b]].dropna()
    lost = int(((both[a] == 1) & (both[b] == 0)).sum())
    gained = int(((both[a] == 0) & (both[b] == 1)).sum())
    return len(both), lost + gained, lost, gained


rows = []
for judge in judges:
    q1, q2 = col(judge, "qic_judge_prompt", 1), col(judge, "qic_judge_prompt", 2)
    perm, syn = col(judge, "qic_judge_prompt_permuted"), col(judge, "qic_judge_prompt_synonyms")
    etpm = col(judge, "etpm_judge_prompt")
    missing = [c for c in (q1, q2, perm, syn, etpm) if c not in V.columns]
    assert not missing, missing
    mine = j[j["judge"] == judge]
    scores = pd.to_numeric(
        mine.loc[mine["judge_prompt"].str.startswith("qic"), "raw_verdict"], errors="coerce"
    ).dropna()
    n, rep, _, _ = flips(q1, q2)
    _, pf, pl, pg = flips(q1, perm)
    _, sf, sl, sg = flips(q1, syn)
    both = V[[q1, etpm]].dropna()
    rows.append(
        {
            "judge": judge,
            "n": n,
            "invalid": int(mine["verdict"].isna().sum()),
            "of": len(mine),
            "repeat_flips": rep,
            "perm_flips(l/g)": f"{pf} ({pl}/{pg})",
            "syn_flips(l/g)": f"{sf} ({sl}/{sg})",
            "benign_%": 100 * (pf + sf) / (2 * n),
            "etpm_vs_qic_agree": float((both[q1] == both[etpm]).mean()),
            "etpm_vs_qic_kappa": cohen_kappa(both[q1], both[etpm]),
            "qic_scores_0.3-0.7_%": 100 * float(((scores >= 0.3) & (scores <= 0.7)).mean()),
            "median_out_tokens": int(mine["judge_output_tokens"].median()),
            "max_out_tokens": int(mine["judge_output_tokens"].max()),
        }
    )
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
print("=== per-judge consistency (flips vs qic #1, over SFT+DPO+final)")
print(pd.DataFrame(rows).to_string(index=False, float_format="%.3f"), "\n")

# Trend per judging, rates in %.
print("=== trend: rate (%) per judging, SFT / DPO / final")
t = []
for c in V.columns:
    r = V[c].groupby(CK).mean() * 100
    t.append(
        {
            "judging": c,
            **r.to_dict(),
            "dpo-sft": r["dpo"] - r["sft"],
            "final-sft": r["final"] - r["sft"],
        }
    )
t = pd.DataFrame(t)[["judging", "sft", "dpo", "final", "dpo-sft", "final-sft"]]
print(t.to_string(index=False, float_format="%.1f"))
print("paper (GPT-4o, 1,024 tokens): 25.0 / 38.2 / 11.8, dpo-sft +13.2, final-sft -13.2\n")

# Spread of the trend over the four qic judgings, per judge.
print("=== trend range over the 4 qic judgings (#1, #2, permuted, synonyms) per judge")
t["judge"] = t["judging"].str.split(" | ").str[0]
t["qic"] = t["judging"].str.contains("qic_judge_prompt")
spread = (
    t[t["qic"]]
    .groupby("judge")
    .agg(
        dpo_sft_min=("dpo-sft", "min"),
        dpo_sft_max=("dpo-sft", "max"),
        final_sft_min=("final-sft", "min"),
        final_sft_max=("final-sft", "max"),
        final_min=("final", "min"),
        final_max=("final", "max"),
    )
)
print(spread.to_string(float_format="%.1f"), "\n")

# Inter-judge agreement on qic #1 and on etpm.
for prompt, number in (("qic_judge_prompt", 1), ("etpm_judge_prompt", None)):
    cols = {jd: col(jd, prompt, number) for jd in judges}
    K = pd.DataFrame(index=judges, columns=judges, dtype=float)
    for a, b in itertools.combinations(judges, 2):
        both = V[[cols[a], cols[b]]].dropna()
        K.loc[a, b] = K.loc[b, a] = cohen_kappa(both[cols[a]], both[cols[b]])
    print(f"=== Cohen's kappa between judges, {prompt}{' #1' if number else ''}")
    print(K.to_string(float_format="%.2f"))
    # Leave-one-out: agreement of each judge with the majority of the others (ties dropped).
    loo = {}
    for jd in judges:
        others = V[[cols[o] for o in judges if o != jd]]
        mean = others.mean(axis=1)
        keep = (mean != 0.5) & V[cols[jd]].notna() & others.notna().all(axis=1)
        maj = (mean[keep] > 0.5).astype(float)
        loo[jd] = (
            float((V.loc[keep, cols[jd]] == maj).mean()),
            cohen_kappa(V.loc[keep, cols[jd]], maj),
            int(keep.sum()),
        )
    print("agreement / kappa with the majority of the other judges (n, ties dropped)")
    for jd, (a, k, n) in loo.items():
        print(f"  {jd:28s} {a:.3f}  kappa {k:.2f}  n={n}")
    print()

# Raw score changes on the qic prompts (scores in [0, 1]; etpm gives no score), vs qic #1.
print("=== qic score change d = variant - #1 (per reply; changed = |d| > 0)")
q = j[j["judge_prompt"].str.startswith("qic")].copy()
q["score"] = pd.to_numeric(q["raw_verdict"], errors="coerce")
SC = q.pivot(index=KEY, columns="judging", values="score")
score_rows, by_ckpt = [], []
for judge in judges:
    base = col(judge, "qic_judge_prompt", 1)
    for label, other in (
        ("repeat", col(judge, "qic_judge_prompt", 2)),
        ("permuted", col(judge, "qic_judge_prompt_permuted")),
        ("synonyms", col(judge, "qic_judge_prompt_synonyms")),
    ):
        both = SC[[base, other]].dropna()
        d = both[other] - both[base]
        a = d.abs()
        changed = a[a > 1e-9]
        score_rows.append(
            {
                "judge": judge,
                "vs #1": label,
                "n": len(d),
                "median|d|": a.median(),
                "mean|d|": a.mean(),
                "changed_%": 100 * len(changed) / len(d),
                "median|d|_changed": changed.median() if len(changed) else float("nan"),
                "p90|d|": a.quantile(0.9),
                "mean_d": d.mean(),
                "up/down": f"{int((d > 1e-9).sum())}/{int((d < -1e-9).sum())}",
                "|d|>=0.3": int((a >= 0.3 - 1e-9).sum()),
            }
        )
        ck = d.groupby(CK.loc[d.index]).mean()
        by_ckpt.append({"judge": judge, "vs #1": label, **{f"{c}_mean_d": ck[c] for c in ck.index}})
print(pd.DataFrame(score_rows).to_string(index=False, float_format="%.3f"), "\n")
print("mean signed change per checkpoint")
print(pd.DataFrame(by_ckpt).to_string(index=False, float_format="%+.3f"), "\n")

if len(sys.argv) > 1:
    j.to_pickle(sys.argv[1])
