"""Serve configs (src/ic_eval/serve/configs/<name>.yaml), one per model.

A config holds what is the same for all checkpoints of a model (reasoning parser, context
length, request size for Inspect) and lists the checkpoints by name. The GPU is chosen on the
command line (an ic-vast machine config); how many requests to send at once is derived from the
KV cache vLLM reports on that GPU (cli.py), so no per-GPU value has to be measured first.
"""

from pathlib import Path

from pydantic import Field

from ic_eval.vast.common import YamlModel

SERVE_CONFIG_DIR = Path(__file__).parent / "configs"


class Checkpoint(YamlModel):
    model: str  # Hugging Face repository, e.g. allenai/Olmo-3-7B-Think-SFT
    revision: str  # branch or commit, e.g. main or step_0200


class ServeConfig(YamlModel):
    # vLLM --reasoning-parser, or "none" for a model without a thinking part.
    reasoning_parser: str
    # vLLM --max-model-len: prompt + reply. vLLM refuses a value above the model's own context.
    max_model_len: int = Field(gt=0)
    # Inspect's HTTP timeout per request (-M client_timeout); a long reply at ~16 tok/s with
    # many requests at once can take far longer than Inspect's default of 600 s.
    client_timeout: int = Field(gt=0)
    # Typical KV-cache tokens one request of this model's use occupies (prompt + reply +
    # headroom). Inspect's max_connections = vLLM's KV cache tokens // this.
    tokens_per_request: int = Field(gt=0)
    # Measured exceptions to that rule, by ic-vast machine config (e.g. {"h200": 96}).
    max_connections_override: dict[str, int] = {}
    checkpoints: dict[str, Checkpoint] = Field(min_length=1)


def available_configs() -> list[str]:
    return sorted(p.stem for p in SERVE_CONFIG_DIR.glob("*.yaml"))


def load_serve_config(name: str) -> ServeConfig:
    path = SERVE_CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise ValueError(f"unknown serve config {name!r}; available: {available_configs()}")
    return ServeConfig.from_file(path)


def resolve_checkpoint(config: ServeConfig, name: str | None) -> tuple[str, Checkpoint]:
    """The named checkpoint; a config with only one may leave the name out."""
    if name is None:
        if len(config.checkpoints) != 1:
            raise ValueError(f"--checkpoint is needed; one of {sorted(config.checkpoints)}")
        name = next(iter(config.checkpoints))
    if name not in config.checkpoints:
        raise ValueError(f"unknown checkpoint {name!r}; one of {sorted(config.checkpoints)}")
    return name, config.checkpoints[name]
