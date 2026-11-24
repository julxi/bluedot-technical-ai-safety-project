"""Tests for build_script_command (src/ic_eval/vast/remote.py): script arguments must reach the
remote script unchanged through two layers of shell quoting (ssh command, then `bash -lc`), and
the command must return at once without holding its output open (run locally with bash, a pipe
standing in for the ssh channel; no ssh, no rental)."""

import shlex
import subprocess
import time
from pathlib import Path

import pytest

from ic_eval.vast import remote
from ic_eval.vast.remote import build_script_command


def remote_argv(command: str) -> list[str]:
    """The argv the remote `bash -lc` runs for the script, recovered from the built command."""
    outer = shlex.split(command)
    inner = outer[outer.index("-lc") + 1]  # the string bash -lc executes
    first = inner.split(";", 1)[0]  # "cd <repo> && bash <script> <args>"
    return shlex.split(first.split("&&", 1)[1])


def test_arguments_reach_the_script_unchanged() -> None:
    """Catches lost or split arguments, e.g. a model name with a space or a quote."""
    args = ["allenai/Olmo-3-7B-Think-SFT", "main", "it's a test"]
    command = build_script_command("scripts/vm/serve_vllm.sh", args, False, "/root/x.log")
    assert remote_argv(command) == ["bash", "scripts/vm/serve_vllm.sh", *args]


def test_no_arguments() -> None:
    command = build_script_command("scripts/vm/serve_vllm.sh", [], False, "/root/x.log")
    assert remote_argv(command) == ["bash", "scripts/vm/serve_vllm.sh"]


SCRIPT_SECONDS = 3


@pytest.fixture
def local_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the remote repo and log dirs at tmp_path and put a short script there."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "job.sh").write_text(f"sleep {SCRIPT_SECONDS}\n")
    monkeypatch.setattr(remote, "REMOTE_REPO_DIR", str(repo))
    monkeypatch.setattr(remote, "REMOTE_SCRIPT_LOG_DIR", str(tmp_path / "logs"))
    return tmp_path


def test_launch_returns_at_once_and_the_script_runs(local_dirs: Path) -> None:
    """Catches a launch command that holds the ssh channel's stdout while the script runs: with
    `mkdir ... && setsid ... &` the pipe stayed open the full 3 s (26-11-23), so `ic-serve up`
    never ended for a caller that reads its output."""
    log = local_dirs / "logs" / "job.log"
    command = build_script_command("job.sh", [], False, str(log))
    start = time.monotonic()
    # capture_output waits until every holder of the pipe has closed it, like a caller of ssh -f.
    done = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=30)
    elapsed = time.monotonic() - start
    assert done.returncode == 0, done.stderr
    assert elapsed < 1.0, f"launch held the output for {elapsed:.1f}s"

    deadline = time.monotonic() + SCRIPT_SECONDS + 10
    while "script exited with code" not in (log.read_text() if log.exists() else ""):
        assert time.monotonic() < deadline, "the detached script never finished"
        time.sleep(0.2)
    assert "[ic-vast] script exited with code 0" in log.read_text()


def test_failing_log_dir_fails_the_launch(
    local_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a launch that ignores a failed mkdir (ssh would exit 0 and the script never run)."""
    blocker = local_dirs / "a_file"
    blocker.write_text("")
    monkeypatch.setattr(remote, "REMOTE_SCRIPT_LOG_DIR", str(blocker / "logs"))
    command = build_script_command("job.sh", [], False, str(blocker / "logs" / "job.log"))
    done = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=30)
    assert done.returncode != 0
    assert "mkdir" in done.stderr
