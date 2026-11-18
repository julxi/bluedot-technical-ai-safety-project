"""Paths, the strict YAML base model, and console output shared by the vast modules."""

from datetime import datetime
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[2]
# Fails if the package was installed as a copy rather than editable: paths below need the repo.
assert (REPO_ROOT / "pyproject.toml").exists(), f"{REPO_ROOT} is not the repo root"
CONFIG_DIR = PACKAGE_DIR / "configs"
POLICY_CONFIG_PATH = CONFIG_DIR / "policy.yaml"
# Git-tracked, append-only history of every rental attempt (records.py); the model learns from it.
RENTALS_PATH = PACKAGE_DIR / "data" / "rentals.jsonl"
# Which instance `bluedot-vast` points at, for `ic-vast destroy`. Local state, so in the gitignored
# scratch/ folder rather than in git.
CURRENT_INSTANCE_PATH = REPO_ROOT / "scratch" / "vast_current_instance.json"


class HostFailure(Exception):
    """A rental that failed because of the host. `failure_type` is one of
    records.HOST_FAILURES; the attempt is recorded, counted against the host by the model, the
    instance destroyed and the next offer rented."""

    def __init__(self, failure_type: str, detail: str):
        super().__init__(detail)
        self.failure_type = failure_type
        self.detail = detail


class YamlModel(BaseModel):
    """Strict, immutable model loaded from YAML: unknown or mistyped fields fail at once."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @classmethod
    def from_file(cls, path: Path) -> Self:
        return cls(**yaml.safe_load(path.read_text()))


def log(message: str) -> None:
    print(f"[ic-vast {datetime.now():%H:%M:%S}] {message}", flush=True)


def section(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def values(items: dict[str, Any]) -> None:
    width = max(len(k) for k in items)
    for key, value in items.items():
        lines = str(value).splitlines() or [""]
        print(f"  {key:<{width}}  {lines[0]}", flush=True)
        for line in lines[1:]:
            print(f"  {'':<{width}}  {line}", flush=True)
