"""The `ic-vast` command: rent and prepare vast.ai GPUs, choosing hosts from past rentals.

    ic-vast offers                        # score the market, rent nothing
    ic-vast rent                          # rent + prepare (default config 48gb, mode balance)
    ic-vast rent --mode hedge             # when watching: avoid failures and long waits
    ic-vast rent --mode explore           # try little-known hosts; run it when you're away
    ic-vast rent --mode exploit           # lowest expected cost, no exploration
    ic-vast rent --config h200 --hours 4  # src/ic_eval/vast/configs/h200.yaml, 4 h session
    ic-vast rent --offer_id 123           # this offer, no choice, no re-rent
    ic-vast rent --script scripts/vm/x.sh # ... then run that repo script on the instance
    ic-vast rent --script scripts/vm/x.sh --script_args "a b"  # ... with arguments
    ic-vast rent --dry_run                # show the choice, rent nothing
    ic-vast timer [2h|90m|off]            # show or change the self-destruct timer
    ic-vast sync [--allow_delete]         # upload the working tree again (HEAD must be pushed)
    ic-vast destroy                       # end the session: record it, destroy the instance
    ic-vast stats                         # what the model has learned, and how calibrated it is

Each rented instance is recorded in src/ic_eval/vast/data/rentals.jsonl (records.py), whatever
its outcome; the model (model.py) learns from that history, the policy (policy.py) chooses with
it, and a slow or failed host is given up on and the next offer rented automatically.
"""

import json
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

import fire
import numpy as np

from ic_eval.vast import sshmodes
from ic_eval.vast.boot import BootResult, wait_for_boot
from ic_eval.vast.common import CURRENT_INSTANCE_PATH, HostFailure, log, section, values
from ic_eval.vast.config import (
    MachineConfig,
    PolicyConfig,
    load_machine_config,
    load_policy_config,
)
from ic_eval.vast.image import Layer, fetch_layers
from ic_eval.vast.market import (
    check_cli,
    create_instance,
    destroy_instance,
    find_offer,
    search_offers,
    show_instance,
)
from ic_eval.vast.model import (
    Posterior,
    cache_eligible_hosts,
    fit,
    host_draws,
    observations_from_records,
)
from ic_eval.vast.policy import (
    MODES,
    AbortRule,
    Evaluation,
    Mode,
    abort_rule,
    candidate_scores,
    evaluate,
    mode_settings,
    next_best_setup,
    select,
)
from ic_eval.vast.probes import run_probes, summary_lines
from ic_eval.vast.pull import replay
from ic_eval.vast.records import (
    SCHEMA_VERSION,
    Attempt,
    End,
    PullStats,
    Selection,
    append_record,
    load_records,
)
from ic_eval.vast.remote import (
    REMOTE_REPO_DIR,
    SSH_HOST_ALIAS,
    SSH_OPTS,
    TIMER_LOG,
    LocalGitState,
    attach_ssh_key,
    check_script,
    files_a_sync_would_delete,
    install_watchdog,
    launch_script,
    local_git_state,
    parse_duration,
    set_timer,
    ssh_host_port,
    ssh_identity_file,
    start_watchdog,
    sync_repo,
    timer_status,
    timer_values,
    wait_until_ssh_ready,
    write_ssh_config,
)

DEFAULT_CONFIG = "48gb"
DEFAULT_MODE: Mode = "balance"
# Bound on offers found taken between search and rent within one attempt (the search index lags
# the market by minutes, so a few are normal; dozens would mean something else is wrong).
MAX_TAKEN_OFFERS = 10


class Scored(NamedTuple):
    evaluation: Evaluation
    posterior: Posterior
    chosen: int
    propensities: np.ndarray
    selection: Selection
    rule: AbortRule


# --------------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------------


