"""Everything done to a rented instance over ssh: the `bluedot-vast` alias, waiting for sshd,
the self-destruct watchdog and timer, syncing the repo, running a script, machine facts.

Ported unchanged in substance from the first launcher
(convos/julian/26-11-18_vast_gpu_runner_LOG.md), where each piece was tested on a real rental
on 26-11-18.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

from dotenv import dotenv_values

from ic_eval.vast import sshmodes
from ic_eval.vast.boot import DEAD_STATUSES
from ic_eval.vast.common import REPO_ROOT, HostFailure, log
from ic_eval.vast.market import show_instance, vastai
from ic_eval.vast.sshmodes import BAD_KEY_MODES_MARKER

SSH_HOST_ALIAS = "bluedot-vast"
SSH_CONFIG_PATH = Path.home() / ".ssh/config.d" / f"{SSH_HOST_ALIAS}.conf"
DEFAULT_SSH_IDENTITY_FILE = Path.home() / ".ssh/id_rsa"
# Every ssh call is non-interactive: a password or passphrase prompt nobody answers would hang it.
# LogLevel=ERROR hides vast.ai's pre-login banner ("Welcome to vast.ai ...") and the "Permanently
# added ... to the list of known hosts" warning that every call printed. Errors such as
# "Permission denied (publickey)", which wait_until_ssh_ready looks for, still show [verified:
# OpenSSH 9.6, 26-11-18].
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "LogLevel=ERROR"]

REMOTE_REPO_DIR = "/root/bluedot"
REMOTE_SCRIPT_LOG_DIR = f"{REMOTE_REPO_DIR}/logs/remote"

TIMER_DIR = "/root/self_destruct"
TIMER_SCRIPT = f"{TIMER_DIR}/watchdog.py"
# Unix time (instance clock) after which the watchdog destroys the instance; no file = timer off.
TIMER_DEADLINE = f"{TIMER_DIR}/destroy_at"
TIMER_PID = f"{TIMER_DIR}/watchdog.pid"
TIMER_LOG = f"{TIMER_DIR}/watchdog.log"
# Rental facts the `timer` command shows (instance id, price), kept with the instance they describe.
TIMER_INSTANCE_INFO = f"{TIMER_DIR}/instance.json"
TIMER_POLL_S = 30
# vast.ai's launch script runs this on every container start (seen in /.launch of the
# vastai/vllm image, 26-11-18); it creates the file if the image has none.
ONSTART_SCRIPT = "/root/onstart.sh"


def _watchdog_start_command(python: str) -> str:
    """Detached (setsid nohup, stdin closed), so the watchdog outlives the ssh session or
    onstart.sh that starts it; the PID file lets `_timer_status` tell a live watchdog from a
    stale one."""
    return (
        f"setsid nohup {python} {TIMER_SCRIPT} watch {TIMER_DIR} {TIMER_POLL_S} "
        f">> {TIMER_DIR}/watchdog.out 2>&1 < /dev/null & echo $! > {TIMER_PID}"
    )


SSH_READY_TIMEOUT_S = 300
SSH_POLL_INTERVAL_S = 5
WATCHDOG_START_TIMEOUT_S = 15

# Runs on the instance under the image's system python3, so it uses only the standard library and
# avoids syntax newer than Python 3.8. Written there by `_install_watchdog`.
WATCHDOG_SOURCE = '''\
"""Self-destruct watchdog for a rented vast.ai instance, written and started by ic_eval/vast.py.

check <dir> <poll_s>: confirm the per-instance key can act on this instance (a no-op "start" of
    the running instance), then print the instance id.
watch <dir> <poll_s>: every poll_s seconds, read <dir>/destroy_at (a unix time; no file = timer
    off) and, once that time has passed, destroy this instance through vast.ai's API.

The key is vast.ai's CONTAINER_API_KEY, which can only start, stop or destroy this one instance.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

API_URL = "https://console.vast.ai/api/v0/instances/{}/"


