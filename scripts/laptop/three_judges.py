"""Three judges (Medium, DeepSeek, Phi-4): simple combinations and a latent class model.

One-off analysis for convos/julian/26-11-23_judge_reliability_LOG.md (entry *Phi-4 back as
third judge; three-judge combination*). Input: the table `compare_judges.py` pickles, e.g.
`uv run python scripts/laptop/compare_judges.py /tmp/judged.pkl` then
`uv run python scripts/laptop/three_judges.py /tmp/judged.pkl`. Bootstrap seed 0, 1,000 resamples.

Latent class (Dawid-Skene, binary): each reply has an unobserved true label; each judge has a
sensitivity (P(yes | true yes)) and specificity (P(no | true no)), shared across checkpoints;
the true rate (prevalence) is estimated per checkpoint. Judges' errors assumed independent
given the true label. Fitted by EM from the majority vote. 3 checkpoints x 7 response
patterns = 21 free cells vs 3 + 6 = 9 parameters, so the model is identified and its fit
can be checked (G^2 against the saturated model, 12 df).
"""

import sys

import numpy as np
import pandas as pd
from scipy.stats import chi2

j = pd.read_pickle(sys.argv[1])
J = ["mistral-medium-2604", "deepseek-v4-1-flash-1017", "phi-4.main.2db69c1"]
SHORT = {J[0]: "medium", J[1]: "deepseek", J[2]: "phi-4"}
CK = ["sft", "dpo", "final"]
rng = np.random.default_rng(0)


def fit_lc(X: np.ndarray, g: np.ndarray, iters: int = 2000):
    """X: n x 3 binary verdicts, g: checkpoint index per row.

    Returns prevalence per checkpoint, sensitivity and specificity per judge, posterior, and
    the model probability of each row's response pattern."""
    post = (X.mean(axis=1) > 0.5).astype(float) * 0.9 + 0.05
    for _ in range(iters):
        prev = np.array([post[g == k].mean() for k in range(3)])
        se = (post[:, None] * X).sum(0) / post.sum()
        sp = ((1 - post)[:, None] * (1 - X)).sum(0) / (1 - post).sum()
        l1 = prev[g] * np.prod(np.where(X == 1, se, 1 - se), axis=1)
        l0 = (1 - prev[g]) * np.prod(np.where(X == 1, 1 - sp, sp), axis=1)
        new = l1 / (l1 + l0)
        if np.max(np.abs(new - post)) < 1e-10:
            post = new
            break
        post = new
    assert np.all(se + sp > 1), "label switching: a judge worse than chance"
    return prev, se, sp, post, l1 + l0


def g2(X, g, loglik_cells):
    # G^2 of the fitted model vs the saturated one (observed pattern frequencies per checkpoint).
    obs = pd.DataFrame({"g": g, "p": [tuple(r) for r in X.astype(int)]})
    counts = obs.value_counts().to_dict()
    n_g = obs["g"].value_counts().to_dict()
    total = 0.0
    for (gk, pat), c in counts.items():
        # expected probability of this pattern in this checkpoint under the model
        row = np.where((g == gk) & np.all(X.astype(int) == np.array(pat), axis=1))[0][0]
        p_model = loglik_cells[row]
        total += 2 * c * np.log((c / n_g[gk]) / p_model)
    return total


for prompt in ["qic_judge_prompt #1", "etpm_judge_prompt"]:
    cols = [f"{x} | {prompt}" for x in J]
    V = (
        j[j["judging"].isin(cols)]
        .pivot_table(index=["checkpoint", "gen_id"], columns="judge", values="verdict")[J]
        .dropna()
    )
    X = V.to_numpy()
    g = np.array([CK.index(c) for c in V.index.get_level_values(0)])
    tasks = V.index.get_level_values(1).to_numpy()
    print(f"=== {prompt}: n = {len(V)}, unanimous {int((X.std(axis=1) == 0).sum())}")
    prev, se, sp, post, cell = fit_lc(X, g)
    G = g2(X, g, cell)
    print(f"  latent class fit: G^2 = {G:.1f}, df 12, p = {chi2.sf(G, 12):.3f}")
    for k, jd in enumerate(J):
        print(
            f"  {SHORT[jd]:9s} sensitivity {se[k]:.2f}  specificity {sp[k]:.2f}  rate "
            + " / ".join(f"{100 * X[g == c, k].mean():.1f}" for c in range(3))
        )

    def summaries(Xs, gs):
        out = {}
        for name, per in {
            "mean of 3 verdicts": Xs.mean(axis=1),
            "majority (2 of 3)": (Xs.sum(axis=1) >= 2).astype(float),
        }.items():
            r = np.array([per[gs == c].mean() for c in range(3)]) * 100
            out[name] = r
        p, *_ = fit_lc(Xs, gs)
        out["latent class prevalence"] = p * 100
        return out

    point = summaries(X, g)
    boots = {k: [] for k in point}
    uniq = np.unique(tasks)
    for _ in range(1000):
        pick = rng.choice(uniq, len(uniq))
        idx = np.concatenate([np.where(tasks == t)[0] for t in pick])
        for k, r in summaries(X[idx], g[idx]).items():
            boots[k].append((r[1] - r[0], r[2] - r[0]))
    for k, r in point.items():
        b = np.array(boots[k])
        c1 = np.percentile(b[:, 0], [2.5, 97.5])
        c2 = np.percentile(b[:, 1], [2.5, 97.5])
        print(
            f"  {k:24s} SFT {r[0]:5.1f} DPO {r[1]:5.1f} final {r[2]:5.1f} | DPO-SFT "
            f"{r[1] - r[0]:+5.1f} [{c1[0]:+5.1f},{c1[1]:+5.1f}] | final-SFT {r[2] - r[0]:+5.1f} "
            f"[{c2[0]:+5.1f},{c2[1]:+5.1f}]"
        )
    print()