def offers(
    config: str = DEFAULT_CONFIG,
    mode: str = DEFAULT_MODE,
    hours: float | None = None,
    gpu_names: list[str] | None = None,
    max_price: float | None = None,
    min_gpu_ram: int | None = None,
    disk: int | None = None,
) -> None:
    """Score every matching offer with the host model and show the mode's choice; rent nothing.

    Args:
        config: Machine config: a short name ('h200' -> configs/h200.yaml) or a YAML path.
        mode: exploit | balance | explore | hedge (see `ic-vast rent --help`).
        hours: Planned session length; default from the machine config.
        gpu_names: Override the config's gpu_names, e.g. '[A100_SXM4]'.
        max_price: Override the config's max_price ($/h including disk).
        min_gpu_ram: Override the config's min_gpu_ram (GB).
        disk: Override the config's disk (GB).
    """
    checked_mode = _check_mode(mode)
    machine = load_machine_config(
        config,
        {
            "gpu_names": gpu_names,
            "max_price": max_price,
            "min_gpu_ram": min_gpu_ram,
            "disk": disk,
        },
    )
    policy = load_policy_config()
    log(f"vastai CLI {check_cli()}")
    layers = fetch_layers(machine.image)
    found = search_offers(machine)
    scored = _score(found, machine, policy, checked_mode, hours, layers, np.random.default_rng())
    _print_candidates(scored, limit=40)


