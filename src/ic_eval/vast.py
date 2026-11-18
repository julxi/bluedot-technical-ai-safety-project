"""Rent a vast.ai GPU for this project, prepare it, and optionally run a repo script on it.

vast.ai is a GPU marketplace, not a job service. `ic-vast rent` searches offers, rents a machine,
attaches an ssh key, writes the ssh alias `bluedot-vast`, arms a self-destruct timer on the
machine, has it clone this repo from GitHub and rsyncs the local working tree over the clone.
With `--script` it then starts that repo script there, detached.

Ported from `spd/scripts/run_vast.py` in Julian's targeted-parameter-decomposition repo ("the SPD
launcher"). Most guards below come from failed rentals recorded there; the design and what was
dropped (WandB, `uv sync` on the instance, the run/detached/sync modes) are recorded in
convos/julian/26-11-18_vast_gpu_runner_LOG.md, entry *implementation plan after Julian's answers*.

Commands (`uv run ic-vast <command> --help` for flags):
    ic-vast offers                       # browse matching offers, rent nothing
    ic-vast rent                         # rent + prepare with the default machine config (48gb)
    ic-vast rent --config h200           # src/ic_eval/vast_configs/h200.yaml
    ic-vast rent --script scripts/x.sh   # ... then run that repo script on the instance
    ic-vast rent --dry_run               # print what would happen, rent nothing
    ic-vast timer                        # show the self-destruct timer of the current instance
    ic-vast timer 2h                     # (re)set it to 2 hours from now ('90m' works too)
    ic-vast timer off                    # switch it off; the watchdog keeps running
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple, Self

import fire
import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
# Fails if the package was installed as a copy rather than editable: paths below need the repo.
assert (REPO_ROOT / "pyproject.toml").exists(), f"{REPO_ROOT} is not the repo root"
CONFIG_DIR = Path(__file__).resolve().parent / "vast_configs"
BLACKLIST_PATH = CONFIG_DIR / "blacklist.yaml"
DEFAULT_CONFIG = "48gb"

# Not `vastai`: the SPD launcher owns that alias and file, and both launchers must be usable at
# the same time without overwriting each other's ssh entry.
SSH_HOST_ALIAS = "bluedot-vast"
SSH_CONFIG_PATH = Path.home() / ".ssh/config.d" / f"{SSH_HOST_ALIAS}.conf"
DEFAULT_SSH_IDENTITY_FILE = Path.home() / ".ssh/id_rsa"
# Every ssh call is non-interactive: a password or passphrase prompt nobody answers would hang it.
SSH_OPTS = ["-o", "BatchMode=yes"]

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


READY_TIMEOUT_S = 900
POLL_INTERVAL_S = 10
SSH_READY_TIMEOUT_S = 300
SSH_POLL_INTERVAL_S = 5
WATCHDOG_START_TIMEOUT_S = 15
# vast.ai reports these when the host has dropped off its control plane. It keeps claiming
# intended_status "running", but the container never finishes provisioning.
DEAD_STATUSES = frozenset({"missing", "exited"})
# vast.ai's error for an ask it will not rent out: one already rented by someone else, or one
# that is unavailable although the search listed it as rentable (e.g. its host went offline).
TAKEN_OFFER_ERROR = "no_such_ask"
# A boot status containing this means the host cannot resolve vast.ai's own servers; such a host
# never finishes booting (SPD launcher, host 124072 on 26-10-06), so waiting 15 min is pointless.
DNS_FAILURE_MARKER = "resolve host"
# sshd's message, in `vastai logs`, when the host broke authorized_keys' file modes: a host fault
# that looks exactly like a rejected key from our side (SPD launcher, host 161249 on 26-10-31).
BAD_KEY_MODES_MARKER = "bad ownership or modes"

# Rewritten on top of the file whenever ic-vast adds a host, which drops any other comments.
BLACKLIST_HEADER = """\
# vast.ai hosts that ic-vast never rents again, whatever the machine config.
# A host is one operator (host_id), who may run several machines (machine_id). The failures that
# land a host here - never booting, ssh never connecting - come from the operator's setup or
# network, which all of their machines share, so the whole host is excluded.
# ic-vast appends a host itself when booting or ssh fails on it. Add hosts by hand when a rental
# turns out bad later (e.g. a slow Hugging Face download): ic-vast prints the host id of every
# offer and of the rented instance. Delete an entry to rent that host again.
# Entry format (replace `hosts: []` by a list if it is empty):
#   hosts:
#   - host_id: 124072
#     date: 26-10-06
#     reason: Hugging Face download at 2 MB/s (instance 1234567)
# This file is rewritten when ic-vast adds a host: put notes in `reason`, not in comments.
"""

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


class HostFailure(Exception):
    """A rental that failed because of the host, not because of us, so the host is blacklisted.

    `reason` is the short form that goes into the blacklist; the exception message is the full
    explanation shown to the user. `rent` blacklists the host and destroys the instance, so the
    message need not tell the user to.
    """

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class YamlModel(BaseModel):
    """Strict, immutable model loaded from YAML: unknown or mistyped fields fail at once."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @classmethod
    def from_file(cls, path: Path) -> Self:
        return cls(**yaml.safe_load(path.read_text()))


class BlacklistedHost(YamlModel):
    host_id: int = Field(
        description="vast.ai host id, i.e. the operator, not a single machine"
    )
    date: str = Field(description="When the host was added, YY-MM-DD")
    reason: str = Field(description="What failed, and on which instance")


class VastBlacklist(YamlModel):
    """Hosts excluded from every offer search, loaded from `vast_configs/blacklist.yaml`."""

    hosts: list[BlacklistedHost]


