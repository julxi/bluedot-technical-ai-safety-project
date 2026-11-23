"""Analysis: read Inspect logs into tables and interpret them (design: tasks record, analysis
interprets). Everything that is a decision about meaning lives here: how judge replies are
parsed, the threshold, which judgings are compared. Changing one means rerunning the analysis
on existing logs, never regenerating or rejudging.

- logs.py: find logs; load generation and judge logs into pandas tables
- verdicts.py: read the verdict out of a judge reply, per the output format its prompt asked for
- agreement.py: rates per judging, pairwise agreement and Cohen's kappa
- report.py: `uv run python -m ic_eval.analysis.report` prints all of it and writes a file of
  judge disagreements (plus a sample of agreements) to read
"""
