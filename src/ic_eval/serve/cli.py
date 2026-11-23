"""ic-serve: rent a GPU, serve a model there with vLLM, and prepare Inspect runs against it.

    ic-serve up olmo-3-7b-think --checkpoint sft          # rent, serve, tunnel, session file
    ic-serve up phi-4 --machine 48gb --timer 2h
    ic-serve attach phi-4                                  # continue on a running instance
    ic-serve switch olmo-3-7b-think --checkpoint dpo       # serve another model, same instance
    source serve_session.env                               # in each terminal that runs Inspect
    inspect eval tasks/generate.py -T dataset=etpm         # model, connections, timeout from env
    ic-vast destroy                                        # end the session

`up` does what scripts/laptop/gpu_up.sh did, driven by a serve config (config.py):
1. check HF_TOKEN from .env with Hugging Face (before renting, so a bad token costs nothing);
   rent through ic-vast; install the token on the instance; start scripts/vm/serve_vllm.sh
   with the checkpoint's arguments (authenticated downloads are much faster: Phi-4 came at
   ~37 MB/s without a token on 26-11-23);
2. open the ssh tunnel to localhost:8000 and wait until vLLM answers;
3. check that vLLM serves the expected name (derived from repository, revision and commit);
4. derive Inspect's max_connections from the KV cache vLLM reports on this GPU;
5. write serve_session.env (gitignored): INSPECT_EVAL_MODEL, INSPECT_EVAL_MAX_CONNECTIONS and
   INSPECT_EVAL_MODEL_ARGS, which Inspect reads in place of --model, --max-connections and -M.
   Not written into .env: that holds keys, and a variable already exported in the shell would
   silently win over .env.

`switch` stops vLLM on the running instance, waits until the GPU is free, and does steps 1
(without renting) to 5 for another model or checkpoint. The self-destruct timer is not changed
(extend it with `ic-vast timer 2h`).

The token goes to the instance only over ssh stdin into a mode-600 file under /etc/profile.d/
(docs/CODING.md, secrets rule), which the login shell running serve_vllm.sh reads. It is never
printed, logged, or passed as a command argument.
"""

import json
import re
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import fire
from dotenv import dotenv_values

from ic_eval.paths import REPO_ROOT
from ic_eval.serve.config import Checkpoint, ServeConfig, load_serve_config, resolve_checkpoint
from ic_eval.vast.cli import rent
from ic_eval.vast.remote import (
    REMOTE_SCRIPT_LOG_DIR,
    SSH_HOST_ALIAS,
    SSH_OPTS,
    launch_script,
    ssh,
    ssh_input,
    ssh_output,
)

PORT = 8000
SERVE_SCRIPT = "scripts/vm/serve_vllm.sh"
SESSION_ENV_PATH = REPO_ROOT / "serve_session.env"
# First start of Olmo 3 7B took 2 min 40 s (download + engine start). Phi-4's 29 GB came at
# only ~37 MB/s on 26-11-23 (unauthenticated Hugging Face download), i.e. ~13 min for weights
# alone, which broke the earlier limit of 900 s.
STARTUP_TIMEOUT_S = 1800
POLL_S = 10
# Written by ic-vast's wrapper when the script ends; vLLM should never end on its own.
SCRIPT_EXITED = "[ic-vast] script exited"
# Read by login shells, so by the shell ic-vast runs serve_vllm.sh in.
HF_TOKEN_FILE = "/etc/profile.d/hf_token.sh"
# After stopping vLLM, how long to wait for its processes to release the GPU.
GPU_FREE_TIMEOUT_S = 120

# vLLM's startup line on the KV cache, e.g. (A6000, Olmo 3 7B, 26-11-21):
# "Maximum concurrency for 32,768 tokens per request: 3.55x"
CONCURRENCY_LINE = re.compile(r"Maximum concurrency for ([\d,]+) tokens per request: ([\d.]+)x")
# serve_vllm.sh's own first line: "[serve_vllm] <date> model=… revision=… sha=… served_name=…"
SERVE_LINE = re.compile(
    r"\[serve_vllm\] \S+ model=(?P<model>\S+) revision=(?P<revision>\S+) "
    r"sha=(?P<sha>[0-9a-f]{40}) served_name=(?P<served_name>\S+)"
)


def log(message: str) -> None:
    print(f"[ic-serve] {message}", flush=True)


def serve_script_args(config: ServeConfig, checkpoint: Checkpoint) -> list[str]:
    """Arguments of scripts/vm/serve_vllm.sh: model, revision, reasoning parser, context length."""
    return [
        checkpoint.model,
        checkpoint.revision,
        config.reasoning_parser,
        str(config.max_model_len),
    ]