class VastConfig(YamlModel):
    """Machine selection and rental settings, loaded from a git-tracked YAML file."""

    gpu_names: list[str] = Field(
        description="vast.ai GPU names with spaces as underscores (e.g. 'RTX_A6000', 'A100_SXM4'); "
        "an offer with any of them matches. A list, because each 48 GB card has few offers"
    )
    max_price: float = Field(
        description="Maximum total price in $/hour, including storage"
    )
    min_gpu_ram: int = Field(
        description="Minimum GPU memory in GB (vast.ai filters this field in GB but reports it "
        "in MB)"
    )
    disk: int = Field(
        description="Disk to rent in GB. Machines with less free disk than this are filtered out, "
        "and offer prices are quoted including this much storage"
    )
    image: str = Field(
        description="Docker image to launch. Pin an exact tag, never 'latest': the tag is the "
        "only record of which vLLM version served a run"
    )
    min_reliability: float = Field(
        description="Minimum host reliability. Low-reliability hosts drop runs midway"
    )
    datacenter_only: bool = Field(
        description="Rent only hosts vast.ai lists as datacenters. False searches all hosts, it "
        "does not exclude datacenters"
    )
    excluded_countries: list[str] = Field(
        description="Two-letter country codes whose hosts are never rented (e.g. ['CN']). On "
        "26-10-26 a host in China could not reach huggingface.co (DNS poisoned; SPD repo), and "
        "every rental here downloads model weights from Hugging Face"
    )
    min_cuda: float = Field(
        description="Minimum CUDA version the host's driver supports; must cover the image's CUDA"
    )
    sort: str = Field(
        description="vast.ai sort order; the first available offer is rented (e.g. 'dph_total' "
        "for cheapest, 'dlperf_per_dphtotal-' for best performance per dollar)"
    )
    n_offers: int = Field(description="How many offers to fetch and show")
    timer: str = Field(
        description="Default self-destruct timer at rent time, e.g. '3h', '90m', or 'off'"
    )


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


# --------------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------------


def rent(
    script: str | None = None,
    config: str = DEFAULT_CONFIG,
    gpu_names: list[str] | None = None,
    max_price: float | None = None,
    min_gpu_ram: int | None = None,
    disk: int | None = None,
    image: str | None = None,
    offer_id: int | None = None,
    timer: str | None = None,
    destroy_on_exit: bool = False,
    dry_run: bool = False,
) -> None:
    """Rent a GPU, prepare it, and optionally run a repo script on it.

    Preparing means: ssh alias `bluedot-vast` written, self-destruct watchdog running with the
    timer set, repo cloned from GitHub and the local working tree rsynced over it (to
    /root/bluedot). The local HEAD commit must be pushed to origin: the instance fetches the git
    history from GitHub, and only the working tree is uploaded.

    Args:
        script: Repo-relative path of a bash script (.sh) to run on the instance after preparing,
            detached, in a login shell from /root/bluedot. Its output goes to
            /root/bluedot/logs/remote/. Omit it to only rent and prepare.
        config: Machine config: a short name ('h200' -> src/ic_eval/vast_configs/h200.yaml) or a
            path to a YAML file.
        gpu_names: Override the config's gpu_names, e.g. '[A100_SXM4]'.
        max_price: Override the config's max_price ($/h including disk).
        min_gpu_ram: Override the config's min_gpu_ram (GB).
        disk: Override the config's disk (GB).
        image: Override the config's image.
        offer_id: Rent this specific offer instead of searching (blacklist and countries are
            still checked, the config's other filters are not).
        timer: Self-destruct timer, e.g. '2h', '90m' or 'off'; default from the config.
        destroy_on_exit: With --script: destroy the instance (through the timer) once the script
            ends, whatever its exit code.
        dry_run: Print what would be run, rent nothing.
    """
    assert shutil.which("vastai"), (
        "vastai CLI not found. Install it with `pip install vastai`."
    )
    _log(f"vastai CLI {_vastai(['--version'], raw=False).strip()}")
    vast_config = _load_vast_config(
        config,
        overrides={
            "gpu_names": gpu_names,
            "max_price": max_price,
            "min_gpu_ram": min_gpu_ram,
            "disk": disk,
            "image": image,
            "timer": timer,
        },
    )
    timer_s = _parse_duration(vast_config.timer)
    assert not (destroy_on_exit and script is None), "--destroy_on_exit needs --script"
    if script is not None:
        _check_script(script)
    identity_file = _ssh_identity_file()
    # Checked before renting, so an unpushed commit costs nothing.
    git_state = _local_git_state()

    label = f"ic-eval-{Path(script).stem if script else 'rent'}-{datetime.now():%y%m%d-%H%M%S}"
    blacklisted = _blacklisted_host_ids(_load_blacklist())
    offers = (
        _search_offers(vast_config, blacklisted)
        if offer_id is None
        else [
            _find_offer(
                offer_id, blacklisted, vast_config.excluded_countries, vast_config.disk
            )
        ]
    )

    if dry_run:
        _section("Dry run - nothing rented")
        _values(
            {
                "create": shlex.join(
                    [
                        "vastai",
                        *_create_instance_args(
                            int(offers[0]["id"]), vast_config, label
                        ),
                    ]
                ),
                "host": offers[0]["host_id"],
                "price": f"${offers[0]['dph_total']:.3f}/h",
                "timer": vast_config.timer,
                "remote git": _build_checkout_script(git_state),
                "rsync": shlex.join(_rsync_args()),
                "script": _build_script_command(script, destroy_on_exit, "<log>")
                if script
                else "-",
            }
        )
        return

    instance_id, offer = _rent_first_available(offers, vast_config, label)
    _log(
        f"Created instance {instance_id} on host {offer['host_id']} (machine "
        f"{offer['machine_id']}), waiting for it to boot"
    )
    # Until the watchdog is armed, nothing on the instance can destroy it, so any failure before
    # that destroys it from here. After that, a failure of ours leaves it running for debugging,
    # covered by the timer (or deliberately not, with --timer off).
    destroy = True
    try:
        _wait_until_running(instance_id)
        _attach_ssh_key(instance_id, identity_file)
        host, port = _ssh_host_port(instance_id)
        _write_ssh_config(host, port, instance_id, identity_file)
        _log(f"Wrote {SSH_CONFIG_PATH} - connect with `ssh {SSH_HOST_ALIAS}`")
        _wait_until_ssh_ready(instance_id, identity_file)
        _install_watchdog(instance_id, offer)
        _set_timer(timer_s)
        destroy = False
        _sync_repo(git_state)
        _log_summary(instance_id, offer, _timer_status())
        if script is not None:
            log_path = _launch_script(script, destroy_on_exit)
            _log(
                f"Script started. Follow with: ssh {SSH_HOST_ALIAS} tail -f {log_path}"
            )
    except HostFailure as failure:
        # The failed instance is destroyed (in `finally`) so it stops billing, but intentionally
        # no next offer is rented: Julian wants to decide on a relaunch himself (SPD repo, and
        # convos/julian/26-11-18_vast_gpu_runner_LOG.md, answer A2).
        destroy = True
        _add_to_blacklist(
            BlacklistedHost(
                host_id=int(offer["host_id"]),
                date=datetime.now().strftime("%y-%m-%d"),
                reason=f"{failure.reason} (instance {instance_id}, machine {offer['machine_id']}, "
                f"{offer['gpu_name']}, {offer['geolocation']})",
            )
        )
        raise
    finally:
        if destroy:
            _destroy_instance(instance_id)
        else:
            _log(
                f"Instance running. Destroy it with: vastai destroy instance {instance_id} -y"
            )