def rent(
    script: str | None = None,
    script_args: str | None = None,
    config: str = DEFAULT_CONFIG,
    mode: str = DEFAULT_MODE,
    hours: float | None = None,
    offer_id: int | None = None,
    timer: str | None = None,
    destroy_on_exit: bool = False,
    skip_probes: bool = False,
    dry_run: bool = False,
    gpu_names: list[str] | None = None,
    max_price: float | None = None,
    min_gpu_ram: int | None = None,
    disk: int | None = None,
    image: str | None = None,
) -> None:
    """Choose an offer with the host model, rent it, prepare it; re-rent if the host fails.

    Preparing means: ssh alias `bluedot-vast`, self-destruct watchdog running with the timer set,
    repo cloned from GitHub and the local working tree rsynced over it (/root/bluedot), probes run.
    The local HEAD commit must be pushed to origin. A host that boots too slowly (predicted by the
    live pull speed) or fails is recorded, destroyed, and the next offer rented, up to
    max_attempts (configs/policy.yaml).

    Args:
        script: Repo-relative bash script (.sh, by convention in scripts/vm/) to run on the
            instance once ready, detached, in a login shell from /root/bluedot; output in
            /root/bluedot/logs/remote/.
        script_args: Arguments for the script, as one shell-quoted string (split with shlex),
            e.g. 'allenai/Olmo-3-7B-Think-SFT main' for scripts/vm/serve_vllm.sh.
        config: Machine config: a short name ('h200' -> configs/h200.yaml) or a YAML path.
        mode: How to choose among offers. exploit: lowest expected cost. balance (default):
            mostly exploit, now and then try a host the model knows little about. explore: try
            uncertain hosts deliberately; run it when away, as a slow host costs little then.
            hedge: avoid failures and long waits (for watching).
        hours: Planned session length, weighs price against setup time; default from config.
        offer_id: Rent exactly this offer: no choice, no re-rent (recorded as mode 'manual').
        timer: Self-destruct timer, e.g. '2h', '90m' or 'off'; default from the config.
        destroy_on_exit: With --script: destroy the instance (through the timer) when it ends.
        skip_probes: Skip the ~45 s of probes after ready (they feed the host records).
        dry_run: Show the choice, rent nothing.
        gpu_names: Override the config's gpu_names, e.g. '[A100_SXM4]'.
        max_price: Override the config's max_price ($/h including disk).
        min_gpu_ram: Override the config's min_gpu_ram (GB).
        disk: Override the config's disk (GB).
        image: Override the config's image.
    """
    checked_mode = _check_mode(mode)
    machine = load_machine_config(
        config,
        {
            "gpu_names": gpu_names,
            "max_price": max_price,
            "min_gpu_ram": min_gpu_ram,
            "disk": disk,
            "image": image,
            "timer": timer,
        },
    )
    policy = load_policy_config()
    timer_s = parse_duration(machine.timer)
    assert not (destroy_on_exit and script is None), "--destroy_on_exit needs --script"
    assert not (script_args is not None and script is None), "--script_args needs --script"
    # fire turns values that look like Python literals into numbers or lists; only a string is
    # meant here, so anything else is a quoting mistake on the command line.
    assert script_args is None or isinstance(script_args, str), (
        f"--script_args must be one string, got {script_args!r}"
    )
    script_argv = shlex.split(script_args) if script_args is not None else []
    if script is not None:
        check_script(script)
    log(f"vastai CLI {check_cli()}")
    if not dry_run:
        _forget_instance_if_gone()
    identity_file = ssh_identity_file()
    git_state = local_git_state()  # checked before renting, so an unpushed commit costs nothing
    layers = fetch_layers(machine.image)
    log(f"Image {machine.image}: {len(layers)} layers, {sum(x.size for x in layers) / 1e9:.2f} GB")
    rng = np.random.default_rng()
    session_id = datetime.now().strftime("%y%m%d-%H%M%S")
    label = f"ic-eval-{session_id}"
    max_attempts = 1 if offer_id is not None else policy.max_attempts
    excluded_hosts: set[int] = set()
    taken_offers: set[int] = set()
    boot_spent_s = 0.0
    attempt_index = 0

    while attempt_index < max_attempts:
        if offer_id is not None:
            found = [find_offer(offer_id, machine)]
        else:
            found = [
                o
                for o in search_offers(machine)
                if int(o["host_id"]) not in excluded_hosts and int(o["id"]) not in taken_offers
            ]
            assert found, f"no offers left after excluding hosts {sorted(excluded_hosts)}"
        scored = _score(
            found,
            machine,
            policy,
            checked_mode,
            hours,
            layers,
            rng,
            manual=offer_id is not None,
        )
        _print_candidates(scored, limit=10)
        offer = scored.evaluation.offers[scored.chosen]
        if dry_run:
            log("Dry run - nothing rented")
            return
        log(
            f"Attempt {attempt_index + 1}/{max_attempts}: renting offer {offer['id']} on host "
            f"{offer['host_id']} ({offer['gpu_name']}, ${offer['dph_total']:.3f}/h, "
            f"{offer['geolocation']})"
        )
        instance_id = create_instance(int(offer["id"]), machine, label, sshmodes.onstart_script())
        if instance_id is None:
            log(f"Offer {offer['id']} is not available any more (rented or withdrawn); rechoosing")
            taken_offers.add(int(offer["id"]))
            assert len(taken_offers) <= MAX_TAKEN_OFFERS, (
                f"{len(taken_offers)} offers were gone by the time they were rented"
            )
            continue
        created_at = time.time()
        total_left_s = policy.max_total_boot_minutes * 60 - boot_spent_s
        log(
            f"Created instance {instance_id}; boot caps: pull {policy.max_pull_minutes:g} min, "
            f"then build {policy.max_build_minutes:g} min, {total_left_s / 60:.1f} min in total"
        )
        done = _run_attempt(
            instance_id=instance_id,
            created_at=created_at,
            offer=offer,
            scored=scored,
            session_id=session_id,
            attempt_index=attempt_index,
            config=config,
            machine=machine,
            policy=policy,
            layers=layers,
            total_left_s=total_left_s,
            identity_file=identity_file,
            git_state=git_state,
            timer_s=timer_s,
            script=script,
            script_argv=script_argv,
            destroy_on_exit=destroy_on_exit,
            skip_probes=skip_probes,
        )
        boot_spent_s += time.time() - created_at
        if done:
            return
        excluded_hosts.add(int(offer["host_id"]))
        attempt_index += 1
        remaining_s = policy.max_total_boot_minutes * 60 - boot_spent_s
        if attempt_index < max_attempts and remaining_s < 60:
            raise AssertionError(
                f"Boot budget used up ({policy.max_total_boot_minutes} min over "
                f"{attempt_index} attempts); no machine. Rent again to start a new budget."
            )
    raise AssertionError(f"No usable machine after {max_attempts} attempt(s); see the log above.")


