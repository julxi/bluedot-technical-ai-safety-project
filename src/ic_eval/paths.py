"""Project paths, so that scripts work from any directory."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
assert (REPO_ROOT / "pyproject.toml").exists(), f"{REPO_ROOT} is not the repo root"

DATA_INPUT_DIR = REPO_ROOT / "data" / "input"