def container_env():
    # vast.ai's docs warn that docker env vars do not always reach ssh sessions; PID 1 has them.
    with open("/proc/1/environ", "rb") as f:
        pairs = [p.split(b"=", 1) for p in f.read().split(b"\\0") if b"=" in p]
    env = {k.decode(): v.decode() for k, v in pairs}
    return env["CONTAINER_ID"], env["CONTAINER_API_KEY"]


def call(method, instance_id, key, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        API_URL.format(instance_id),
        data=data,
        method=method,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode())


def log(path, message):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "a") as f:
        f.write(stamp + " " + message + "\\n")


def main():
    mode, timer_dir, poll_s = sys.argv[1], sys.argv[2], float(sys.argv[3])
    instance_id, key = container_env()
    if mode == "check":
        reply = call("PUT", instance_id, key, {"state": "running"})
        assert reply["success"] is True, reply
        print(instance_id)
        return
    assert mode == "watch", mode
    deadline_path = os.path.join(timer_dir, "destroy_at")
    log_path = os.path.join(timer_dir, "watchdog.log")
    log(log_path, "watchdog started for instance " + instance_id)
    while True:
        # Intentionally catches everything and keeps looping: this process is the safety net
        # against a forgotten instance, so a failed API call or a half-written deadline file must
        # not end it. Every failure is logged and retried on the next poll.
        try:
            if os.path.exists(deadline_path):
                with open(deadline_path) as f:
                    deadline = float(f.read().strip())
                if time.time() >= deadline:
                    log(log_path, "deadline passed, destroying instance " + instance_id)
                    log(log_path, "destroy reply: " + json.dumps(call("DELETE", instance_id, key)))
        except Exception as e:
            log(log_path, "error: " + repr(e))
        time.sleep(poll_s)


