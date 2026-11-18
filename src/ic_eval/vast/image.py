"""The layer list of a Docker Hub image, so a host's pull progress can be measured in bytes.

vast.ai's boot status shows Docker's pull messages, one line per event, keyed by the first 12 hex
digits of each layer's digest ("648f7856342e: Pull complete"). Docker unpacks layers in manifest
order, so "Pull complete" for layer k means layers 0..k are done; with the layer sizes that gives
the bytes pulled so far (boot.py).
"""

import json
import urllib.request
from typing import Any

from pydantic import BaseModel, ConfigDict

REGISTRY = "https://registry-1.docker.io/v2"
MAX_REPEATED_LAYER_BYTES = 1_000_000
AUTH_URL = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{}:pull"
MANIFEST_TYPES = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)


class Layer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    short_id: str  # first 12 hex digits of the digest, as Docker's pull messages show it
    size: int  # bytes, compressed (what crosses the network)


def fetch_layers(image: str) -> list[Layer]:
    """Layers of `repo:tag` for linux/amd64, in manifest (= unpack) order.

    Anonymous registry access: Docker Hub hands out a pull token for public repositories. A
    multi-platform tag resolves to an index first (checked 26-11-18 for vastai/vllm: index with
    amd64, arm64 and two attestation entries), whose amd64 entry is fetched by digest.
    """
    assert ":" in image and "/" in image, f"expected 'repo/name:tag', got {image!r}"
    repo, tag = image.rsplit(":", 1)
    token = _get_json(AUTH_URL.format(repo), {})["token"]
    headers = {"Authorization": f"Bearer {token}", "Accept": MANIFEST_TYPES}
    manifest = _get_json(f"{REGISTRY}/{repo}/manifests/{tag}", headers)
    if "manifests" in manifest:
        amd64 = [
            m
            for m in manifest["manifests"]
            if m["platform"]["architecture"] == "amd64" and m["platform"]["os"] == "linux"
        ]
        assert len(amd64) == 1, f"{image}: expected one linux/amd64 manifest, got {amd64}"
        manifest = _get_json(f"{REGISTRY}/{repo}/manifests/{amd64[0]['digest']}", headers)
    layers = [
        Layer(short_id=layer["digest"].split(":")[1][:12], size=int(layer["size"]))
        for layer in manifest["layers"]
    ]
    assert layers, f"{image}: manifest has no layers"
    # A layer may repeat (vastai/vllm:v0.34.0-cuda-13.0 lists a 2,080-byte layer at positions 15
    # and 16, checked 26-11-18). Docker downloads it once, so its messages cannot tell the copies
    # apart; boot.PullTracker maps it to the first copy. Harmless only for tiny layers.
    seen: set[str] = set()
    for layer in layers:
        if layer.short_id in seen:
            assert layer.size < MAX_REPEATED_LAYER_BYTES, (
                f"{image}: layer {layer.short_id} ({layer.size} bytes) repeats; pull progress "
                f"cannot be attributed to one copy"
            )
        seen.add(layer.short_id)
    return layers


def _get_json(url: str, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())
