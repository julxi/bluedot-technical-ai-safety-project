"""The deletion check of `ic-vast sync`, run with the real rsync between two local directories.

The rsync flags are the production ones (`rsync_args()` turned into a dry run); only the source
and destination are swapped for temporary directories. Nothing touches ssh or vast.ai.
"""

import subprocess
from pathlib import Path

from ic_eval.vast.common import REPO_ROOT
from ic_eval.vast.remote import (
    REMOTE_REPO_DIR,
    SSH_HOST_ALIAS,
    dry_run_args,
    parse_rsync_deletions,
    rsync_args,
)


def _write(path: Path, text: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _would_delete(src: Path, dst: Path) -> list[str]:
    args = dry_run_args(rsync_args())
    assert args[-2:] == [f"{REPO_ROOT}/", f"{SSH_HOST_ALIAS}:{REMOTE_REPO_DIR}/"], args
    args = args[:-2] + [f"{src}/", f"{dst}/"]
    result = subprocess.run(args, check=True, capture_output=True, text=True, timeout=30)
    return parse_rsync_deletions(result.stdout)


def test_lists_exactly_the_unprotected_extra_files(tmp_path: Path) -> None:
    """Catches a parser that drops or mangles deletions (e.g. one splitting on whitespace, which
    breaks the path with spaces), and flags that would let --delete reach .git, .venv or files
    the instance's .gitignore covers, or that would make the dry run write anything."""
    src, dst = tmp_path / "laptop", tmp_path / "instance"
    for root in (src, dst):
        _write(root / ".gitignore", "*.log\n")
        _write(root / "kept.py")
    _write(dst / "results" / "out.json")  # an output written to a tracked path
    _write(dst / " spaced name ")
    _write(dst / "run.log")  # gitignored on the instance
    _write(dst / ".git" / "HEAD")
    _write(dst / ".venv" / "bin" / "python")

    doomed = _would_delete(src, dst)

    assert sorted(doomed) == sorted(["results/out.json", "results/", " spaced name "]), doomed
    assert (dst / "results" / "out.json").exists(), "the dry run deleted a file"


def test_nothing_to_delete_when_trees_match(tmp_path: Path) -> None:
    """Catches a parser that mistakes rsync's other itemized lines (new or changed files) for
    deletions."""
    src, dst = tmp_path / "laptop", tmp_path / "instance"
    _write(src / "new_script.sh")
    _write(src / "changed.py", "new\n")
    _write(dst / "changed.py", "old\n")

    assert _would_delete(src, dst) == []