def timer_command(duration: str | None = None) -> None:
    """Show, set or switch off the self-destruct timer of the instance behind `bluedot-vast`.

    Restarts the watchdog if it is not running.

    Args:
        duration: '2h' or '90m' sets the deadline to that long from now (replacing any earlier
            one); 'off' removes it. Omit it to only show the timer.
    """
    assert CURRENT_INSTANCE_PATH.exists(), "no current instance - rent one first"
    if duration is not None:
        set_timer(parse_duration(duration))
    status = timer_status()
    if not status.watchdog_alive:
        log("The watchdog is not running on the instance - restarting it")
        start_watchdog()
        status = timer_status()
    section("Self-destruct timer")
    values(timer_values(status))


def sync(allow_delete: bool = False) -> None:
    """Upload the local working tree to the current instance again, as `rent` did at rent time.

    The same two steps: the instance's clone is put on our branch and HEAD commit (fetched from
    GitHub, so HEAD must be pushed), then rsync makes its files match our working tree,
    uncommitted changes included. Edits made on the instance to files we also have are
    overwritten. Only files change: a process already running there keeps the code it started
    with.

    rsync runs with --delete, so files on the instance that we don't have are removed unless the
    instance's .gitignore covers them. At rent time that only affects the fresh clone; on a used
    instance it can hit outputs written to tracked paths. So a dry run comes first, and if it
    would delete anything the sync stops and lists the paths.

    Args:
        allow_delete: Go ahead even if the sync deletes files on the instance.
    """
    assert CURRENT_INSTANCE_PATH.exists(), "no current instance - rent one first"
    git_state = local_git_state()
    doomed = files_a_sync_would_delete()
    if doomed:
        log(f"The sync would delete {len(doomed)} path(s) on the instance:")
        for path in doomed:
            log(f"  {REMOTE_REPO_DIR}/{path}")
        assert allow_delete, "Not syncing. Copy what you need first, or pass --allow_delete."
    sync_repo(git_state)