def expected_served_name(model: str, revision: str, sha: str) -> str:
    """The name serve_vllm.sh derives; keep in sync with SERVED_NAME there."""
    return f"{model.split('/')[-1].lower()}.{revision}.{sha[:7]}"


def parse_serve_line(log_text: str) -> dict[str, str]:
    found = [m.groupdict() for m in SERVE_LINE.finditer(log_text)]
    assert len(found) == 1, f"expected one [serve_vllm] line in the serve log, found {len(found)}"
    return found[0]


def parse_cache_tokens(log_text: str) -> int:
    """KV cache size in tokens, from vLLM's "Maximum concurrency for N tokens per request: Fx".

    N × F (F has two decimals, so the result is off by at most 0.5% of N).
    """
    found = CONCURRENCY_LINE.findall(log_text)
    assert len(found) == 1, f"expected one 'Maximum concurrency' line, found {len(found)}"
    per_request, factor = found[0]
    return round(int(per_request.replace(",", "")) * float(factor))


def derive_max_connections(config: ServeConfig, machine: str, cache_tokens: int) -> tuple[int, str]:
    """(max_connections, how it was derived)."""
    if machine in config.max_connections_override:
        n = config.max_connections_override[machine]
        return n, f"override for machine {machine!r} in the serve config"
    n = max(1, cache_tokens // config.tokens_per_request)
    return n, f"{cache_tokens:,} cache tokens // {config.tokens_per_request:,} tokens per request"


def session_env_text(served_name: str, max_connections: int, client_timeout: int) -> str:
    return (
        "# Written by `ic-serve up`; source it in each terminal that runs Inspect.\n"
        f"export INSPECT_EVAL_MODEL=openai-api/vllm/{served_name}\n"
        f"export INSPECT_EVAL_MAX_CONNECTIONS={max_connections}\n"
        f"export INSPECT_EVAL_MODEL_ARGS=client_timeout={client_timeout}\n"
    )


def read_hf_token(env_path: Path = REPO_ROOT / ".env") -> str:
    token = dotenv_values(env_path).get("HF_TOKEN")  # absence is handled right below
    assert token, (
        f"HF_TOKEN missing in {env_path}: add a read-only Hugging Face token "
        "(https://huggingface.co/settings/tokens) as a line HF_TOKEN=..."
    )
    return token


def check_hf_token(token: str) -> str:
    """The Hugging Face account the token belongs to; crashes if Hugging Face rejects it."""
    request = urllib.request.Request(
        "https://huggingface.co/api/whoami-v2", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            return json.load(resp)["name"]
    except urllib.error.HTTPError as e:
        # `from None`: keep the request (and its header) out of the traceback.
        raise AssertionError(f"Hugging Face rejected HF_TOKEN from .env (HTTP {e.code})") from None


def hf_token_profile(token: str) -> str:
    """Contents of the profile.d file that exports the token in login shells."""
    return f"export HF_TOKEN={shlex.quote(token)}\n"


def install_hf_token(token: str) -> None:
    """Over ssh stdin only (never a command argument): visible in no process list or log."""
    ssh_input(f"umask 077 && cat > {HF_TOKEN_FILE}", hf_token_profile(token))
    log(f"Hugging Face token installed on the instance ({HF_TOKEN_FILE}, mode 600)")


def checked_hf_token() -> str:
    token = read_hf_token()
    log(f"HF_TOKEN from .env accepted by Hugging Face (account {check_hf_token(token)})")
    return token


def start_server(config: ServeConfig, ckpt: Checkpoint) -> str:
    """Start serve_vllm.sh detached on the instance; returns its remote log path."""
    args = serve_script_args(config, ckpt)
    log_path = launch_script(SERVE_SCRIPT, args, destroy_on_exit=False)
    log(f"started {SERVE_SCRIPT} {shlex.join(args)}; log {log_path}")
    return log_path


def stop_server() -> None:
    """Stop vLLM and wait until no process uses the GPU any more."""
    # Bracket pattern: a plain "vllm serve" would also match this ssh command's own shell.
    # pkill exits 1 when nothing matched (nothing to stop), which is fine.
    ssh("pkill -f '[v]llm serve'; rc=$?; [ $rc -le 1 ]")
    started = time.time()
    while True:
        users = ssh_output("nvidia-smi --query-compute-apps=pid --format=csv,noheader").strip()
        if not users:
            log(f"vLLM stopped, GPU free after {time.time() - started:.0f} s")
            return
        assert time.time() - started < GPU_FREE_TIMEOUT_S, (
            f"GPU still in use {GPU_FREE_TIMEOUT_S} s after stopping vLLM (pids {users!r})"
        )
        time.sleep(3)


def newest_serve_log_path() -> str:
    path = ssh_output(f"ls -t {REMOTE_SCRIPT_LOG_DIR}/serve_vllm_*.log | head -n 1").strip()
    assert path, "no serve_vllm log on the instance"
    return path


def remote_serve_log(path: str) -> str:
    """Text of a serve_vllm log on the instance; empty while the just-started script hasn't
    created it yet (the wait's timeout catches a log that never appears)."""
    quoted = shlex.quote(path)
    return ssh_output(f"if [ -f {quoted} ]; then cat {quoted}; fi")


def open_tunnel() -> None:
    # A tunnel left over from an earlier session would point at the old instance.
    # pkill exits 1 when nothing matched, which is fine; anything else is a real error.
    killed = subprocess.run(["pkill", "-f", f"[l]ocalhost:{PORT} {SSH_HOST_ALIAS}"], check=False)
    assert killed.returncode in (0, 1), f"pkill failed with {killed.returncode}"
    # `ssh -f` forks into the background and would keep the caller's stdout and stderr open:
    # `ic-serve up | tee x` then never ended (seen 26-11-23: a piped switch only "finished"
    # when the next switch killed the tunnel). So no inherited streams; ssh's own error
    # messages go to a temporary file, shown if it fails.
    with tempfile.TemporaryFile(mode="w+") as errors:
        result = subprocess.run(
            [
                "ssh",
                *SSH_OPTS,
                "-f",
                "-N",
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "ServerAliveInterval=30",
                "-L",
                f"{PORT}:localhost:{PORT}",
                SSH_HOST_ALIAS,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=errors,
            check=False,
        )
        errors.seek(0)
        assert result.returncode == 0, f"ssh tunnel failed ({result.returncode}): {errors.read()}"
    log(f"tunnel open: localhost:{PORT} -> {SSH_HOST_ALIAS}:{PORT}")


def new_log_lines(text: str, seen: int) -> tuple[list[str], int, str]:
    """(complete lines after the first `seen` ones, new count, current state of the unfinished
    last line).

    Split on newlines only: download and loading progress bars rewrite one line with carriage
    returns, and only the last state of such a line is shown (str.splitlines would split at
    every carriage return and print each state).
    """
    *complete, unfinished = text.split("\n")
    shown = [line.rsplit("\r", 1)[-1][:200] for line in complete[seen:]]
    return [x for x in shown if x.strip()], len(complete), unfinished.rsplit("\r", 1)[-1][:200]


def wait_for_vllm(log_path: str) -> None:
    """Poll /health until vLLM answers, echoing new lines of the remote serve log meanwhile."""
    log(f"waiting for vLLM (up to {STARTUP_TIMEOUT_S} s); its log as it grows:")
    started = time.time()
    seen = 0
    last_progress = ""
    while True:
        try:
            with urllib.request.urlopen(f"http://localhost:{PORT}/health", timeout=5) as resp:
                if resp.status == 200:
                    log(f"vLLM answers after {time.time() - started:.0f} s of waiting")
                    return
        except urllib.error.URLError, ConnectionError, TimeoutError:
            pass  # not up yet: expected while vLLM loads; the checks below catch real failures
        text = remote_serve_log(log_path)
        lines, seen, progress = new_log_lines(text, seen)
        for line in lines:
            print(f"  vllm | {line}", flush=True)
        if progress.strip() and progress != last_progress:
            print(f"  vllm | {progress}", flush=True)
        last_progress = progress
        if SCRIPT_EXITED in text:
            raise AssertionError("serve_vllm.sh exited. End of its log:\n" + tail(text))
        if time.time() - started > STARTUP_TIMEOUT_S:
            raise AssertionError(
                f"no answer after {STARTUP_TIMEOUT_S} s. End of log:\n" + tail(text)
            )
        time.sleep(POLL_S)


def tail(text: str, lines: int = 40) -> str:
    return "\n".join(text.splitlines()[-lines:])


def served_models() -> list[str]:
    with urllib.request.urlopen(f"http://localhost:{PORT}/v1/models", timeout=10) as resp:
        return [m["id"] for m in json.load(resp)["data"]]


def up(
    model: str,
    checkpoint: str | None = None,
    machine: str = "48gb",
    timer: str | None = None,
    mode: str = "balance",
    hours: float | None = None,
) -> None:
    """Rent a GPU, serve one checkpoint of a model, open the tunnel, write serve_session.env.

    Args:
        model: Serve config name (src/ic_eval/serve/configs/<model>.yaml), e.g. olmo-3-7b-think.
        checkpoint: Checkpoint name from that config, e.g. sft; may be left out if it has one.
        machine: ic-vast machine config (GPU class), e.g. 48gb or h200.
        timer: Self-destruct timer, e.g. '2h'; default from the machine config.
        mode: ic-vast offer choice (exploit, balance, explore, hedge).
        hours: Planned session length for ic-vast's offer choice.
    """
    # fire turns arguments that look like Python literals into numbers; names must be strings.
    assert isinstance(model, str) and (checkpoint is None or isinstance(checkpoint, str)), (
        f"model and checkpoint must be names, got {model!r}, {checkpoint!r}"
    )
    config = load_serve_config(model)
    checkpoint_name, ckpt = resolve_checkpoint(config, checkpoint)
    args = serve_script_args(config, ckpt)
    log(f"{model} / {checkpoint_name} on machine {machine}: {SERVE_SCRIPT} {shlex.join(args)}")

    token = checked_hf_token()  # before renting: a bad token must not cost a rental
    # Rented without a script, so the token is on the instance before vLLM starts downloading.
    rent(config=machine, timer=timer, mode=mode, hours=hours)
    install_hf_token(token)
    prepare_session(config, ckpt, machine, start_server(config, ckpt))


def attach(model: str, checkpoint: str | None = None, machine: str = "48gb") -> None:
    """Continue on an instance that is already serving: tunnel, wait, checks, serve_session.env.

    For when `up` stopped after renting (e.g. its wait timed out while weights were still
    downloading) or the tunnel or session file got lost. Rents nothing; the instance behind
    `bluedot-vast` must serve this checkpoint, which the checks below verify.

    Args:
        model: Serve config name, as for `up`.
        checkpoint: Checkpoint name, as for `up`.
        machine: The ic-vast machine config the instance was rented with (for overrides).
    """
    assert isinstance(model, str) and (checkpoint is None or isinstance(checkpoint, str)), (
        f"model and checkpoint must be names, got {model!r}, {checkpoint!r}"
    )
    config = load_serve_config(model)
    _, ckpt = resolve_checkpoint(config, checkpoint)
    prepare_session(config, ckpt, machine, newest_serve_log_path())


def switch(model: str, checkpoint: str | None = None, machine: str = "48gb") -> None:
    """Serve another model or checkpoint on the instance that is already rented.

    Stops vLLM, waits until the GPU is free, (re)installs the Hugging Face token, starts
    serve_vllm.sh with the new checkpoint, then tunnel, wait, checks and serve_session.env as
    in `up`. Terminals that sourced the old session file must source it again; with the old
    one, vLLM answers "model not found".

    Args:
        model: Serve config name, as for `up`.
        checkpoint: Checkpoint name, as for `up`.
        machine: The ic-vast machine config the instance was rented with (for overrides).
    """
    assert isinstance(model, str) and (checkpoint is None or isinstance(checkpoint, str)), (
        f"model and checkpoint must be names, got {model!r}, {checkpoint!r}"
    )
    config = load_serve_config(model)
    checkpoint_name, ckpt = resolve_checkpoint(config, checkpoint)
    log(f"switching to {model} / {checkpoint_name}")
    token = checked_hf_token()
    stop_server()
    install_hf_token(token)
    prepare_session(config, ckpt, machine, start_server(config, ckpt))


def prepare_session(config: ServeConfig, ckpt: Checkpoint, machine: str, log_path: str) -> None:
    """Tunnel, wait for vLLM, check what it serves, write the session file."""
    open_tunnel()
    wait_for_vllm(log_path)

    text = remote_serve_log(log_path)
    serve = parse_serve_line(text)
    assert (serve["model"], serve["revision"]) == (ckpt.model, ckpt.revision), (
        f"serve log says {serve['model']}@{serve['revision']}, "
        f"expected {ckpt.model}@{ckpt.revision}"
    )
    expected = expected_served_name(ckpt.model, ckpt.revision, serve["sha"])
    assert serve["served_name"] == expected, f"served as {serve['served_name']!r}, not {expected!r}"
    assert served_models() == [expected], f"vLLM serves {served_models()}, expected [{expected!r}]"

    cache_tokens = parse_cache_tokens(text)
    max_connections, how = derive_max_connections(config, machine, cache_tokens)
    SESSION_ENV_PATH.write_text(session_env_text(expected, max_connections, config.client_timeout))

    log(f"serving {expected} (commit {serve['sha']})")
    log(f"max_connections {max_connections}: {how}")
    log(f"wrote {SESSION_ENV_PATH.name}; in each Inspect terminal: source {SESSION_ENV_PATH.name}")


def main() -> None:
    fire.Fire({"up": up, "attach": attach, "switch": switch})


if __name__ == "__main__":
    main()
