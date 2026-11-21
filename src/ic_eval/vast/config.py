"""Machine configs (configs/<name>.yaml: what to rent) and the policy config (configs/policy.yaml:
how to choose among offers and when to give up on one)."""

from pathlib import Path
from typing import Any

from pydantic import Field

from ic_eval.vast.common import CONFIG_DIR, POLICY_CONFIG_PATH, YamlModel, log


class MachineConfig(YamlModel):
    """Hard filters of the offer search plus per-machine defaults.

    The filters are deliberately loose (Julian, 26-11-18: "way lower ... and no `verified`"), so
    that the model's own rental history, not vast.ai's self-reported fields, decides which hosts
    are good. Excluding CN is the exception: hosts there cannot reach Hugging Face.
    """

    gpu_names: list[str] = Field(
        description="vast.ai GPU names with spaces as underscores (e.g. 'RTX_A6000'); an offer "
        "with any of them matches"
    )
    max_price: float = Field(description="Maximum total price in $/hour, including storage")
    min_gpu_ram: int = Field(description="Minimum GPU memory in GB (vast.ai reports it in MB)")
    disk: int = Field(description="Disk to rent in GB; offer prices are quoted including it")
    image: str = Field(
        description="Docker image. Pin an exact tag, never 'latest': the tag is the only record "
        "of which vLLM version served a run, and its layer list drives the pull progress"
    )
    min_reliability: float = Field(description="Minimum vast.ai host reliability score")
    min_inet_down: float = Field(description="Minimum advertised download speed in Mbit/s")
    verified_only: bool = Field(description="Only hosts vast.ai lists as verified")
    datacenter_only: bool = Field(
        description="Only datacenter-labelled hosts. False searches all hosts, it does not "
        "exclude datacenters"
    )
    excluded_countries: list[str] = Field(
        description="Two-letter country codes never rented. CN: Hugging Face is DNS-poisoned "
        "there (SPD repo, 26-10-26), and every rental downloads model weights"
    )
    min_cuda: float = Field(description="Minimum CUDA version of the host driver; covers the image")
    n_offers: int = Field(
        description="How many offers (cheapest first) the policy chooses from. Large enough to "
        "cover the whole filtered market, or the model never sees the pricier hosts"
    )
    timer: str = Field(description="Default self-destruct timer, e.g. '3h', '90m' or 'off'")
    hours: float = Field(
        description="Default planned session length in hours. The price weighs more the longer "
        "the session, so this trades price against setup time in the policy's cost"
    )


class PolicyConfig(YamlModel):
    """How offers are scored and chosen, and when a booting host is given up on (policy.py,
    boot.py, model.py). Values and their reasons: configs/policy.yaml."""

    lambda_away_per_hour: float = Field(description="$ value of an hour of waiting, not watching")
    lambda_watching_per_hour: float = Field(description="$ value of an hour of waiting, watching")
    band_minutes: float = Field(description="Setup-time differences below this count nothing")
    band_fraction: float = Field(description="... nor those below this fraction of the best")
    failure_lost_minutes: float = Field(description="Time a failed rental costs before re-renting")
    switch_overhead_minutes: float = Field(description="Destroy + rent the next offer")
    speed_half_life_days: float = Field(description="Age at which a speed observation counts half")
    failure_half_life_days: float = Field(description="Same, for failure observations")
    hedge_half_life_factor: float = Field(description="`hedge` remembers this much longer")
    hedge_failure_aversion: float = Field(description="`hedge` multiplies failure costs by this")
    hedge_quantile: float = Field(description="`hedge` minimises this quantile of the cost")
    balance_tempering: float = Field(description="`balance` shrinks the posterior spread to this")
    max_attempts: int = Field(description="Rentals per `ic-vast rent` before giving up")
    max_total_boot_minutes: float = Field(description="Boot time summed over all attempts")
    max_pull_minutes: float = Field(
        description="Hard cap from renting until the image pull ends (download and unpack)"
    )
    max_build_minutes: float = Field(
        description="Hard cap from the pull's end until `running` (vast.ai's build step)"
    )
    stall_minutes: float = Field(description="Abort when the boot status has not changed this long")
    abort_warmup_seconds: float = Field(
        description="Pull time before the speed-based abort may act"
    )
    abort_budget_margin: float = Field(
        description="Abort when the best-case pull time left exceeds this x the pull budget left"
    )
    cache_window_days: float = Field(
        description="A host that ran the image this recently may have it"
    )
    n_posterior_draws: int = Field(description="Posterior draws kept for scoring")
    gibbs_iterations: int = Field(description="Gibbs sampler iterations, burn-in included")
    gibbs_burn_in: int = Field(description="Iterations discarded before keeping draws")


def resolve_config_path(config: str) -> Path:
    """'h200' -> configs/h200.yaml; anything with a '/' or '.yaml' is taken as a path."""
    if "/" in config or config.endswith((".yaml", ".yml")):
        path = Path(config)
        return path if path.is_absolute() else Path.cwd() / path
    return CONFIG_DIR / f"{config}.yaml"


def load_machine_config(config: str, overrides: dict[str, Any]) -> MachineConfig:
    """Load a machine config, applying any flags the caller passed explicitly."""
    path = resolve_config_path(config)
    available = sorted(p.stem for p in CONFIG_DIR.glob("*.yaml") if p != POLICY_CONFIG_PATH)
    assert path.exists(), f"machine config not found: {path}\nAvailable: {', '.join(available)}"
    log(f"Machine config: {path}")
    loaded = MachineConfig.from_file(path)
    given = {k: v for k, v in overrides.items() if v is not None}
    if given:
        log(f"Overriding {path.name}: {given}")
    # Rebuilt rather than model_copy(update=...), which skips validation and would let a
    # mistyped flag through into the offer search.
    return MachineConfig(**{**loaded.model_dump(), **given})


def load_policy_config() -> PolicyConfig:
    return PolicyConfig.from_file(POLICY_CONFIG_PATH)