def destroy() -> None:
    """End the current session: record how it went (container restarts), destroy the instance.

    If the instance is unreachable (its timer or host already ended it), the end is recorded as
    such and the destroy still runs (vast.ai answers 404 for a gone instance, which is accepted).
    """
    assert CURRENT_INSTANCE_PATH.exists(), "no current instance recorded - nothing to destroy"
    state = json.loads(CURRENT_INSTANCE_PATH.read_text())
    instance_id = int(state["instance_id"])
    probe = subprocess.run(
        [
            "ssh",
            *SSH_OPTS,
            "-o",
            "ConnectTimeout=15",
            SSH_HOST_ALIAS,
            f"grep -c 'watchdog started' {TIMER_LOG}",
        ],
        check=False,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    if probe.returncode == 0:
        reason, starts, detail = "destroyed", int(probe.stdout.strip()), None
        if starts > 1:
            log(f"The container restarted {starts - 1} time(s) during the session")
    else:
        reason, starts = "unreachable", None
        detail = probe.stderr.strip()[-300:] or f"ssh exit {probe.returncode}"
        log(f"Instance unreachable ({detail}); recording that and destroying anyway")
    destroy_instance(instance_id)
    append_record(
        End(
            kind="end",
            schema_version=SCHEMA_VERSION,
            instance_id=instance_id,
            ended_at=time.time(),
            reason=reason,
            watchdog_starts=starts,
            detail=detail,
        )
    )
    CURRENT_INSTANCE_PATH.unlink()


def stats() -> None:
    """What the model has learned from the rental history, and how well calibrated it is."""
    policy = load_policy_config()
    records = load_records()
    attempts = [r for r in records if isinstance(r, Attempt)]
    now = time.time()
    rng = np.random.default_rng()
    obs = observations_from_records(
        records, now, policy.cache_window_days, policy.abort_warmup_seconds
    )
    posterior = _fit(obs, policy, "balance", rng)
    section(f"History: {len(attempts)} attempts, {len(records) - len(attempts)} session ends")
    for a in attempts:
        setup = f"{(a.ready_at - a.created_at) / 60:.1f} min" if a.ready_at else "-"
        speed = _replayed_speed(a)
        print(
            f"  {datetime.fromtimestamp(a.created_at):%y-%m-%d %H:%M}  host {a.offer['host_id']:>7}"
            f"  {a.offer['gpu_name']:<13} {a.selection.mode:<8} {a.outcome:<13}"
            f" {a.failure_type or '':<12} pull {speed:>11}  setup {setup}"
        )
    section("Shared parameters (posterior mean [10%, 90%])")
    values(
        {
            "speed at 1000 Mbit/s adv.": _interval(np.exp(posterior.alpha), "MB/s"),
            "beta (adv. speed effect)": _interval(posterior.beta, ""),
            "host spread tau": _interval(np.sqrt(posterior.tau2), "(log)"),
            "day spread sigma": _interval(np.sqrt(posterior.sigma2), "(log)"),
            "overhead": _interval(np.exp(posterior.overhead_mu), "min"),
            "cache hit prob.": _interval(posterior.cache_pi, ""),
            "failure rate (pooled)": _interval(posterior.failure_mean, ""),
        }
    )
    hosts = sorted({int(a.offer["host_id"]) for a in attempts})
    if hosts:
        section("Hosts")
        for host in hosts:
            draws = host_draws(posterior, host, obs.advertised_mbps[host], rng)
            print(
                f"  host {host:>7}  speed {_interval(np.exp(draws.log_speed), 'MB/s'):<28}"
                f"  failure {draws.failure_prob.mean():.2f}"
                f"  effective obs {draws.effective_observations:.1f}"
            )
    section("Calibration: actual setup time inside the predicted 10-90% interval")
    inside = 0
    checked = 0
    unpredicted = 0
    for a in attempts:
        if a.outcome != "ready" or a.ready_at is None:
            continue
        if not a.selection.candidates:
            # Backfilled from before the model existed (26-11-18): nothing was predicted.
            unpredicted += 1
            continue
        chosen = [c for c in a.selection.candidates if c.offer_id == int(a.offer["id"])]
        assert len(chosen) == 1, f"attempt {a.instance_id}: chosen offer not among candidates"
        actual = (a.ready_at - a.created_at) / 60
        hit = chosen[0].setup_p10_min <= actual <= chosen[0].setup_p90_min
        inside += hit
        checked += 1
        print(
            f"  instance {a.instance_id}: actual {actual:.1f} min, predicted "
            f"[{chosen[0].setup_p10_min:.1f}, {chosen[0].setup_p90_min:.1f}] "
            f"{'inside' if hit else 'OUTSIDE'}"
        )
    print(
        f"  {inside}/{checked} inside (80% expected once there are enough rentals)"
        if checked
        else "  no ready rentals with a recorded prediction yet"
    )
    if unpredicted:
        print(f"  ({unpredicted} ready rental(s) without a recorded prediction)")


# --------------------------------------------------------------------------------------------
# One attempt
# --------------------------------------------------------------------------------------------


def _run_attempt(
    *,
    instance_id: int,
    created_at: float,
    offer: dict[str, Any],
    scored: Scored,
    session_id: str,
    attempt_index: int,
    config: str,
    machine: MachineConfig,
    policy: PolicyConfig,
    layers: list[Layer],
    total_left_s: float,
    identity_file: Path,
    git_state: LocalGitState,
    timer_s: int | None,
    script: str | None,
    script_argv: list[str],
    destroy_on_exit: bool,
    skip_probes: bool,
) -> bool:
    """Boot, prepare and record one rented instance. True if it is ready (and stays running).

    Destroy policy: until the watchdog is armed nothing on the instance can destroy it, so any
    failure before that destroys it from here. After that, a failure of ours leaves it running
    for debugging, covered by the timer.
    """
    boot: BootResult | None = None
    ssh_ready_at: float | None = None
    ssh_modes: list[str] | None = None
    armed = False

    def record(outcome, failure_type, detail, ready_at=None, probes=None) -> None:
        append_record(
            Attempt(
                kind="attempt",
                schema_version=SCHEMA_VERSION,
                session_id=session_id,
                attempt_index=attempt_index,
                created_at=created_at,
                config=config,
                image=machine.image,
                image_layers=layers,
                offer=offer,
                instance_id=instance_id,
                selection=scored.selection,
                polls=boot.polls if boot else [],
                pull=boot.pull if boot else _empty_pull(layers),
                abort_prediction_min=boot.abort_prediction_min if boot else None,
                outcome=outcome,
                failure_type=failure_type,
                failure_detail=detail,
                ssh_ready_at=ssh_ready_at,
                ready_at=ready_at,
                probes=probes,
                ssh_modes=ssh_modes,
            )
        )

    def collect_ssh_modes() -> None:
        nonlocal ssh_modes
        ssh_modes = sshmodes.fetch_report(instance_id)
        log(f"ssh mode fix: {sshmodes.summary(ssh_modes)}")

    try:
        boot = wait_for_boot(instance_id, layers, scored.rule, policy, total_left_s)
        if boot.outcome != "running":
            log(f"Giving up on host {offer['host_id']}: {boot.outcome} - {boot.detail}")
            record(boot.outcome, boot.failure_type, boot.detail)
            destroy_instance(instance_id)
            return False
        log(f"Running after {(time.time() - created_at) / 60:.1f} min")
        attach_ssh_key(instance_id, identity_file)
        host, port = ssh_host_port(instance_id)
        write_ssh_config(host, port, instance_id, identity_file)
        try:
            wait_until_ssh_ready(instance_id, identity_file)
        finally:
            collect_ssh_modes()
        ssh_ready_at = time.time()
        install_watchdog(instance_id, offer)
        armed = True
        set_timer(timer_s)
        sync_repo(git_state)
        ready_at = time.time()
        probes = None if skip_probes else run_probes()
        record("ready", None, None, ready_at=ready_at, probes=probes)
    except HostFailure as failure:
        assert not armed, "a host failure after the watchdog was armed is not expected"
        log(f"Host {offer['host_id']} failed ({failure.failure_type}): {failure.detail}")
        record("failed", failure.failure_type, failure.detail)
        destroy_instance(instance_id)
        return False
    except BaseException as error:
        # Recorded, then re-raised: a bug or a Ctrl-C is not the host's fault (not counted
        # against it by the model) and must not silently become a re-rent.
        failure_type = "interrupted" if isinstance(error, KeyboardInterrupt) else "ours"
        record("failed", failure_type, f"{type(error).__name__}: {error}")
        if armed:
            log(f"Instance {instance_id} left running (timer armed). Destroy: ic-vast destroy")
            _remember_instance(instance_id, offer)
        else:
            destroy_instance(instance_id)
        raise

    _remember_instance(instance_id, offer)
    status = timer_status()
    section("vast.ai instance ready")
    values(
        {
            "instance": instance_id,
            "host": f"{offer['host_id']} (machine {offer['machine_id']}, {offer['geolocation']})",
            "price": f"${offer['dph_total']:.3f}/h including disk",
            "setup time": f"{(ready_at - created_at) / 60:.1f} min "
            f"(predicted {_chosen_score(scored).setup_mean_min:.1f})",
            **{k: v for k, v in timer_values(status).items() if k != "instance"},
            **(summary_lines(probes) if probes is not None else {"probes": "skipped"}),
            "ssh": f"ssh {SSH_HOST_ALIAS}",
            "tunnel": f"ssh -N -L 8000:localhost:8000 {SSH_HOST_ALIAS}",
            "change timer": "ic-vast timer [2h|90m|off]",
            "end session": "ic-vast destroy",
        }
    )
    if script is not None:
        log_path = launch_script(script, script_argv, destroy_on_exit)
        log(f"Script started. Follow with: ssh {SSH_HOST_ALIAS} tail -f {log_path}")
    return True


# --------------------------------------------------------------------------------------------
# Scoring and output
# --------------------------------------------------------------------------------------------


def _check_mode(mode: str) -> Mode:
    assert mode in MODES, f"--mode must be one of {MODES}, got {mode!r}"
    return mode  # type: ignore[return-value]


def _fit(obs: Any, policy: PolicyConfig, mode: Mode, rng: np.random.Generator) -> Posterior:
    factor = policy.hedge_half_life_factor if mode == "hedge" else 1.0
    return fit(
        obs,
        speed_half_life_days=policy.speed_half_life_days * factor,
        failure_half_life_days=policy.failure_half_life_days * factor,
        n_draws=policy.n_posterior_draws,
        iterations=policy.gibbs_iterations,
        burn_in=policy.gibbs_burn_in,
        rng=rng,
    )


def _score(
    found: list[dict[str, Any]],
    machine: MachineConfig,
    policy: PolicyConfig,
    mode: Mode,
    hours: float | None,
    layers: list[Layer],
    rng: np.random.Generator,
    manual: bool = False,
) -> Scored:
    now = time.time()
    records = load_records()
    obs = observations_from_records(
        records, now, policy.cache_window_days, policy.abort_warmup_seconds
    )
    posterior = _fit(obs, policy, mode, rng)
    session_hours = hours if hours is not None else machine.hours
    lam, aversion = mode_settings(mode, policy)
    evaluation = evaluate(
        found,
        posterior,
        image_bytes=sum(layer.size for layer in layers),
        cache_eligible_hosts=cache_eligible_hosts(
            records, machine.image, now, policy.cache_window_days
        ),
        hours=session_hours,
        lambda_per_min=lam,
        failure_aversion=aversion,
        policy=policy,
        rng=rng,
    )
    if manual:
        assert len(found) == 1
        chosen, probs = 0, np.ones(1)
    else:
        chosen, probs = select(evaluation, mode, policy, rng)
    next_best = None if manual else next_best_setup(evaluation, chosen, mode, policy)
    selection = Selection(
        mode="manual" if manual else mode,
        hours=session_hours,
        lambda_per_min=lam,
        band_min=evaluation.band_min,
        reference_setup_min=evaluation.reference_setup_min,
        next_best_setup_min=next_best,
        candidates=candidate_scores(evaluation, probs, policy),
        propensity=float(probs[chosen]),
    )
    rule = abort_rule(posterior, next_best, policy)
    return Scored(evaluation, posterior, chosen, probs, selection, rule)


def _replayed_speed(a: Attempt) -> str:
    """The pull speed as the model sees it (polls replayed): exact, or a range if unfinished."""
    bounds = replay(a.image_layers, a.polls).speed_bounds(a.polls[-1].t) if a.polls else None
    if bounds is None:
        return "cached" if a.polls and a.pull.cached else "-"
    if bounds.exact:
        return f"{bounds.low_mb_s:.0f} MB/s"
    return f"{bounds.low_mb_s:.0f}-{bounds.high_mb_s:.0f} MB/s"


def _chosen_score(scored: Scored):
    return scored.selection.candidates[scored.chosen]


def _print_candidates(scored: Scored, limit: int) -> None:
    sel = scored.selection
    section(
        f"{len(sel.candidates)} offers, mode {sel.mode}, {sel.hours:g} h session, waiting "
        f"${sel.lambda_per_min * 60:.1f}/h beyond a {sel.band_min:.1f} min band"
    )
    print(
        f"  {'':1} {'offer':>9} {'host':>7}  {'gpu':<13} {'$/h':>6} {'setup min':>16} "
        f"{'fail':>5} {'cost $':>7} {'obs':>5} {'P(pick)':>8}  location"
    )
    order = sorted(range(len(sel.candidates)), key=lambda i: -sel.candidates[i].propensity)
    order = sorted(order[:limit], key=lambda i: sel.candidates[i].cost_mean)
    for i in order:
        c = sel.candidates[i]
        offer = scored.evaluation.offers[i]
        mark = ">" if i == scored.chosen else " "
        setup = f"{c.setup_mean_min:4.1f} [{c.setup_p10_min:4.1f},{c.setup_p90_min:5.1f}]"
        print(
            f"  {mark} {c.offer_id:>9} {c.host_id:>7}  {offer['gpu_name']:<13} {c.price:6.3f} "
            f"{setup:>16} {c.failure_prob:5.2f} {c.cost_mean:7.2f} "
            f"{c.effective_observations:5.1f} {c.propensity:8.3f}  {offer['geolocation']}"
        )
    against = f"its pull alone needs more than {scored.rule.budget_margin:g} x the pull budget left"
    if scored.rule.threshold_min is not None:
        against = (
            f"it needs more than {scored.rule.threshold_min:.1f} min to ready (next-best offer: "
            f"{sel.next_best_setup_min:.1f} min), or {against}"
        )
    print(f"  abort the pull if, even at its best speed so far, {against}")


def _interval(draws: np.ndarray, unit: str) -> str:
    lo, hi = np.quantile(draws, [0.1, 0.9])
    return f"{draws.mean():.3g} [{lo:.3g}, {hi:.3g}] {unit}".rstrip()


def _empty_pull(layers: list[Layer]) -> PullStats:
    """Pull stats of an attempt that ended before its boot was observed (e.g. Ctrl-C at once)."""
    return PullStats(
        started_at=None,
        ended_at=None,
        bytes_total=sum(layer.size for layer in layers),
        bytes_done=0,
        cached=False,
        speed_mb_s=None,
        unknown_layer_ids=[],
    )


def _forget_instance_if_gone() -> None:
    """Before renting: refuse while the recorded instance still exists; forget it if it is gone.

    The record (CURRENT_INSTANCE_PATH) normally ends with `ic-vast destroy`. An instance destroyed
    another way (vast.ai console, `vastai destroy`) leaves it behind; renting over it would lose
    that session's end. So a missing instance gets its End record (reason 'gone') here. One that
    still exists, in any status, may still be billing and is left to `ic-vast destroy`.
    """
    if not CURRENT_INSTANCE_PATH.exists():
        return
    instance_id = int(json.loads(CURRENT_INSTANCE_PATH.read_text())["instance_id"])
    shown = show_instance(instance_id)
    assert shown is None, (
        f"Instance {instance_id} is still recorded as active and exists on vast.ai (status "
        f"{shown['actual_status']!r}). End it with `uv run ic-vast destroy`, then rent again."
    )
    log(f"Instance {instance_id} is recorded as active but gone from vast.ai; recording its end")
    append_record(
        End(
            kind="end",
            schema_version=SCHEMA_VERSION,
            instance_id=instance_id,
            ended_at=time.time(),
            reason="gone",
            watchdog_starts=None,
            detail="not found by `vastai show instance` when renting again",
        )
    )
    CURRENT_INSTANCE_PATH.unlink()


def _remember_instance(instance_id: int, offer: dict[str, Any]) -> None:
    CURRENT_INSTANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CURRENT_INSTANCE_PATH.write_text(
        json.dumps({"instance_id": instance_id, "host_id": offer["host_id"]})
    )


def cli() -> None:
    fire.Fire(
        {
            "offers": offers,
            "rent": rent,
            "timer": timer_command,
            "sync": sync,
            "destroy": destroy,
            "stats": stats,
        }
    )


if __name__ == "__main__":
    cli()