def offers(
    config: str = DEFAULT_CONFIG,
    gpu_names: list[str] | None = None,
    max_price: float | None = None,
    min_gpu_ram: int | None = None,
    disk: int | None = None,
) -> None:
    """Print the offers `rent` would choose from, in its order, and rent nothing.

    Args:
        config: Machine config, as for `rent`.
        gpu_names: Override the config's gpu_names, e.g. '[A100_SXM4]'.
        max_price: Override the config's max_price ($/h including disk).
        min_gpu_ram: Override the config's min_gpu_ram (GB).
        disk: Override the config's disk (GB).
    """
    vast_config = _load_vast_config(
        config,
        overrides={
            "gpu_names": gpu_names,
            "max_price": max_price,
            "min_gpu_ram": min_gpu_ram,
            "disk": disk,
        },
    )
    found = _search_offers(vast_config, _blacklisted_host_ids(_load_blacklist()))
    _print_offers(found, vast_config.sort, vast_config.disk)


def timer_command(duration: str | None = None) -> None:
    """Show, set or switch off the self-destruct timer of the instance behind `bluedot-vast`.

    Restarts the watchdog if it is not running (e.g. after the container restarted).

    Args:
        duration: '2h' or '90m' sets the deadline to that long from now (replacing any earlier
            one); 'off' removes it. Omit it to only show the timer.
    """
    assert SSH_CONFIG_PATH.exists(), (
        f"{SSH_CONFIG_PATH} not found - rent an instance first"
    )
    if duration is not None:
        _set_timer(_parse_duration(duration))
    status = _timer_status()
    if not status.watchdog_alive:
        _log("The watchdog is not running on the instance - restarting it")
        _start_watchdog()
        status = _timer_status()
    _section("Self-destruct timer")
    _values(_timer_values(status))


# --------------------------------------------------------------------------------------------
# Self-destruct timer
# --------------------------------------------------------------------------------------------


def _parse_duration(spec: str) -> int | None:
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


def _install_watchdog(instance_id: int, offer: Any) -> None:
    """Write the watchdog, check that the instance's own key works, and start the watchdog.

    The check runs before anything relies on the timer: it confirms that the image has python3,
    that the per-instance key reaches vast.ai's API, and that the id the instance knows itself by
    is the one we rented - so the watchdog cannot destroy, or fail to destroy, the wrong thing.
    """
    _ssh_input(f"mkdir -p {TIMER_DIR} && cat > {TIMER_SCRIPT}", WATCHDOG_SOURCE)
    info = {
        "instance_id": instance_id,
        "dph_total": offer["dph_total"],
        "gpu_name": offer["gpu_name"],
        "host_id": offer["host_id"],
        "rented_at": datetime.now().isoformat(timespec="seconds"),
    }
    _ssh_input(f"cat > {TIMER_INSTANCE_INFO}", json.dumps(info))
    seen_id = _ssh_output(
        f"python3 {TIMER_SCRIPT} check {TIMER_DIR} {TIMER_POLL_S}"
    ).strip()
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
    python = _ssh_output("command -v python3").strip()
    assert python.startswith("/"), (
        f"`command -v python3` on the instance gave {python!r}"
    )
    onstart_line = _watchdog_start_command(python)
    _ssh(
        f"grep -qF {shlex.quote(TIMER_SCRIPT)} {ONSTART_SCRIPT} 2>/dev/null "
        f"|| echo {shlex.quote(onstart_line)} >> {ONSTART_SCRIPT}"
    )
    _start_watchdog()
    _log(
        f"Self-destruct watchdog running (checks every {TIMER_POLL_S}s; restarts with the "
        f"container via {ONSTART_SCRIPT})"
    )


def _start_watchdog() -> None:
    """Start the watchdog detached and wait until it is alive.

    `ssh -n -f` plus `setsid nohup ... < /dev/null &`: without `-f` the local ssh call can hang
    until the remote process ends (SPD repo FEEDBACK.md, 26-10-21).
    """
    _ssh_detached(_watchdog_start_command("python3"))
    deadline = time.time() + WATCHDOG_START_TIMEOUT_S
    while time.time() < deadline:
        if _timer_status().watchdog_alive:
            return
        time.sleep(1)
    output = _ssh_output(
        f"tail -n 20 {TIMER_DIR}/watchdog.out {TIMER_LOG} 2>&1 || true"
    )
    raise AssertionError(
        f"The watchdog did not stay alive within {WATCHDOG_START_TIMEOUT_S}s:\n{output}"
    )


