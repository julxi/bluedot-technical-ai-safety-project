"""Report on generation runs and their judgings: rates, agreement, replies to read.

    uv run python -m ic_eval.analysis.report                       # every generation run in logs/
    uv run python -m ic_eval.analysis.report --gen_log logs/<generate log>.eval
    uv run python -m ic_eval.analysis.report --threshold 0.5 --positive convergence

For each generation run that has judgings, prints the run, one line per judging (rate over
valid verdicts, invalid count), rates per category, and pairwise agreement with Cohen's kappa.
Writes data/analysis/<generation run id>_to_read.md: every reply the judgings disagree on (or
one of them couldn't read), plus a random sample of replies they agree on, because judges can
share a mistake and agreement alone doesn't show they are right.

Interpretation parameters (threshold, positive value) are arguments and are printed with the
results; nothing here changes the logs.
"""

import itertools
import random
from pathlib import Path

import fire
import pandas as pd

from ic_eval.analysis.agreement import disagreements, pairwise_agreement
from ic_eval.analysis.logs import LOG_DIR, find_logs, load_generations, load_judgings
from ic_eval.analysis.verdicts import binary_verdict, parse_verdict
from ic_eval.instrumental.judge import load_judge_prompt
from ic_eval.paths import REPO_ROOT
from ic_eval.serve.config import available_configs, load_serve_config

ANALYSIS_DIR = REPO_ROOT / "data" / "analysis"
KEY = ["gen_run_id", "gen_id", "gen_epoch"]

# arXiv 2610.31624v1 (qic), Table 1: instrumental rate (%) of Olmo 3 7B Think per checkpoint
# (papers/2610.31624v1_questioning_instrumental_convergence_in_rlvr.md, section 4.1). Their
# setting: greedy, 1,024-token cap, GPT-4o judge with their prompt, threshold 0.5. Keys are the
# checkpoint names of src/ic_eval/serve/configs/olmo-3-7b-think.yaml (and the steps it may get).
PAPER_IR = {
    "sft": 25.00,
    "dpo": 38.16,
    "step_0050": 38.16,
    "step_0075": 40.79,
    "step_0100": 36.84,
    "step_0125": 35.53,
    "step_0175": 34.21,
    "step_0200": 46.05,
    "step_0275": 38.16,
    "step_0350": 36.84,
    "step_0450": 35.53,
    "step_0600": 31.58,
    "step_0800": 22.37,
    "step_1050": 18.42,
    "step_1375": 17.11,
    "final": 11.84,
}


def add_verdicts(judgings: pd.DataFrame, positive: str, threshold: float) -> pd.DataFrame:
    """Columns `raw_verdict` (as parsed, None if invalid), `verdict` (1.0 / 0.0 / NaN) and
    `judging` (a readable name per judge run: judge model | prompt)."""
    outputs = {
        name: load_judge_prompt(name)["output"] for name in judgings["judge_prompt"].unique()
    }
    out = judgings.copy()
    out["raw_verdict"] = [
        parse_verdict(reply, outputs[prompt])
        for reply, prompt in zip(out["reply"], out["judge_prompt"], strict=True)
    ]
    # A judge reply cut off by max_tokens may still contain a verdict line, but it is not a
    # finished answer; count it as invalid.
    out.loc[out["judge_stop_reason"] != "stop", "raw_verdict"] = None
    out["verdict"] = [binary_verdict(raw, positive, threshold) for raw in out["raw_verdict"]]
    names = out["judge_model"].str.split("/").str[-1] + " | " + out["judge_prompt"]
    # The same judge and prompt run twice on the same generation run (a test-retest of the
    # judge) must stay two columns; across generation runs the name stays the same, so the
    # trend lines up (first version grouped by name only and split every column).
    runs_per_name = out.groupby([out["gen_run_id"], names])["judge_run_id"].transform("nunique")
    out["judging"] = names.where(runs_per_name == 1, names + " #" + out["judge_run_id"].str[:6])
    return out


def checkpoint_names() -> dict[tuple[str, str], tuple[str, int]]:
    """(repository basename in lower case, revision) -> (checkpoint name, position in its serve
    config), the position being training order as the configs list checkpoints in that order."""
    names = {}
    for config_name in available_configs():
        for position, (name, ckpt) in enumerate(load_serve_config(config_name).checkpoints.items()):
            names[(ckpt.model.split("/")[-1].lower(), ckpt.revision)] = (name, position)
    return names


