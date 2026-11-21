"""Keeps sshd's StrictModes from refusing our key: the instance's onstart command resets the
ownership and modes of the paths sshd checks, and reports every fix to `vastai logs`.

Why: on 2 of the first 4 rentals that reached `running` (host 314882 on 26-11-18, host 679583 on
26-11-21, image vastai/vllm), sshd refused our key for the full 5 min of waiting with "bad
ownership or modes" for authorized_keys, and the rentals were lost as host failures. sshd
(StrictModes, on by default) rejects authorized_keys if the file, or any directory above it
(/root/.ssh, /root, /), is owned by a user other than root or is group- or world-writable. sshd
checks on every login attempt, so a fix at any time before the next attempt is enough.

Whether the host or vast.ai's container start causes it is not known, and when the modes go bad
is not known either (vast.ai installs the key at container start and again on `vastai attach
ssh`). So the fix is a loop that runs for WATCH_SECONDS from container start, not a one-off
chmod. It logs the state it found before every fix, so each rental's record (records.Attempt
.ssh_modes) shows whether the fault would have hit. Design and test rentals:
convos/julian/26-11-18_vast_host_selection_LOG.md, entry *ssh mode fix, ...*.

The script goes to vast.ai as `--onstart-cmd`, which vast.ai stores on its servers: it must
never carry a secret (docs/CODING.md).
"""

import shlex
import subprocess

# Prefix of every line the onstart loop writes; how its lines are found in `vastai logs`.
TAG = "[ic-vast ssh-modes]"
STARTED = "started"
# The ones sshd's StrictModes checks for root's authorized_keys, top down.
CHECKED_PATHS = ("/", "/root", "/root/.ssh", "/root/.ssh/authorized_keys")
# Container start to the end of the ssh wait is at most a few minutes once `running` (300 s of
# ssh polling in remote.wait_until_ssh_ready), plus the key re-attach halfway through it.
WATCH_SECONDS = 900
POLL_SECONDS = 2
LOG_PATH = "/root/ssh_modes.log"
# PID 1's stdout is the container's log, which `vastai logs` shows: the one place the loop's
# report can be read when ssh never works.
CONTAINER_STDOUT = "/proc/1/fd/1"
# sshd's message, in `vastai logs`, when it refuses authorized_keys for its modes (SPD launcher,
# host 161249 on 26-10-31; here hosts 314882 and 679583).
BAD_KEY_MODES_MARKER = "bad ownership or modes"


def onstart_script(
    paths: tuple[str, ...] = CHECKED_PATHS,
    uid: int = 0,
    log_path: str = LOG_PATH,
    report_path: str = CONTAINER_STDOUT,
    watch_seconds: int = WATCH_SECONDS,
    poll_seconds: int = POLL_SECONDS,
    background: bool = True,
) -> str:
    """The onstart command: a POSIX sh loop (the shell vast.ai runs it with is not documented).

    A path is fixed when it exists and is owned by another uid than `uid`, or is group- or
    world-writable (`find -perm /022`): chown to `uid`, chmod go-w. Only the owner and the write
    bits change, nothing recursive. Each distinct (path, state before) is reported once, so a fix
    that cannot hold (e.g. on a read-only mount) does not flood the log. Errors of chown/chmod go
    into the report line.

    The parameters other than the defaults exist for tests, which run the script on a temporary
    directory as a normal user, in the foreground.
    """
    assert all(" " not in p and p.startswith("/") for p in paths), paths
    quoted_paths = " ".join(shlex.quote(p) for p in paths)
    log = shlex.quote(log_path)
    report = shlex.quote(report_path)
    body = f"""icvast_ssh_modes() {{
  say() {{ echo "{TAG} $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a {log} >> {report}; }}
  say "{STARTED}; checking {" ".join(paths)} every {poll_seconds} s for {watch_seconds} s"
  say "root mounts: $(grep -E ' /root[ /]' /proc/self/mountinfo | tr '\\n' ';')"
  seen=""
  end=$(( $(date +%s) + {watch_seconds} ))
  while [ "$(date +%s)" -lt "$end" ]; do
    for p in {quoted_paths}; do
      if [ -n "$(find "$p" -maxdepth 0 \\( ! -uid {uid} -o -perm /022 \\) 2>/dev/null)" ]; then
        before=$(stat -c '%u:%g %a' "$p")
        err=$(chown {uid} "$p" 2>&1; chmod go-w "$p" 2>&1)
        case "$seen" in
          *"|$p $before|"*) ;;
          *) seen="$seen|$p $before|"
             say "fixed $p: was $before, now $(stat -c '%u:%g %a' "$p")${{err:+; errors: $err}}" ;;
        esac
      fi
    done
    sleep {poll_seconds}
  done
  say "stopped after {watch_seconds} s"
}}
"""
    if background:
        return body + "icvast_ssh_modes </dev/null >/dev/null 2>&1 &\n"
    return body + "icvast_ssh_modes\n"


def report_lines(container_log: str) -> list[str]:
    """Our loop's lines and sshd's bad-modes lines from a container log, in order."""
    return [
        line.strip()
        for line in container_log.splitlines()
        if TAG in line or BAD_KEY_MODES_MARKER in line
    ]


def fetch_report(instance_id: int) -> list[str]:
    """`report_lines` of the instance's `vastai logs`.

    Diagnostics only, so a failing `vastai logs` call is reported in the result rather than
    raised: the caller is either recording a ready machine or already handling a host failure.
    """
    result = subprocess.run(
        ["vastai", "logs", str(instance_id)],
        check=False,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    lines = report_lines(result.stdout + result.stderr)
    if result.returncode != 0:
        lines.append(f"(`vastai logs` exit code {result.returncode}: {result.stderr.strip()})")
    return lines


def summary(lines: list[str]) -> str:
    """One line for the console: did the loop run, and what did it fix."""
    if not any(f"{TAG} " in line and f" {STARTED};" in line for line in lines):
        return "the onstart fix did NOT report in `vastai logs` (did it run?)"
    fixes = [line.split(" fixed ", 1)[1] for line in lines if " fixed " in line]
    return "fixed: " + " | ".join(fixes) if fixes else "ran, nothing to fix"