def _set_timer(seconds: int | None) -> None:
    """Set the deadline to `seconds` from now on the instance's clock, or remove it.

    The deadline is computed remotely, so a skewed laptop clock cannot shorten or stretch it. The
    file is replaced atomically, so the watchdog never reads a half-written number.
    """
    if seconds is None:
        _ssh(f"rm -f {TIMER_DEADLINE}")
        _log("Self-destruct timer off")
        return
    _ssh(
        f"echo $(( $(date +%s) + {seconds} )) > {TIMER_DEADLINE}.tmp "
        f"&& mv {TIMER_DEADLINE}.tmp {TIMER_DEADLINE}"
    )
    _log(f"Self-destruct timer set to {_format_duration(seconds)} from now")


def _timer_status() -> TimerStatus:
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
    lines = _ssh_output(script).strip().splitlines()
    fields = dict(line.split("=", 1) for line in lines)
    assert sorted(fields) == ["alive", "deadline", "instance", "now"], (
        f"bad timer status: {lines}"
    )
    assert fields["alive"] in ("yes", "no"), fields
    return TimerStatus(
        now=int(fields["now"]),
        deadline=None if fields["deadline"] == "off" else int(fields["deadline"]),
        watchdog_alive=fields["alive"] == "yes",
        instance=json.loads(fields["instance"]),
    )


def _timer_values(status: TimerStatus) -> dict[str, Any]:
    dph = status.instance["dph_total"]
    if status.deadline is None:
        deadline = "off - the instance runs until you destroy it"
        max_cost = f"unbounded (${dph:.3f}/h)"
    else:
        left_s = max(status.deadline - status.now, 0)
        local_deadline = datetime.fromtimestamp(time.time() + left_s)
        deadline = (
            f"{local_deadline:%H:%M:%S} local time, in {_format_duration(left_s)}"
        )
        max_cost = f"${dph * left_s / 3600:.2f} more at ${dph:.3f}/h"
    return {
        "instance": status.instance["instance_id"],
        "timer": deadline,
        "cost until timer": max_cost,
        "watchdog": "running" if status.watchdog_alive else "NOT RUNNING",
    }