main()
'''


class LocalGitState(NamedTuple):
    """Where the local checkout stands, recreated on the instance from a GitHub clone."""

    origin_url: str
    branch: str
    commit: str


class TimerStatus(NamedTuple):
    """The self-destruct timer as the instance reports it; times are the instance's clock."""

    now: int
    deadline: int | None
    watchdog_alive: bool
    instance: dict[str, Any]


def parse_duration(spec: str) -> int | None:
    """'2h', '1.5h', '90m' -> seconds; 'off' -> None."""
    # fire turns a bare number such as `timer 3` into an int; the unit must be explicit.
    assert isinstance(spec, str), (
        f"timer takes e.g. '2h', '90m' or 'off', got {spec!r} ({type(spec).__name__})"
    )
    if spec == "off":
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([hm])", spec)
    assert match, f"timer takes e.g. '2h', '90m' or 'off', got {spec!r}"
    seconds = float(match[1]) * (3600 if match[2] == "h" else 60)
    assert seconds >= 60, f"timer {spec!r} is under a minute"
    return int(seconds)


def install_watchdog(instance_id: int, offer: Any) -> None:
    """Write the watchdog, check that the instance's own key works, and start the watchdog.

    The check runs before anything relies on the timer: it confirms that the image has python3,
    that the per-instance key reaches vast.ai's API, and that the id the instance knows itself by
    is the one we rented - so the watchdog cannot destroy, or fail to destroy, the wrong thing.
    """
    ssh_input(f"mkdir -p {TIMER_DIR} && cat > {TIMER_SCRIPT}", WATCHDOG_SOURCE)
    info = {
        "instance_id": instance_id,
        "dph_total": offer["dph_total"],
        "gpu_name": offer["gpu_name"],
        "host_id": offer["host_id"],
        "rented_at": datetime.now().isoformat(timespec="seconds"),
    }
    ssh_input(f"cat > {TIMER_INSTANCE_INFO}", json.dumps(info))
    seen_id = ssh_output(f"python3 {TIMER_SCRIPT} check {TIMER_DIR} {TIMER_POLL_S}").strip()
    assert seen_id == str(instance_id), (
        f"The instance reports CONTAINER_ID={seen_id!r}, but we rented {instance_id}; the "
        f"watchdog would act on the wrong instance"
    )
    # Also started from onstart.sh, which vast.ai's launch script (/.launch) runs on every
    # container start: the container can restart under us, which kills every process but keeps
    # /root. Seen 26-11-18: instance 61292124 restarted 27 s after it was ready, and the
    # watchdog was gone until `ic-vast timer` restarted it.
    # The absolute interpreter path, because onstart.sh runs with PID 1's environment, whose PATH
    # may lack the image's python3 (a shim in /opt/sys-venv/shim/ on vastai/vllm).
    python = ssh_output("command -v python3").strip()
    assert python.startswith("/"), f"`command -v python3` on the instance gave {python!r}"
    onstart_line = _watchdog_start_command(python)
    ssh(
        f"grep -qF {shlex.quote(TIMER_SCRIPT)} {ONSTART_SCRIPT} 2>/dev/null "
        f"|| echo {shlex.quote(onstart_line)} >> {ONSTART_SCRIPT}"
    )
    start_watchdog()
    log(
        f"Self-destruct watchdog running (checks every {TIMER_POLL_S}s; restarts with the "
        f"container via {ONSTART_SCRIPT})"
    )


def start_watchdog() -> None:
    """Start the watchdog detached and wait until it is alive.

    `ssh -n -f` plus `setsid nohup ... < /dev/null &`: without `-f` the local ssh call can hang
    until the remote process ends (SPD repo FEEDBACK.md, 26-10-21).
    """
    ssh_detached(_watchdog_start_command("python3"))
    deadline = time.time() + WATCHDOG_START_TIMEOUT_S
    while time.time() < deadline:
        if timer_status().watchdog_alive:
            return
        time.sleep(1)
    output = ssh_output(f"tail -n 20 {TIMER_DIR}/watchdog.out {TIMER_LOG} 2>&1 || true")
    raise AssertionError(
        f"The watchdog did not stay alive within {WATCHDOG_START_TIMEOUT_S}s:\n{output}"
    )


def set_timer(seconds: int | None) -> None:
    """Set the deadline to `seconds` from now on the instance's clock, or remove it.

    The deadline is computed remotely, so a skewed laptop clock cannot shorten or stretch it. The
    file is replaced atomically, so the watchdog never reads a half-written number.
    """
    if seconds is None:
        ssh(f"rm -f {TIMER_DEADLINE}")
        log("Self-destruct timer off")
        return
    ssh(
        f"echo $(( $(date +%s) + {seconds} )) > {TIMER_DEADLINE}.tmp "
        f"&& mv {TIMER_DEADLINE}.tmp {TIMER_DEADLINE}"
    )
    log(f"Self-destruct timer set to {format_duration(seconds)} from now")


def timer_status() -> TimerStatus:
    """Read the timer state from the instance in one ssh call, as `key=value` lines."""
    script = "\n".join(
        [
            "echo now=$(date +%s)",
            (
                f"if [ -f {TIMER_DEADLINE} ]; then echo deadline=$(cat {TIMER_DEADLINE}); "
                "else echo deadline=off; fi"
            ),
            (
                f"if [ -f {TIMER_PID} ] && grep -qa watchdog.py /proc/$(cat {TIMER_PID})/cmdline "
                "2>/dev/null; then echo alive=yes; else echo alive=no; fi"
            ),
            f"echo instance=$(cat {TIMER_INSTANCE_INFO})",
        ]
    )
    lines = ssh_output(script).strip().splitlines()
    fields = dict(line.split("=", 1) for line in lines)
    assert sorted(fields) == ["alive", "deadline", "instance", "now"], f"bad timer status: {lines}"
    assert fields["alive"] in ("yes", "no"), fields
    return TimerStatus(
        now=int(fields["now"]),
        deadline=None if fields["deadline"] == "off" else int(fields["deadline"]),
        watchdog_alive=fields["alive"] == "yes",
        instance=json.loads(fields["instance"]),
    )


def timer_values(status: TimerStatus) -> dict[str, Any]:
    dph = status.instance["dph_total"]
    if status.deadline is None:
        deadline = "off - the instance runs until you destroy it"
        max_cost = f"unbounded (${dph:.3f}/h)"
    else:
        left_s = max(status.deadline - status.now, 0)
        local_deadline = datetime.fromtimestamp(time.time() + left_s)
        deadline = f"{local_deadline:%H:%M:%S} local time, in {format_duration(left_s)}"
        max_cost = f"${dph * left_s / 3600:.2f} more at ${dph:.3f}/h"
    return {
        "instance": status.instance["instance_id"],
        "timer": deadline,
        "cost until timer": max_cost,
        "watchdog": "running" if status.watchdog_alive else "NOT RUNNING",
    }


def format_duration(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    return f"{hours}h{rest // 60:02d}m" if hours else f"{rest // 60}m{rest % 60:02d}s"


def ssh_identity_file() -> Path:
    """The private key ssh authenticates to rented machines with.

    The path is machine-specific but not secret, so it lives in the gitignored `.env` (or the
    environment) rather than in the git-tracked machine configs.
    """
    # .get: an unset VAST_SSH_KEY is the normal case and means the default key.
    configured = dotenv_values(REPO_ROOT / ".env").get("VAST_SSH_KEY") or os.environ.get(
        "VAST_SSH_KEY"
    )
    key = Path(configured).expanduser() if configured else DEFAULT_SSH_IDENTITY_FILE
    assert key.exists(), f"ssh key not found: {key}. Set VAST_SSH_KEY in .env."
    return key


def public_key_path(identity_file: Path) -> Path:
    """OpenSSH appends `.pub` to the whole filename, so `vast.key` pairs with `vast.key.pub`."""
    return identity_file.with_name(identity_file.name + ".pub")


def attach_ssh_key(instance_id: int, identity_file: Path) -> None:
    """Push our public key to the instance through vast.ai's control plane.

    vast.ai's entrypoint copies account-level keys into authorized_keys at container start, but on
    some hosts that is slow or never happens, and there is no way in to fix it by hand. Attaching
    is idempotent, so it runs on every rental rather than only on the ones that turn out to need
    it.
    """
    public_key = public_key_path(identity_file)
    assert public_key.exists(), f"public key not found: {public_key}"
    vastai(["attach", "ssh", str(instance_id), public_key.read_text().strip()], raw=False)


def ssh_host_port(instance_id: int) -> tuple[str, int]:
    """Parse `vastai ssh-url`, which reports the right host/port for direct or proxied ssh."""
    ssh_url = vastai(["ssh-url", str(instance_id)], raw=False).strip()
    assert ssh_url.startswith("ssh://"), f"Unexpected ssh url: {ssh_url}"
    host_port = ssh_url.removeprefix("ssh://").split("@")[-1]
    host, port = host_port.split(":")
    return host, int(port)


def write_ssh_config(host: str, port: int, instance_id: int, identity_file: Path) -> None:
    """Write the `bluedot-vast` ssh stanza and check that ssh resolves the alias to it.

    Host keys are not checked because every rental is a fresh machine, often reusing an
    ip:port that a previous rental had. The `ssh -G` check catches a ~/.ssh/config without an
    `Include` of config.d, which would otherwise surface as five minutes of failing ssh probes
    and a wrongly blacklisted host.
    """
    SSH_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SSH_CONFIG_PATH.write_text(
        f"# generated by ic-vast (src/ic_eval/vast.py) for instance {instance_id} "
        f"at {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"Host {SSH_HOST_ALIAS}\n"
        f"    HostName {host}\n"
        f"    User root\n"
        f"    IdentityFile {identity_file}\n"
        f"    Port {port}\n"
        f"    StrictHostKeyChecking no\n"
        f"    UserKnownHostsFile /dev/null\n"
        f"    LogLevel ERROR\n"
    )
    resolved = subprocess.check_output(["ssh", "-G", SSH_HOST_ALIAS], text=True).splitlines()
    assert f"hostname {host}" in resolved and f"port {port}" in resolved, (
        f"ssh does not pick up {SSH_CONFIG_PATH}: `ssh -G {SSH_HOST_ALIAS}` resolves to "
        f"{[line for line in resolved if line.startswith(('hostname ', 'port '))]}. Add "
        f"`Include ~/.ssh/config.d/*` at the top of ~/.ssh/config."
    )


def wait_until_ssh_ready(instance_id: int, identity_file: Path) -> None:
    """Poll until sshd accepts our key, re-attaching it once halfway through.

    `actual_status == "running"` only means the container started: vast.ai's entrypoint installs
    authorized_keys a few seconds later, and connections made before that are closed mid-auth. A
    host that rejects the key is not a lost cause either - the same key is often accepted minutes
    later - so the loop keeps polling through "Permission denied" and re-attaches once in case the
    entrypoint overwrote authorized_keys after we first attached.
    """
    log("Waiting for ssh to accept our key")
    deadline = time.time() + SSH_READY_TIMEOUT_S
    reattach_at = time.time() + SSH_READY_TIMEOUT_S / 2
    reattached = False
    last_error = "<no probe ran>"
    while time.time() < deadline:
        probe = subprocess.run(
            ["ssh", *SSH_OPTS, "-o", "ConnectTimeout=10", SSH_HOST_ALIAS, "true"],
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        if probe.returncode == 0:
            return
        last_error = probe.stderr.strip() or f"exit code {probe.returncode}, no stderr"
        if not reattached and time.time() >= reattach_at:
            log(f"ssh still failing ({last_error}) - re-attaching the key")
            attach_ssh_key(instance_id, identity_file)
            reattached = True
        time.sleep(SSH_POLL_INTERVAL_S)
    shown = show_instance(instance_id)
    status = shown["actual_status"] if shown is not None else "vanished"
    if shown is None or status in DEAD_STATUSES:
        raise HostFailure(
            "dead" if shown is not None else "vanished",
            f"Instance {instance_id} went '{status}' while we waited for ssh. The host dropped "
            f"off vast.ai's control plane after reporting itself running, so it never installed "
            f"the key - the rejection is the host's fault, not the key's.",
        )
    cause = ""
    if "Permission denied" in last_error:
        # sshd's own words, e.g. which path it found bad; the caller records the full report.
        refused = [
            line for line in sshmodes.fetch_report(instance_id) if BAD_KEY_MODES_MARKER in line
        ]
        if refused:
            cause = f"; sshd: {refused[-1]!r} ({len(refused)} such lines)"
    # Counted against the host although a broken local key would fail the same way: a key that
    # works on other hosts is far more common, and repeated ssh failures everywhere would show it.
    raise HostFailure(
        "ssh",
        f"ssh to {SSH_HOST_ALIAS} still failing after {SSH_READY_TIMEOUT_S}s while instance "
        f"{instance_id} reports '{status}'{cause}. Last ssh error: {last_error}. "
        f"'Permission denied (publickey)' means sshd is up but never took the key in "
        f"{identity_file}; a refused or timed out connection means the direct port mapping never "
        f"came up. The entrypoint's own account: vastai logs {instance_id}",
    )


def ssh(remote_command: str) -> None:
    subprocess.run(
        ["ssh", *SSH_OPTS, SSH_HOST_ALIAS, remote_command],
        check=True,
        stdin=subprocess.DEVNULL,
    )


def ssh_output(remote_command: str) -> str:
    return subprocess.run(
        ["ssh", *SSH_OPTS, SSH_HOST_ALIAS, remote_command],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    ).stdout


def ssh_input(remote_command: str, text: str) -> None:
    """Run a remote command with `text` on its stdin.

    The way to send file contents, and the only allowed way to send a secret: unlike a command
    argument, stdin shows up in no process list, locally or remotely.
    """
    subprocess.run(
        ["ssh", *SSH_OPTS, SSH_HOST_ALIAS, remote_command],
        check=True,
        input=text,
        text=True,
    )


def ssh_detached(remote_command: str) -> None:
    """Start a remote background command and return at once (see `_start_watchdog`)."""
    subprocess.run(
        ["ssh", *SSH_OPTS, "-n", "-f", SSH_HOST_ALIAS, remote_command],
        check=True,
        stdin=subprocess.DEVNULL,
    )


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(REPO_ROOT), *args], text=True).strip()


def local_git_state() -> LocalGitState:
    """Read the local branch and HEAD commit, asserting the instance can fetch that commit.

    The instance clones from `origin` over https without credentials, so `origin` must be a public
    https remote and HEAD must be on one of its branches. The check reads our remote-tracking refs
    (as of the last fetch/push); a commit missing on GitHub after all still fails on the instance,
    in `git update-ref`.
    """
    origin_url = git("remote", "get-url", "origin")
    assert origin_url.startswith("https://"), (
        f"origin is {origin_url}; the instance clones it without credentials, so it must be https"
    )
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    assert branch != "HEAD", "Detached HEAD: check out a branch, the instance is put on it"
    commit = git("rev-parse", "HEAD")
    assert git("branch", "-r", "--list", "origin/*", "--contains", commit), (
        f"HEAD {commit[:8]} is on no origin branch: push it first. The instance gets the git "
        f"history from {origin_url}; only the working tree is uploaded."
    )
    return LocalGitState(origin_url=origin_url, branch=branch, commit=commit)


def build_checkout_script(git_state: LocalGitState) -> str:
    """Put the instance's checkout on our branch and HEAD commit, with the history from GitHub.

    Run before every rsync. It sets only git's view (HEAD, branch, index); the rsync then makes the
    files match our working tree, so `git status` there shows our uncommitted changes as such.

    `.git` is fetched rather than uploaded because a home uplink is far slower than the
    instance's download (Julian's measured ~79 KB/s, SPD repo 26-11-11).

    `git update-ref` + `symbolic-ref` + `reset --mixed` instead of `git checkout`: they never touch
    the working tree, so a re-sync onto a tree that holds our uncommitted edits cannot conflict.
    """
    return "\n".join(
        [
            "set -euo pipefail",
            (
                "for tool in git rsync; do command -v $tool >/dev/null "
                '|| { echo "$tool is not installed in this image" >&2; exit 1; }; done'
            ),
            # A private or mistyped repo must fail, not wait for a password nobody will type.
            "export GIT_TERMINAL_PROMPT=0",
            (
                f"[ -d {REMOTE_REPO_DIR}/.git ] || "
                f"git clone -q {shlex.quote(git_state.origin_url)} {REMOTE_REPO_DIR}"
            ),
            f"cd {REMOTE_REPO_DIR}",
            "git fetch -q origin",
            f"git update-ref refs/heads/{git_state.branch} {git_state.commit}",
            f"git symbolic-ref HEAD refs/heads/{git_state.branch}",
            "git reset -q --mixed",
        ]
    )


def rsync_args() -> list[str]:
    """Sync the working tree onto the instance's clone, `.git` excluded.

    rsync's delta transfer sends only block checksums for files that already match the clone, so
    only our uncommitted changes cross the uplink. Excluded paths (`.git`, `.venv`, gitignored
    files such as `.env` and `logs/`) are never deleted on the instance despite `--delete`.

    Ownership is deliberately not preserved: `-a` would carry our local uid across, and the
    container runs as root, so git would then refuse the repo as having dubious ownership.
    """
    return [
        "rsync",
        "-az",
        "--no-owner",
        "--no-group",
        "--delete",
        # A live progress line on a terminal; in a log file it is hundreds of carriage-return
        # updates, so there only the end-of-run totals.
        "--info=progress2" if sys.stdout.isatty() else "--info=stats1",
        "--filter=:- .gitignore",
        "--exclude=/.git/",
        "--exclude=.venv",
        "-e",
        shlex.join(["ssh", *SSH_OPTS]),
        f"{REPO_ROOT}/",
        f"{SSH_HOST_ALIAS}:{REMOTE_REPO_DIR}/",
    ]


def sync_repo(git_state: LocalGitState) -> None:
    log(f"Fetching {git_state.branch} @ {git_state.commit[:8]} on the instance from GitHub")
    ssh(f"bash -c {shlex.quote(build_checkout_script(git_state))}")
    args = rsync_args()
    log(f"Syncing working tree: {shlex.join(args)}")
    subprocess.run(args, check=True, stdin=subprocess.DEVNULL)


# rsync's itemized line for a deletion: "*deleting" padded to the 11-character change field, one
# space, then the path relative to the destination root (directories end in '/'). Seen in the
# output of rsync 3.2.7 (tests/vast/test_resync.py runs it for real).
_RSYNC_DELETING_PREFIX = "*deleting   "


def parse_rsync_deletions(itemized: str) -> list[str]:
    """The paths an `rsync --itemize-changes` run deletes (with `--dry-run`: would delete).

    Sliced at a fixed width rather than split on whitespace, so a path with leading or trailing
    spaces comes out intact.
    """
    return [
        line[len(_RSYNC_DELETING_PREFIX) :]
        for line in itemized.splitlines()
        if line.startswith(_RSYNC_DELETING_PREFIX)
    ]


def dry_run_args(args: list[str]) -> list[str]:
    """`rsync_args()` turned into a dry run that itemizes changes and prints no progress lines."""
    assert args[0] == "rsync", args
    return ["rsync", "--dry-run", "--itemize-changes"] + [
        a for a in args[1:] if not a.startswith("--info=")
    ]


def files_a_sync_would_delete() -> list[str]:
    """Paths under the instance's repo that `sync_repo` would delete: files that exist there but
    not in our working tree, and that the instance's own `.gitignore` files don't cover (rsync
    reads the receiving side's `.gitignore` files when deciding what `--delete` protects)."""
    result = subprocess.run(
        dry_run_args(rsync_args()),
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    return parse_rsync_deletions(result.stdout)


def check_script(script: str) -> None:
    """The script must be a bash file in the repo that the rsync uploads (i.e. not gitignored)."""
    path = REPO_ROOT / script
    assert not Path(script).is_absolute() and path.is_file(), (
        f"--script takes a repo-relative path to a file, got {script!r}"
    )
    assert path.suffix == ".sh", f"--script runs bash scripts (.sh), got {script!r}"
    # Exit 0 = ignored, 1 = not ignored, 128 = error; the assert accepts only 1.
    ignored = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", script], check=False
    )
    assert ignored.returncode == 1, f"{script} is gitignored, so the rsync would not upload it"


def build_script_command(script: str, destroy_on_exit: bool, log_path: str) -> str:
    """The detached remote command that runs `script` in a login shell from the repo.

    A login shell, because it reads /etc/profile.d/, where secrets would be installed over ssh
    (docs/CODING.md). With destroy_on_exit, the deadline is set to "now" when the script ends,
    so the watchdog destroys the instance within one poll.
    """
    inner = (
        f"cd {REMOTE_REPO_DIR} && bash {shlex.quote(script)}; "
        'echo "[ic-vast] script exited with code $?"'
    )
    if destroy_on_exit:
        inner += f"; date +%s > {TIMER_DEADLINE}"
    return (
        f"mkdir -p {REMOTE_SCRIPT_LOG_DIR} && setsid nohup bash -lc {shlex.quote(inner)} "
        f"> {log_path} 2>&1 < /dev/null &"
    )


def launch_script(script: str, destroy_on_exit: bool) -> str:
    """Start the script detached; returns the remote log path."""
    log_path = f"{REMOTE_SCRIPT_LOG_DIR}/{Path(script).stem}_{datetime.now():%y%m%d_%H%M%S}.log"
    ssh_detached(build_script_command(script, destroy_on_exit, log_path))
    return log_path


def machine_info() -> dict[str, str]:
    """GPU power limit and CPU quota, the two host settings that silently slowed SPD runs.

    A 500 W H100 ran 40% slower than a ~600 W one; a container with a 23-CPU quota on a 192-core
    host throttled CPU-heavy jobs (SPD repo, 26-10-03 and 26-11-16).
    """
    gpu = ssh_output(
        "nvidia-smi --query-gpu=name,memory.total,power.limit --format=csv,noheader"
    ).strip()
    cpu = ssh_output(
        'echo "quota $(cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo unknown), nproc $(nproc)"'
    ).strip()
    return {"gpu (nvidia-smi)": gpu, "cpu (cgroup quota/period)": cpu}
