"""The onstart ssh-mode fix (sshmodes.py), run for real with sh on a temporary directory tree.

The tree mimics / -> /root -> /root/.ssh -> authorized_keys. The tests run as a normal user, so
the script is told to treat this user's uid as the owner sshd wants (root on an instance).
"""

import os
import stat
import subprocess
from pathlib import Path

from ic_eval.vast import sshmodes


def _tree(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    top = tmp_path / "top"
    home = top / "root"
    dot_ssh = home / ".ssh"
    keys = dot_ssh / "authorized_keys"
    dot_ssh.mkdir(parents=True)
    keys.write_text("ssh-ed25519 AAAA test\n")
    top.chmod(0o755)
    home.chmod(0o700)
    dot_ssh.chmod(0o700)
    keys.chmod(0o600)
    return top, home, dot_ssh, keys


def _run(tmp_path: Path, paths: tuple[Path, ...]) -> list[str]:
    report = tmp_path / "container_stdout"
    script = sshmodes.onstart_script(
        paths=tuple(str(p) for p in paths),
        uid=os.getuid(),
        log_path=str(tmp_path / "ssh_modes.log"),
        report_path=str(report),
        watch_seconds=2,
        poll_seconds=1,
        background=False,
    )
    subprocess.run(["sh", "-c", script], check=True, timeout=30)
    return sshmodes.report_lines(report.read_text())


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_fixes_writable_paths_and_reports_each_once(tmp_path):
    """Catches a loop that does not fix group/world-writable paths, that touches paths sshd would
    accept, or that reports the same fix on every poll."""
    top, home, dot_ssh, keys = _tree(tmp_path)
    home.chmod(0o775)  # group-writable home: sshd refuses
    keys.chmod(0o666)  # world-writable keys: sshd refuses
    lines = _run(tmp_path, (top, home, dot_ssh, keys))

    assert _mode(home) == 0o755
    assert _mode(keys) == 0o644
    assert _mode(top) == 0o755 and _mode(dot_ssh) == 0o700  # were fine, untouched
    fixed = [line for line in lines if " fixed " in line]
    assert len(fixed) == 2, lines
    assert f"fixed {home}: was {os.getuid()}:{os.getgid()} 775, now" in fixed[0]
    assert f"fixed {keys}: was {os.getuid()}:{os.getgid()} 666, now" in fixed[1]
    assert sshmodes.summary(lines).startswith("fixed: ")
    assert (tmp_path / "ssh_modes.log").read_text().count(" fixed ") == 2


def test_clean_tree_reports_start_and_nothing_fixed(tmp_path):
    """Catches a check that flags sshd-acceptable modes (700/600, 755) as bad."""
    top, home, dot_ssh, keys = _tree(tmp_path)
    lines = _run(tmp_path, (top, home, dot_ssh, keys))
    assert any(f" {sshmodes.STARTED};" in line for line in lines), lines
    assert not any(" fixed " in line for line in lines), lines
    assert sshmodes.summary(lines) == "ran, nothing to fix"


def test_missing_paths_are_skipped(tmp_path):
    """authorized_keys may not exist yet when the loop starts; it must wait, not fail."""
    top, home, dot_ssh, keys = _tree(tmp_path)
    keys.unlink()
    lines = _run(tmp_path, (top, home, dot_ssh, keys))
    assert sshmodes.summary(lines) == "ran, nothing to fix"


def test_summary_without_the_loop():
    """A container log without the loop's start line must say so, not 'nothing to fix'."""
    log = "Welcome to vast.ai\nAuthentication refused: bad ownership or modes for directory /root\n"
    lines = sshmodes.report_lines(log)
    assert lines == ["Authentication refused: bad ownership or modes for directory /root"]
    assert "did NOT report" in sshmodes.summary(lines)
