"""Short measurements on a ready instance, identical on every machine so hosts can be compared.

About 45 s in total, recorded with the rental (records.Attempt.probes):
- Hugging Face download speed: one fixed file at a pinned revision, fetched for at most 30 s and
  discarded. The real job downloads model weights from there, at whatever speed this host gets.
- GPU: bf16 matmul throughput (TFLOPS) and device memory copy bandwidth (GB/s), with the image's
  own PyTorch. vLLM's token generation is mostly limited by memory bandwidth, so the copy speed is
  the cheap stand-in for tokens/s (Julian, 26-11-18: measure it if it can be done easily).
- nvidia-smi facts (power limit: a capped H100 ran 40% slower in the SPD repo) and the container's
  CPU quota against nproc.

A probe that fails records its error instead of a value and prints a warning: a missing
measurement must not cost a ready machine, and the record shows which probe failed and why.
"""

import json
import subprocess
from collections.abc import Callable
from typing import Any

from ic_eval.vast.common import log
from ic_eval.vast.remote import SSH_HOST_ALIAS, SSH_OPTS, ssh_output

# Olmo-3-7B-Think's first weight shard (~5 GB) at the revision current on 26-11-18: a fixed file
# and revision, so every host downloads the same bytes from the same CDN path.
HF_PROBE_URL = (
    "https://huggingface.co/allenai/Olmo-3-7B-Think/resolve/"
    "d97e442d7cc678210054dbcc9b440894d62c89a4/model-00001-of-00003.safetensors"
)
HF_PROBE_SECONDS = 30
# curl's exit code when --max-time cut the transfer: expected, the file is larger than 30 s.
CURL_TIMEOUT_EXIT = 28

GPU_PROBE_SCRIPT = """\
import json, time, torch
assert torch.cuda.is_available(), "no CUDA device visible to torch"
dev = torch.device("cuda")
n, iters = 8192, 20
a = torch.randn(n, n, device=dev, dtype=torch.bfloat16)
b = torch.randn(n, n, device=dev, dtype=torch.bfloat16)
for _ in range(3):
    a @ b
torch.cuda.synchronize(); t = time.time()
for _ in range(iters):
    a @ b
torch.cuda.synchronize(); matmul_s = time.time() - t
x = torch.empty(2**30, dtype=torch.uint8, device=dev); y = torch.empty_like(x)
y.copy_(x); torch.cuda.synchronize(); t = time.time()
for _ in range(iters):
    y.copy_(x)
torch.cuda.synchronize(); copy_s = time.time() - t
print(json.dumps({
    "bf16_tflops": 2 * n**3 * iters / matmul_s / 1e12,
    "copy_gb_s": 2 * x.numel() * iters / copy_s / 1e9,
    "torch": torch.__version__,
    "device": torch.cuda.get_device_name(0),
}))
"""
NVIDIA_FIELDS = [
    "name",
    "memory.total",
    "power.limit",
    "power.max_limit",
    "clocks.max.sm",
    "driver_version",
]


def run_probes() -> dict[str, Any]:
    log("Running probes (Hugging Face download, GPU throughput, machine facts, ~45 s)")
    results = {
        "hf_download": _guarded("hf_download", _probe_hf),
        "gpu": _guarded("gpu", _probe_gpu),
        "nvidia_smi": _guarded("nvidia_smi", _probe_nvidia_smi),
        "cpu": _guarded("cpu", _probe_cpu),
    }
    return results


def summary_lines(probes: dict[str, Any]) -> dict[str, str]:
    """The probe results as summary rows (errors shown as such)."""

    def show(name: str, fmt: Callable[[dict[str, Any]], str]) -> str:
        result = probes[name]
        return f"FAILED: {result['error']}" if "error" in result else fmt(result)

    return {
        "hf download": show("hf_download", lambda r: f"{r['mb_s']:.0f} MB/s"),
        "gpu speed": show(
            "gpu",
            lambda r: f"{r['bf16_tflops']:.0f} bf16 TFLOPS, {r['copy_gb_s']:.0f} GB/s copy",
        ),
        "gpu facts": show(
            "nvidia_smi",
            lambda r: (
                f"{r['name']}, {r['memory.total']} MiB, power limit {r['power.limit']} W "
                f"of {r['power.max_limit']} W"
            ),
        ),
        "cpu": show("cpu", lambda r: f"quota {r['quota']}, nproc {r['nproc']}"),
    }


def _guarded(name: str, probe: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return probe()
    except (
        subprocess.CalledProcessError,
        AssertionError,
        ValueError,
        KeyError,
    ) as error:
        detail = getattr(error, "stderr", None) or str(error)
        log(f"WARNING: probe {name} failed: {detail}")
        return {"error": f"{type(error).__name__}: {detail}"}


def _probe_hf() -> dict[str, Any]:
    out = ssh_output(
        f"curl -sL -o /dev/null --max-time {HF_PROBE_SECONDS} "
        f"-w '%{{size_download}} %{{time_total}} %{{http_code}}' '{HF_PROBE_URL}'; echo \" $?\""
    ).split()
    size, seconds, http_code, exit_code = (
        float(out[0]),
        float(out[1]),
        out[2],
        int(out[3]),
    )
    assert exit_code in (0, CURL_TIMEOUT_EXIT), f"curl exit {exit_code}: {out}"
    assert http_code == "200", f"HTTP {http_code} for the probe file"
    assert size > 0 and seconds > 0, f"nothing downloaded: {out}"
    return {
        "mb_s": size / 1e6 / seconds,
        "bytes": size,
        "seconds": seconds,
        "url": HF_PROBE_URL,
    }


def _probe_gpu() -> dict[str, Any]:
    # The interpreter that runs vLLM has torch; on vastai/vllm it is the `vllm` script's shebang
    # (/venv/main/bin/python on 26-11-18), not the system python3.
    python = ssh_output('head -1 "$(command -v vllm)"').strip().removeprefix("#!")
    assert python.startswith("/"), f"no interpreter found from the vllm script: {python!r}"
    out = _ssh_input_output(f"{python} -", GPU_PROBE_SCRIPT)
    result = json.loads(out.strip().splitlines()[-1])
    result["python"] = python
    return result


def _probe_nvidia_smi() -> dict[str, Any]:
    line = ssh_output(
        f"nvidia-smi --query-gpu={','.join(NVIDIA_FIELDS)} --format=csv,noheader,nounits"
    ).strip()
    parts = [p.strip() for p in line.splitlines()[0].split(",")]
    assert len(parts) == len(NVIDIA_FIELDS), f"unexpected nvidia-smi output: {line!r}"
    return dict(zip(NVIDIA_FIELDS, parts, strict=True))


def _probe_cpu() -> dict[str, Any]:
    quota = ssh_output("cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo unknown").strip()
    nproc = int(ssh_output("nproc").strip())
    return {"quota": quota, "nproc": nproc}


def _ssh_input_output(remote_command: str, text: str) -> str:
    """Like remote.ssh_input, but returns stdout (the GPU probe prints its JSON result)."""
    return subprocess.run(
        ["ssh", *SSH_OPTS, SSH_HOST_ALIAS, remote_command],
        check=True,
        input=text,
        capture_output=True,
        text=True,
    ).stdout