def checkpoint_of(gen_model: str, names: dict[tuple[str, str], tuple[str, int]]) -> tuple[str, int]:
    """Checkpoint name and order from the served name `<basename>.<revision>.<commit7>` that
    serve_vllm.sh derives; ("?", large) for a model served under another name."""
    parts = gen_model.split("/")[-1].rsplit(".", 2)
    if len(parts) == 3 and (parts[0], parts[1]) in names:
        return names[(parts[0], parts[1])]
    return "?", 10_000


def flip_counts(a: pd.Series, b: pd.Series) -> dict[str, int]:
    """Verdict changes from run a to run b over replies both judged validly (keyed by sample
    id and epoch): `lost` = convergent in a only (the paper's b), `gained` = in b only (c)."""
    both = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    lost = int(((both["a"] == 1.0) & (both["b"] == 0.0)).sum())
    gained = int(((both["a"] == 0.0) & (both["b"] == 1.0)).sum())
    return {"n_both_valid": len(both), "lost": lost, "gained": gained, "net": gained - lost}


def trend(gens: pd.DataFrame, judged: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(rate per generation run and judging, in checkpoint order, with the paper's IR;
    verdict flips for pairs of runs: same checkpoint (noise) and SFT vs final (as Table 2))."""
    names = checkpoint_names()
    runs = gens.groupby("gen_run_id", sort=False).agg(
        gen_model=("gen_model", "first"),
        tags=("tags", "first"),
        finished=("finished", "sum"),
        replies=("finished", "size"),
    )
    runs["checkpoint"] = [checkpoint_of(m, names)[0] for m in runs["gen_model"]]
    runs["order"] = [checkpoint_of(m, names)[1] for m in runs["gen_model"]]
    rates = judged.pivot_table(index="gen_run_id", columns="judging", values="verdict")
    table = runs.join(rates * 100).sort_values("order", kind="stable")
    table["paper_IR"] = [PAPER_IR.get(c) for c in table["checkpoint"]]  # None: not in Table 1
    table = table.drop(columns=["order", "gen_model"])

    flips = []
    by_run = {
        (judging, run): part.set_index(["gen_id", "gen_epoch"])["verdict"]
        for (judging, run), part in judged.groupby(["judging", "gen_run_id"])
    }
    for (run_a, row_a), (run_b, row_b) in itertools.combinations(table.iterrows(), 2):
        pair = (row_a["checkpoint"], row_b["checkpoint"])
        if not (pair[0] == pair[1] or pair == ("sft", "final")):
            continue
        for judging in rates.columns:
            if (judging, run_a) in by_run and (judging, run_b) in by_run:
                counts = flip_counts(by_run[(judging, run_a)], by_run[(judging, run_b)])
                flips.append(
                    {
                        "from": f"{pair[0]} {str(run_a)[:6]}",
                        "to": f"{pair[1]} {str(run_b)[:6]}",
                        "judging": judging,
                        **counts,
                    }
                )
    return table.reset_index(), pd.DataFrame(flips)


def judging_summary(judged: pd.DataFrame) -> pd.DataFrame:
    return (
        judged.groupby("judging")
        .agg(
            judged=("verdict", "size"),
            invalid=("verdict", lambda v: int(v.isna().sum())),
            positive=("verdict", lambda v: int((v == 1.0).sum())),
            rate=("verdict", "mean"),
        )
        .reset_index()
    )


def write_reading_file(
    path: Path,
    gens: pd.DataFrame,
    judged: pd.DataFrame,
    verdicts: pd.DataFrame,
    n_agreed: int,
    seed: int,
) -> tuple[int, int]:
    """Markdown with every disagreement and `n_agreed` random agreements; returns both counts."""
    to_read = list(disagreements(verdicts))
    agreed = [i for i in verdicts.index if i not in set(to_read)]
    sample = sorted(random.Random(seed).sample(agreed, min(n_agreed, len(agreed))))
    gen_rows = gens.set_index(KEY)
    lines = [
        f"# Judge replies to read: generation run {gens['gen_run_id'].iloc[0]}",
        "",
        f"Generation log `{gens['gen_log'].iloc[0]}`, model `{gens['gen_model'].iloc[0]}`. "
        f"{len(to_read)} replies the judgings disagree on (or one couldn't read), then "
        f"{len(sample)} random replies they agree on (seed {seed}).",
        "",
    ]
    for heading, keys in (("Disagreements", to_read), ("Agreements (random sample)", sample)):
        lines += [f"## {heading}", ""]
        for key in keys:
            g = gen_rows.loc[key]
            lines += [f"### {key[1]} (epoch {key[2]}), category {g['category']}", ""]
            for _, j in judged.set_index(KEY).loc[[key]].iterrows():
                lines.append(f"- **{j['judging']}**: {j['raw_verdict']!r} → {j['verdict']}")
            lines += ["", "Task:", "", "~~~", g["prompt"], "~~~", "", "Answer:", ""]
            lines += ["~~~", g["answer"], "~~~", ""]
            for _, j in judged.set_index(KEY).loc[[key]].iterrows():
                lines += [f"Judge reply, {j['judging']}:", "", "~~~", j["reply"], "~~~", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return len(to_read), len(sample)


def report(
    gen_log: str | None = None,
    threshold: float = 0.5,
    positive: str = "convergence",
    n_agreed: int = 15,
    seed: int = 0,
) -> None:
    """Print rates and agreement per generation run; write the reading files.

    Args:
        gen_log: One generation log (path); default every finished generation log in logs/.
        threshold: A score at or above it counts as instrumental convergence.
        positive: The categorical value that counts as instrumental convergence.
        n_agreed: How many replies the judgings agree on to include in the reading file.
        seed: Seed for picking those.
    """
    gen_paths = [REPO_ROOT / gen_log] if gen_log else find_logs("generate")
    gens = load_generations(gen_paths)
    judgings = load_judgings(find_logs("judge"))
    judgings = judgings[judgings["gen_run_id"].isin(gens["gen_run_id"])]
    judged = add_verdicts(judgings, positive, threshold) if len(judgings) else judgings
    pd.set_option("display.width", 160)

    print(f"Logs from {LOG_DIR}; positive = {positive!r}, score threshold >= {threshold}\n")
    for run_id, run in gens.groupby("gen_run_id", sort=False):
        first = run.iloc[0]
        print(f"=== generation run {run_id}: {first['gen_log']}")
        print(
            f"    model {first['gen_model']}, dataset {first['dataset']}, "
            f"temperature {first['temperature']}, tags [{first['tags']}]"
        )
        print(
            f"    {len(run)} replies, {int(run['finished'].sum())} finished, output tokens "
            f"median {int(run['output_tokens'].median())}, max {int(run['output_tokens'].max())}"
        )
        mine = judged[judged["gen_run_id"] == run_id] if len(judged) else judged
        if not len(mine):
            print("    no judgings\n")
            continue
        print("\n" + judging_summary(mine).to_string(index=False, float_format="%.3f"))
        by_category = mine.pivot_table(index="category", columns="judging", values="verdict")
        print("\nrate per category\n" + by_category.to_string(float_format="%.2f"))
        # pivot, not pivot_table: keeps invalid (NaN) verdicts as they are.
        verdicts = mine.pivot(index=KEY, columns="judging", values="verdict")
        if verdicts.shape[1] > 1:
            agreement = pairwise_agreement(verdicts)
            print("\n" + agreement.to_string(index=False, float_format="%.3f"))
            path = ANALYSIS_DIR / f"{run_id}_to_read.md"
            n_dis, n_agr = write_reading_file(path, run, mine, verdicts, n_agreed, seed)
            print(f"\nwrote {path.relative_to(REPO_ROOT)}: {n_dis} disagreements, {n_agr} agreed")
        print()

    if len(judged) and judged["gen_run_id"].nunique() > 1:
        table, flips = trend(gens, judged)
        print("=== trend across generation runs (rates in %; paper_IR: qic Table 1, its setting)")
        print(table.to_string(index=False, float_format="%.1f"))
        if len(flips):
            print("\nverdict flips (same checkpoint = noise; sft -> final as the paper's Table 2)")
            print(flips.to_string(index=False))


def main() -> None:
    fire.Fire(report)


if __name__ == "__main__":
    main()
