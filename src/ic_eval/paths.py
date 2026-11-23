"""Project paths, so that scripts work from any directory."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
assert (REPO_ROOT / "pyproject.toml").exists(), f"{REPO_ROOT} is not the repo root"

_DATA_DIR = REPO_ROOT / "data"

DATA_INPUT_DIR = _DATA_DIR / "input"

DATA_JUDGE_PROMPTS = DATA_INPUT_DIR / "judge_prompts.json"
