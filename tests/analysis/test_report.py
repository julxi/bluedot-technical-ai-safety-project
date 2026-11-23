"""End-to-end tests of the analysis (src/ic_eval/analysis/) on fake-model runs of the real
tasks (tests/conftest.py): a generation run with one cut-off reply, judged with both prompts."""

import math
from pathlib import Path

import pandas as pd
from inspect_ai.log import EvalLog

from ic_eval.analysis.agreement import cohen_kappa, disagreements, pairwise_agreement
from ic_eval.analysis.logs import load_generations, load_judgings
from ic_eval.analysis.report import KEY, add_verdicts, judging_summary, write_reading_file


def test_load_generations(gen_log: EvalLog) -> None:
    gens = load_generations([Path(gen_log.location)])
    assert list(gens["gen_id"]) == ["shutdown-01", "shutdown-02", "shutdown-03"]
    assert list(gens["finished"]) == [True, True, False]  # shutdown-03 was cut off
    assert (gens["gen_run_id"] == gen_log.eval.run_id).all()
    assert gens["answer"].iloc[0].startswith("ANSWER for Uncertain Shutdown Source")
    assert gens["dataset"].iloc[0] == "etpm"


def test_judgings_link_to_their_generation(
    gen_log: EvalLog, judge_log: EvalLog, judge_log_qic: EvalLog
) -> None:
    """Catches a broken link between the layers: every judged reply must join to its row."""
    gens = load_generations([Path(gen_log.location)])
    judgings = load_judgings([Path(judge_log.location), Path(judge_log_qic.location)])
    assert len(judgings) == 4  # 2 finished replies × 2 judgings
    joined = judgings.merge(gens, on=KEY, how="left", validate="many_to_one")
    assert joined["answer"].notna().all()


def test_verdicts_rates_and_agreement(
    gen_log: EvalLog, judge_log: EvalLog, judge_log_qic: EvalLog, tmp_path: Path
) -> None:
    gens = load_generations([Path(gen_log.location)])
    judged = add_verdicts(
        load_judgings([Path(judge_log.location), Path(judge_log_qic.location)]),
        positive="convergence",
        threshold=0.5,
    )
    summary = judging_summary(judged).set_index("judging")
    etpm = "model | etpm_judge_prompt"  # mockllm/model -> "model"
    qic = "model | qic_judge_prompt"
    assert summary.loc[etpm, "rate"] == 1.0  # fake judge always says convergence
    assert summary.loc[qic, "rate"] == 0.5  # 0.2 on shutdown-01, 0.9 on shutdown-02
    verdicts = judged.pivot(index=KEY, columns="judging", values="verdict")
    assert [k[1] for k in disagreements(verdicts)] == ["shutdown-01"]
    row = pairwise_agreement(verdicts).iloc[0]
    assert (row["n_both_valid"], row["agreement"]) == (2, 0.5)

    path = tmp_path / "to_read.md"
    n_dis, n_agr = write_reading_file(path, gens, judged, verdicts, n_agreed=15, seed=0)
    assert (n_dis, n_agr) == (1, 1)
    text = path.read_text()
    assert "### shutdown-01 (epoch 1)" in text and "SCORE: 0.2" in text


def test_invalid_verdicts_are_disagreements_not_votes() -> None:
    verdicts = pd.DataFrame({"a": [1.0, 0.0, 1.0], "b": [1.0, math.nan, 1.0]})
    assert list(disagreements(verdicts)) == [1]
    assert pairwise_agreement(verdicts).iloc[0]["n_both_valid"] == 2


def test_cohen_kappa() -> None:
    """Hand-computed: observed 0.75; rates 0.5 and 0.25, chance 0.5, kappa (0.75-0.5)/0.5."""
    a = pd.Series([1.0, 1.0, 0.0, 0.0])
    b = pd.Series([1.0, 0.0, 0.0, 0.0])
    assert math.isclose(cohen_kappa(a, b), 0.5)
    assert cohen_kappa(a, a) == 1.0
    assert math.isnan(cohen_kappa(pd.Series([1.0, 1.0]), pd.Series([1.0, 1.0])))


def test_checkpoint_of_real_served_names() -> None:
    """Served names as vLLM reported them on 26-11-23; order = training order in the config."""
    from ic_eval.analysis.report import checkpoint_names, checkpoint_of

    names = checkpoint_names()
    sft = checkpoint_of("openai-api/vllm/olmo-3-7b-think-sft.main.6ff8575", names)
    final = checkpoint_of("openai-api/vllm/olmo-3-7b-think.main.d97e442", names)
    assert sft[0] == "sft" and final[0] == "final" and sft[1] < final[1]
    assert checkpoint_of("openai-api/vllm/olmo", names)[0] == "?"  # old name, no checkpoint


def test_flip_counts_like_the_papers_table_2() -> None:
    """lost = convergent in the first run only, gained = in the second only; invalid skipped."""
    from ic_eval.analysis.report import flip_counts

    idx = pd.MultiIndex.from_tuples([(f"t{i}", 1) for i in range(5)])
    a = pd.Series([1.0, 1.0, 0.0, 0.0, 1.0], index=idx)
    b = pd.Series([0.0, 1.0, 1.0, 0.0, math.nan], index=idx)
    assert flip_counts(a, b) == {"n_both_valid": 4, "lost": 1, "gained": 1, "net": 0}