def _format_duration(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    return f"{hours}h{rest // 60:02d}m" if hours else f"{rest // 60}m{rest % 60:02d}s"


# --------------------------------------------------------------------------------------------
# Config, offers, blacklist
# --------------------------------------------------------------------------------------------


def _vastai(args: list[str], raw: bool = True) -> Any:
    """Run a vastai CLI command, parsing its JSON output when raw.

    Under `--raw` the CLI reports an API failure by printing a JSON error object to stderr and
    exiting 0 with an empty stdout, so empty stdout means the command failed rather than that it
    found nothing. Only the leading tokens of a failed command are reported, to keep anything
    passed in later arguments out of the error.

    stdin is closed because stdout is captured: a command that prompts for confirmation (e.g.
    `destroy instance` without `-y`) would otherwise wait on an invisible prompt forever. With
    no stdin the prompt aborts at once - but the CLI still exits 0, so such commands must check
    their output (see `_destroy_instance`).
    """
    cmd = ["vastai", *args, "--raw"] if raw else ["vastai", *args]
    result = subprocess.run(
        cmd, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    if not raw:
        return result.stdout
    stdout = result.stdout.strip()
    redacted_command = shlex.join(["vastai", *args[:3]])
    assert stdout, (
        f"`{redacted_command}` failed: {result.stderr.strip() or 'no error message'}"
    )
    return json.loads(stdout)


def _resolve_config_path(config: str) -> Path:
    """'h200' -> src/ic_eval/vast_configs/h200.yaml; anything with a '/' or '.yaml' is a path."""
    if "/" in config or config.endswith((".yaml", ".yml")):
        path = Path(config)
        return path if path.is_absolute() else Path.cwd() / path
    return CONFIG_DIR / f"{config}.yaml"


def _load_vast_config(config: str, overrides: dict[str, Any]) -> VastConfig:
    """Load the machine config, applying any flags the caller passed explicitly."""
    config_path = _resolve_config_path(config)
    available = sorted(p.stem for p in CONFIG_DIR.glob("*.yaml") if p != BLACKLIST_PATH)
    assert config_path.exists(), (
        f"vast config not found: {config_path}\nAvailable: {', '.join(available)}"
    )
    _log(f"Machine config: {config_path}")
    vast_config = VastConfig.from_file(config_path)
    given = {k: v for k, v in overrides.items() if v is not None}
    if given:
        _log(f"Overriding {config_path.name}: {given}")
    # Rebuild rather than model_copy(update=...), which skips validation and would let a
    # mistyped flag (e.g. an offer id passed to --gpu_names) through into the offer search.
    return VastConfig(**{**vast_config.model_dump(), **given})


def _search_offers(config: VastConfig, blacklisted: list[int]) -> list[Any]:
    """Search offers in the config's sort order; the caller rents the first available one.

    `disk_space` is the machine's free disk, which must fit the disk we intend to rent.
    `direct_port_count>=1` is required for the `--direct` ssh this module relies on. `gpu_ram` is
    queried in GB even though offers report it in MB. The datacenter term is added only when
    required, because `datacenter=false` would restrict the search to non-datacenter hosts instead
    of leaving it open. Blacklisted hosts are excluded in the query, so `n_offers` still counts
    rentable ones; `host_id` is missing from the CLI's documented query fields (it worked when
    tested by the SPD launcher on 26-10-06), so the result is checked for leaks too.
    """
    query = (
        f"num_gpus=1 gpu_name in [{','.join(config.gpu_names)}] rentable=true verified=true "
        f"reliability>{config.min_reliability} direct_port_count>=1 "
        f"cuda_max_good>={config.min_cuda} gpu_ram>={config.min_gpu_ram} "
        f"disk_space>={config.disk} dph_total<{config.max_price}"
    )
    if config.datacenter_only:
        query += " datacenter=true"
    if config.excluded_countries:
        query += f" geolocation notin [{','.join(config.excluded_countries)}]"
    if blacklisted:
        query += f" host_id notin [{','.join(map(str, blacklisted))}]"
    _log(f"Searching offers: {query}")
    found = _vastai(
        [
            "search",
            "offers",
            query,
            "-o",
            config.sort,
            "--limit",
            str(config.n_offers),
            # Price storage for the disk we actually rent; vast.ai otherwise quotes it for 5GiB
            "--storage",
            str(config.disk),
        ]
    )
    assert found, (
        "No offers matched. Raise max_price, lower min_gpu_ram/disk, or change gpu_names - "
        f"in the config or with the matching flag. {len(blacklisted)} hosts are excluded by "
        f"{BLACKLIST_PATH}."
    )
    wanted = {name.replace("_", " ") for name in config.gpu_names}
    for offer in found:
        assert offer["gpu_name"] in wanted, (
            f"Offer {offer['id']} has GPU {offer['gpu_name']!r}, not one of {sorted(wanted)}: "
            f"vast.ai ignored the gpu_name filter"
        )
        _assert_allowed_country(offer, config.excluded_countries)
    leaked = sorted({o["host_id"] for o in found} & set(blacklisted))
    assert not leaked, (
        f"vast.ai ignored the host_id exclusion and returned blacklisted hosts {leaked}"
    )
    return found


def _assert_allowed_country(offer: Any, excluded: list[str]) -> None:
    """vast.ai reports `geolocation` as 'Region, CC' (e.g. 'Jiangsu, CN'; SPD repo, 26-10-26)."""
    geo = offer["geolocation"]
    assert isinstance(geo, str) and ", " in geo, (
        f"Offer {offer['id']} has geolocation {geo!r}, expected 'Region, CC'; its country "
        f"cannot be checked against excluded_countries {excluded}"
    )
    country = geo.rsplit(", ", 1)[1]
    assert country not in excluded, (
        f"Offer {offer['id']} is in {geo}, an excluded country ({excluded}). Remove the country "
        f"from excluded_countries in the machine config to rent it anyway."
    )


def _find_offer(
    offer_id: int, blacklisted: list[int], excluded_countries: list[str], disk: int
) -> Any:
    """Look up one offer, for --offer_id, so its host is known and checked like a searched one.

    vast.ai's query language has no documented field for the offer id: `id=` matches nothing, and
    `ask_contract_id=` works but the CLI warns that it does not know the field. `-n` drops the
    CLI's default terms (rentable, verified, ...) so a hand-picked offer is not filtered out.
    `--storage` prices the disk we rent; without it the offer's `dph_total` covers only vast.ai's
    default 5 GB (seen 26-11-18: $0.456/h instead of the search's $0.490/h with 80 GB).
    """
    found = _vastai(
        [
            "search",
            "offers",
            "-n",
            f"ask_contract_id={offer_id}",
            "--storage",
            str(disk),
        ]
    )
    assert [int(o["id"]) for o in found] == [offer_id], (
        f"Looking up offer {offer_id} returned {[o['id'] for o in found]} - it is no longer on "
        f"the market, or vast.ai has changed how offers are looked up by id."
    )
    offer = found[0]
    assert offer["host_id"] not in blacklisted, (
        f"Offer {offer_id} is on blacklisted host {offer['host_id']}. Remove the host from "
        f"{BLACKLIST_PATH} to rent it anyway."
    )
    _assert_allowed_country(offer, excluded_countries)
    return offer


def _load_blacklist() -> VastBlacklist:
    assert BLACKLIST_PATH.exists(), f"Host blacklist not found: {BLACKLIST_PATH}"
    blacklist = VastBlacklist.from_file(BLACKLIST_PATH)
    host_ids = [h.host_id for h in blacklist.hosts]
    assert len(host_ids) == len(set(host_ids)), (
        f"Duplicate host ids in {BLACKLIST_PATH}"
    )
    return blacklist


def _blacklisted_host_ids(blacklist: VastBlacklist) -> list[int]:
    host_ids = sorted(h.host_id for h in blacklist.hosts)
    if host_ids:
        _log(
            f"Excluding {len(host_ids)} blacklisted hosts ({BLACKLIST_PATH}): {host_ids}"
        )
    return host_ids


def _add_to_blacklist(entry: BlacklistedHost) -> None:
    """Append a host to the git-tracked blacklist, so the next search skips it."""
    blacklist = _load_blacklist()
    assert entry.host_id not in {h.host_id for h in blacklist.hosts}, (
        f"Host {entry.host_id} failed but is already blacklisted - the search should have "
        f"excluded it"
    )
    hosts = [*blacklist.hosts, entry]
    BLACKLIST_PATH.write_text(
        BLACKLIST_HEADER
        + yaml.safe_dump(
            VastBlacklist(hosts=hosts).model_dump(mode="json"),
            sort_keys=False,
            width=100,
        )
    )
    _log(f"Blacklisted host {entry.host_id} in {BLACKLIST_PATH}: {entry.reason}")


def _print_offers(found: list[Any], sort: str, disk: int) -> None:
    """Print the offers as a table.

    'host' is the operator's host id, the unit the blacklist excludes. `gpu_ram` and `cpu_ram` are
    reported in MB, disk in GB. 'free' is the machine's unallocated disk, not the disk we rent -
    `$/hr` already covers the rented disk.
    """
    _section(
        f"{len(found)} matching offers, sorted by {sort}. $/hr includes the {disk}GB disk"
    )
    header = (
        f"{'id':>10} {'host':>7}  {'gpu':<16} {'vram':>5} {'$/hr':>6} {'free':>6} {'ram':>6} "
        f"{'cores':>5} {'cuda':>5} {'net↓':>7} {'dlperf':>7} {'dlperf/$':>8} {'reliab':>7}  "
        f"location"
    )
    rows = [
        f"{o['id']:>10} {o['host_id']:>7}  {o['gpu_name']:<16} {o['gpu_ram'] / 1024:>4.0f}G "
        f"{o['dph_total']:>6.3f} {o['disk_space']:>5.0f}G {o['cpu_ram'] / 1024:>5.0f}G "
        f"{o['cpu_cores_effective']:>5.1f} {o['cuda_max_good']:>5.1f} "
        f"{o['inet_down']:>6.0f}M {o['dlperf']:>7.1f} {o['dlperf_per_dphtotal']:>8.1f} "
        f"{o['reliability']:>7.4f}  {o['geolocation']}"
        for o in found
    ]
    print("\n".join([header, *rows]), flush=True)


# --------------------------------------------------------------------------------------------
# Renting and booting
# --------------------------------------------------------------------------------------------


def _create_instance_args(offer_id: int, config: VastConfig, label: str) -> list[str]:
    """Arguments for `vastai create instance`.

    Intentionally no `--env`: vast.ai stores those values in the instance's metadata on its
    servers, so secrets must never go there (docs/CODING.md, *Rented vast.ai GPUs*).
    """
    return [
        "create",
        "instance",
        str(offer_id),
        "--image",
        config.image,
        "--disk",
        str(config.disk),
        "--ssh",
        "--direct",
        "--label",
        label,
        "--cancel-unavail",
    ]


def _rent_first_available(
    found: list[Any], config: VastConfig, label: str
) -> tuple[int, Any]:
    """Rent the best offer still on the market, walking down the search order.

    Returns the instance id and the offer it was rented from (whose host gets blacklisted if the
    rental fails).

    vast.ai's offer search serves asks that are no longer available - rented by someone else, or
    withdrawn without being rented (e.g. the host went offline) - so the top offer is regularly
    gone by the time we ask for it. Only an unavailable offer moves us on to the next one; any
    other create failure is ours and is raised.
    """
    for offer in found:
        offer_id = int(offer["id"])
        _log(
            f"Renting offer {offer_id}: {offer['gpu_name']} at ${offer['dph_total']:.3f}/hr "
            f"in {offer['geolocation']} (reliability {offer['reliability']:.4f}, host "
            f"{offer['host_id']})"
        )
        instance_id = _create_instance(_create_instance_args(offer_id, config, label))
        if instance_id is not None:
            return instance_id, offer
        _log(
            f"Offer {offer_id} (host {offer['host_id']}) is not available - rented by someone "
            f"else or withdrawn by its host - trying the next one"
        )
    raise AssertionError(
        f"None of the {len(found)} matching offers was available: each was rented by someone "
        f"else or withdrawn by its host. Rent again - the search index lags the marketplace by "
        f"minutes, so a fresh search lists different asks."
    )


def _create_instance(create_args: list[str]) -> int | None:
    """Rent an offer, returning None if it is not available. Nothing is rented on failure.

    `--cancel-unavail` makes vast.ai reject an unavailable ask outright instead of parking a
    stopped instance on us, and it reports that as `no_such_ask` - both for an ask someone else
    rented and for one that is unavailable without being rented. This does not go through
    `_vastai` because an unavailable ask is an expected outcome here rather than an error.
    """
    result = subprocess.run(
        ["vastai", *create_args, "--raw"],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    stdout = result.stdout.strip()
    if not stdout:
        stderr = result.stderr.strip()
        assert TAKEN_OFFER_ERROR in stderr, (
            f"`vastai create instance` failed: {stderr or 'no error message'}"
        )
        return None
    created = json.loads(stdout)
    assert created["success"], f"Failed to create instance: {created}"
    return int(created["new_contract"])


def _destroy_instance(instance_id: int) -> None:
    """Destroy an instance, failing loudly unless vast.ai confirms it.

    The CLI exits 0 whatever happens: on success it prints "destroying instance <id>.", on an
    unknown instance "Failed with error 404: ..." (to stderr), and without `-y` it prompts, reads
    a closed stdin and prints "Aborted." [all observed with vastai 1.2.0 by the SPD launcher on
    26-10-06]. So the output, both streams, is the only signal. A 404 is the one failure to
    accept, because an instance whose host dropped it is already gone (see `_show_instance`).
    """
    _log(f"Destroying instance {instance_id}")
    result = subprocess.run(
        ["vastai", "destroy", "instance", str(instance_id), "-y"],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    output = (result.stdout + result.stderr).strip()
    _log(output)
    assert output == f"destroying instance {instance_id}." or "error 404" in output, (
        f"vast.ai did not confirm destroying instance {instance_id} ({output!r}), so it may still "
        f"be billing. Check `vastai show instances` and destroy it with: "
        f"vastai destroy instance {instance_id} -y"
    )


def _show_instance(instance_id: int) -> dict[str, Any]:
    """Look an instance up, failing loudly if it has vanished.

    An instance whose host drops it stops existing rather than reporting a dead status, and
    `show instance` answers for it with `{"instances": null}` instead of the flat instance dict.
    """
    shown = _vastai(["show", "instance", str(instance_id)])
    if "actual_status" not in shown:
        raise HostFailure(
            "host dropped the rental",
            f"Instance {instance_id} no longer exists ({shown}). Its host dropped it, which "
            f"vast.ai reports by forgetting the rental rather than by marking it dead. Rent "
            f"again to land on a different host.",
        )
    return shown


def _wait_until_running(instance_id: int) -> None:
    """Poll the boot, logging the status only when it changes (it repeats for minutes)."""
    deadline = time.time() + READY_TIMEOUT_S
    last_seen = None
    while time.time() < deadline:
        instance = _show_instance(instance_id)
        status, message = instance["actual_status"], instance["status_msg"]
        if status == "running":
            return
        if status in DEAD_STATUSES:
            raise HostFailure(
                f"instance went '{status}' while booting",
                f"Instance {instance_id} is '{status}' ({message}). The host has dropped off "
                f"vast.ai's control plane and will never install your ssh key.",
            )
        if message and DNS_FAILURE_MARKER in message:
            raise HostFailure(
                f"DNS failure while booting: {message}",
                f"Instance {instance_id} cannot resolve vast.ai's servers ({message}), so it "
                f"will never finish booting.",
            )
        if (status, message) != last_seen:
            _log(f"Instance status: {status} ({message})")
            last_seen = (status, message)
        time.sleep(POLL_INTERVAL_S)
    raise HostFailure(
        f"not running after {READY_TIMEOUT_S}s",
        f"Instance {instance_id} not running after {READY_TIMEOUT_S}s.",
    )


# --------------------------------------------------------------------------------------------
# ssh
# --------------------------------------------------------------------------------------------


def _ssh_identity_file() -> Path:
    """The private key ssh authenticates to rented machines with.

    The path is machine-specific but not secret, so it lives in the gitignored `.env` (or the
    environment) rather than in the git-tracked machine configs.
    """
    # .get: an unset VAST_SSH_KEY is the normal case and means the default key.
    configured = dotenv_values(REPO_ROOT / ".env").get(
        "VAST_SSH_KEY"
    ) or os.environ.get("VAST_SSH_KEY")
    key = Path(configured).expanduser() if configured else DEFAULT_SSH_IDENTITY_FILE
    assert key.exists(), f"ssh key not found: {key}. Set VAST_SSH_KEY in .env."
    return key


def _public_key_path(identity_file: Path) -> Path:
    """OpenSSH appends `.pub` to the whole filename, so `vast.key` pairs with `vast.key.pub`."""
    return identity_file.with_name(identity_file.name + ".pub")


def _attach_ssh_key(instance_id: int, identity_file: Path) -> None:
    """Push our public key to the instance through vast.ai's control plane.

    vast.ai's entrypoint copies account-level keys into authorized_keys at container start, but on
    some hosts that is slow or never happens, and there is no way in to fix it by hand. Attaching
    is idempotent, so it runs on every rental rather than only on the ones that turn out to need
    it.
    """
    public_key = _public_key_path(identity_file)
    assert public_key.exists(), f"public key not found: {public_key}"
    _vastai(
        ["attach", "ssh", str(instance_id), public_key.read_text().strip()], raw=False
    )


def _ssh_host_port(instance_id: int) -> tuple[str, int]:
    """Parse `vastai ssh-url`, which reports the right host/port for direct or proxied ssh."""
    ssh_url = _vastai(["ssh-url", str(instance_id)], raw=False).strip()
    assert ssh_url.startswith("ssh://"), f"Unexpected ssh url: {ssh_url}"
    host_port = ssh_url.removeprefix("ssh://").split("@")[-1]
    host, port = host_port.split(":")
    return host, int(port)


def _write_ssh_config(
    host: str, port: int, instance_id: int, identity_file: Path
) -> None:
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
    )
    resolved = subprocess.check_output(
        ["ssh", "-G", SSH_HOST_ALIAS], text=True
    ).splitlines()
    assert f"hostname {host}" in resolved and f"port {port}" in resolved, (
        f"ssh does not pick up {SSH_CONFIG_PATH}: `ssh -G {SSH_HOST_ALIAS}` resolves to "
        f"{[line for line in resolved if line.startswith(('hostname ', 'port '))]}. Add "
        f"`Include ~/.ssh/config.d/*` at the top of ~/.ssh/config."
    )


def _wait_until_ssh_ready(instance_id: int, identity_file: Path) -> None:
    """Poll until sshd accepts our key, re-attaching it once halfway through.

    `actual_status == "running"` only means the container started: vast.ai's entrypoint installs
    authorized_keys a few seconds later, and connections made before that are closed mid-auth. A
    host that rejects the key is not a lost cause either - the same key is often accepted minutes
    later - so the loop keeps polling through "Permission denied" and re-attaches once in case the
    entrypoint overwrote authorized_keys after we first attached.
    """
    _log("Waiting for ssh to accept our key")
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
            _log(f"ssh still failing ({last_error}) - re-attaching the key")
            _attach_ssh_key(instance_id, identity_file)
            reattached = True
        time.sleep(SSH_POLL_INTERVAL_S)
    status = _show_instance(instance_id)["actual_status"]
    if status in DEAD_STATUSES:
        raise HostFailure(
            f"instance went '{status}' while waiting for ssh",
            f"Instance {instance_id} went '{status}' while we waited for ssh. The host dropped "
            f"off vast.ai's control plane after reporting itself running, so it never installed "
            f"your key - the rejection is the host's fault, not your key's.",
        )
    cause = ""
    if "Permission denied" in last_error:
        # check=False: diagnostics only; the HostFailure below is raised either way.
        logs = subprocess.run(
            ["vastai", "logs", str(instance_id)],
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        if BAD_KEY_MODES_MARKER in logs.stdout + logs.stderr:
            cause = f"; sshd: '{BAD_KEY_MODES_MARKER}' of authorized_keys (host fault)"
    # Blacklisted although a broken local key would fail the same way: a key that works on other
    # hosts is far more common, and the first blacklisted host would reveal a broken one.
    raise HostFailure(
        f"ssh failing after {SSH_READY_TIMEOUT_S}s: {last_error.splitlines()[-1]}{cause}",
        f"ssh to {SSH_HOST_ALIAS} still failing after {SSH_READY_TIMEOUT_S}s while instance "
        f"{instance_id} reports '{status}'{cause}.\n"
        f"Last ssh error: {last_error}\n"
        f"'Permission denied (publickey)' means sshd is up but never took the key in "
        f"{identity_file}; a refused or timed out connection means the direct port mapping never "
        f"came up. Read the entrypoint's own account with: vastai logs {instance_id}",
    )


def _ssh(remote_command: str) -> None:
    subprocess.run(
        ["ssh", *SSH_OPTS, SSH_HOST_ALIAS, remote_command],
        check=True,
        stdin=subprocess.DEVNULL,
    )


def _ssh_output(remote_command: str) -> str:
    return subprocess.run(
        ["ssh", *SSH_OPTS, SSH_HOST_ALIAS, remote_command],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    ).stdout


def _ssh_input(remote_command: str, text: str) -> None:
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


def _ssh_detached(remote_command: str) -> None:
    """Start a remote background command and return at once (see `_start_watchdog`)."""
    subprocess.run(
        ["ssh", *SSH_OPTS, "-n", "-f", SSH_HOST_ALIAS, remote_command],
        check=True,
        stdin=subprocess.DEVNULL,
    )


# --------------------------------------------------------------------------------------------
# Code sync and scripts
# --------------------------------------------------------------------------------------------


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(REPO_ROOT), *args], text=True
    ).strip()


def _local_git_state() -> LocalGitState:
    """Read the local branch and HEAD commit, asserting the instance can fetch that commit.

    The instance clones from `origin` over https without credentials, so `origin` must be a public
    https remote and HEAD must be on one of its branches. The check reads our remote-tracking refs
    (as of the last fetch/push); a commit missing on GitHub after all still fails on the instance,
    in `git update-ref`.
    """
    origin_url = _git("remote", "get-url", "origin")
    assert origin_url.startswith("https://"), (
        f"origin is {origin_url}; the instance clones it without credentials, so it must be https"
    )
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    assert branch != "HEAD", (
        "Detached HEAD: check out a branch, the instance is put on it"
    )
    commit = _git("rev-parse", "HEAD")
    assert _git("branch", "-r", "--list", "origin/*", "--contains", commit), (
        f"HEAD {commit[:8]} is on no origin branch: push it first. The instance gets the git "
        f"history from {origin_url}; only the working tree is uploaded."
    )
    return LocalGitState(origin_url=origin_url, branch=branch, commit=commit)


def _build_checkout_script(git_state: LocalGitState) -> str:
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


def _rsync_args() -> list[str]:
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
        "--info=progress2",
        "--filter=:- .gitignore",
        "--exclude=/.git/",
        "--exclude=.venv",
        "-e",
        shlex.join(["ssh", *SSH_OPTS]),
        f"{REPO_ROOT}/",
        f"{SSH_HOST_ALIAS}:{REMOTE_REPO_DIR}/",
    ]


def _sync_repo(git_state: LocalGitState) -> None:
    _log(
        f"Fetching {git_state.branch} @ {git_state.commit[:8]} on the instance from GitHub"
    )
    _ssh(f"bash -c {shlex.quote(_build_checkout_script(git_state))}")
    args = _rsync_args()
    _log(f"Syncing working tree: {shlex.join(args)}")
    subprocess.run(args, check=True, stdin=subprocess.DEVNULL)


def _check_script(script: str) -> None:
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
    assert ignored.returncode == 1, (
        f"{script} is gitignored, so the rsync would not upload it"
    )


def _build_script_command(script: str, destroy_on_exit: bool, log_path: str) -> str:
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


def _launch_script(script: str, destroy_on_exit: bool) -> str:
    """Start the script detached; returns the remote log path."""
    log_path = f"{REMOTE_SCRIPT_LOG_DIR}/{Path(script).stem}_{datetime.now():%y%m%d_%H%M%S}.log"
    _ssh_detached(_build_script_command(script, destroy_on_exit, log_path))
    return log_path


# --------------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------------


def _machine_info() -> dict[str, str]:
    """GPU power limit and CPU quota, the two host settings that silently slowed SPD runs.

    A 500 W H100 ran 40% slower than a ~600 W one; a container with a 23-CPU quota on a 192-core
    host throttled CPU-heavy jobs (SPD repo, 26-10-03 and 26-11-16).
    """
    gpu = _ssh_output(
        "nvidia-smi --query-gpu=name,memory.total,power.limit --format=csv,noheader"
    ).strip()
    cpu = _ssh_output(
        'echo "quota $(cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo unknown), nproc $(nproc)"'
    ).strip()
    return {"gpu (nvidia-smi)": gpu, "cpu (cgroup quota/period)": cpu}


def _log_summary(instance_id: int, offer: Any, status: TimerStatus) -> None:
    _section("vast.ai instance ready")
    _values(
        {
            "instance": instance_id,
            "host": f"{offer['host_id']} (machine {offer['machine_id']}, {offer['geolocation']})",
            "price": f"${offer['dph_total']:.3f}/h including disk",
            **{k: v for k, v in _timer_values(status).items() if k != "instance"},
            **_machine_info(),
            "ssh": f"ssh {SSH_HOST_ALIAS}",
            "tunnel": f"ssh -N -L 8000:localhost:8000 {SSH_HOST_ALIAS}",
            "change timer": "ic-vast timer [2h|90m|off]",
            "logs": f"vastai logs {instance_id}",
            "destroy": f"vastai destroy instance {instance_id} -y",
        }
    )


def _log(message: str) -> None:
    print(f"[ic-vast {datetime.now():%H:%M:%S}] {message}", flush=True)


def _section(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def _values(values: dict[str, Any]) -> None:
    width = max(len(k) for k in values)
    for key, value in values.items():
        lines = str(value).splitlines() or [""]
        print(f"  {key:<{width}}  {lines[0]}", flush=True)
        for line in lines[1:]:
            print(f"  {'':<{width}}  {line}", flush=True)


def cli() -> None:
    fire.Fire({"rent": rent, "offers": offers, "timer": timer_command})


if __name__ == "__main__":
    cli()
