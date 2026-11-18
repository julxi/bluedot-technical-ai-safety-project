"""Thin wrappers around the `vastai` CLI: search offers, rent, look up and destroy instances.

Every call closes stdin and captures output; the CLI's failure modes are documented on each
function because it signals errors inconsistently (exit 0 on failure, errors on stderr).
"""

import json
import shlex
import shutil
import subprocess
from typing import Any

from ic_eval.vast.common import log
from ic_eval.vast.config import MachineConfig

# vast.ai's error for an ask it will not rent out: one already rented by someone else, or one
# that is unavailable although the search listed it as rentable (e.g. its host went offline).
TAKEN_OFFER_ERROR = "no_such_ask"


def vastai(args: list[str], raw: bool = True) -> Any:
    """Run a vastai CLI command, parsing its JSON output when raw.

    Under `--raw` the CLI reports an API failure by printing a JSON error object to stderr and
    exiting 0 with an empty stdout, so empty stdout means the command failed rather than that it
    found nothing. Only the leading tokens of a failed command are reported, to keep anything
    passed in later arguments out of the error.

    stdin is closed because stdout is captured: a command that prompts for confirmation (e.g.
    `destroy instance` without `-y`) would otherwise wait on an invisible prompt forever. With
    no stdin the prompt aborts at once - but the CLI still exits 0, so such commands must check
    their output (see `destroy_instance`).
    """
    cmd = ["vastai", *args, "--raw"] if raw else ["vastai", *args]
    result = subprocess.run(
        cmd, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    if not raw:
        return result.stdout
    stdout = result.stdout.strip()
    redacted_command = shlex.join(["vastai", *args[:3]])
    assert stdout, f"`{redacted_command}` failed: {result.stderr.strip() or 'no error message'}"
    return json.loads(stdout)


def check_cli() -> str:
    """Assert the CLI exists and return its version, which is logged: the output formats parsed
    here were observed with vastai 1.2.0 and may change between versions."""
    assert shutil.which("vastai"), "vastai CLI not found. Install it with `pip install vastai`."
    return vastai(["--version"], raw=False).strip()


def search_offers(config: MachineConfig) -> list[dict[str, Any]]:
    """All offers passing the config's hard filters, cheapest first.

    `disk_space` is the machine's free disk, which must fit the disk we intend to rent.
    `direct_port_count>=1` is required for the `--direct` ssh the launcher relies on. `gpu_ram`
    is queried in GB although offers report it in MB. Terms for datacenter and verified are added
    only when required: `datacenter=false` would select non-datacenter hosts only instead of
    leaving the choice open. The order does not matter to the policy, but `--limit` cuts from the
    cheap end, so `n_offers` must cover the market.
    """
    query = (
        f"num_gpus=1 gpu_name in [{','.join(config.gpu_names)}] rentable=true "
        f"reliability>{config.min_reliability} inet_down>={config.min_inet_down} "
        f"direct_port_count>=1 cuda_max_good>={config.min_cuda} gpu_ram>={config.min_gpu_ram} "
        f"disk_space>={config.disk} dph_total<{config.max_price}"
    )
    if config.verified_only:
        query += " verified=true"
    if config.datacenter_only:
        query += " datacenter=true"
    if config.excluded_countries:
        query += f" geolocation notin [{','.join(config.excluded_countries)}]"
    log(f"Searching offers: {query}")
    # -n: without it the CLI adds its own default terms (verified=true among them), which would
    # silently undo verified_only=false.
    found = vastai(
        [
            "search",
            "offers",
            "-n",
            query,
            "-o",
            "dph_total",
            "--limit",
            str(config.n_offers),
            # Price storage for the disk we actually rent; vast.ai otherwise quotes it for 5 GB
            "--storage",
            str(config.disk),
        ]
    )
    assert found, (
        "No offers matched. Raise max_price, lower min_gpu_ram/disk, or change gpu_names - in "
        "the machine config or with the matching flag."
    )
    wanted = {name.replace("_", " ") for name in config.gpu_names}
    for offer in found:
        assert offer["gpu_name"] in wanted, (
            f"Offer {offer['id']} has GPU {offer['gpu_name']!r}, not one of {sorted(wanted)}: "
            f"vast.ai ignored the gpu_name filter"
        )
        assert_allowed_country(offer, config.excluded_countries)
    return found


def assert_allowed_country(offer: dict[str, Any], excluded: list[str]) -> None:
    """vast.ai reports `geolocation` as 'Region, CC' (e.g. 'Jiangsu, CN'; SPD repo, 26-10-26), and
    sometimes with an empty region (', US'; seen 26-11-18)."""
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


def find_offer(offer_id: int, config: MachineConfig) -> dict[str, Any]:
    """Look up one offer, for --offer_id.

    vast.ai's query language has no documented field for the offer id: `id=` matches nothing, and
    `ask_contract_id=` works but the CLI warns that it does not know the field. `-n` drops the
    CLI's default terms so a hand-picked offer is not filtered out. `--storage` prices the disk we
    rent; without it `dph_total` covers only vast.ai's default 5 GB (seen 26-11-18: $0.456/h
    instead of $0.490/h with 80 GB).
    """
    found = vastai(
        [
            "search",
            "offers",
            "-n",
            f"ask_contract_id={offer_id}",
            "--storage",
            str(config.disk),
        ]
    )
    assert [int(o["id"]) for o in found] == [offer_id], (
        f"Looking up offer {offer_id} returned {[o['id'] for o in found]} - it is no longer on "
        f"the market, or vast.ai has changed how offers are looked up by id."
    )
    assert_allowed_country(found[0], config.excluded_countries)
    return found[0]


def create_instance(offer_id: int, config: MachineConfig, label: str) -> int | None:
    """Rent an offer, returning None if it is not available. Nothing is rented on failure.

    `--cancel-unavail` makes vast.ai reject an unavailable ask outright instead of parking a
    stopped instance on us, and it reports that as `no_such_ask` - both for an ask someone else
    rented and for one that is unavailable without being rented. Intentionally no `--env`:
    vast.ai stores those values on its servers, so secrets must never go there (docs/CODING.md).
    """
    args = [
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
        "--raw",
    ]
    result = subprocess.run(
        ["vastai", *args],
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


def show_instance(instance_id: int) -> dict[str, Any] | None:
    """The instance's state, or None if it no longer exists.

    An instance whose host drops it stops existing rather than reporting a dead status, and
    `show instance` answers for it with `{"instances": null}` instead of the flat instance dict.
    The same answer comes for an instance we destroyed.
    """
    shown = vastai(["show", "instance", str(instance_id)])
    if "actual_status" not in shown:
        assert shown == {"instances": None}, f"unexpected `show instance` answer: {shown}"
        return None
    return shown


def destroy_instance(instance_id: int) -> None:
    """Destroy an instance, failing loudly unless vast.ai confirms it.

    The CLI exits 0 whatever happens: on success it prints "destroying instance <id>.", on an
    unknown instance "Failed with error 404: ..." (to stderr), and without `-y` it prompts, reads
    a closed stdin and prints "Aborted." [all observed with vastai 1.2.0 by the SPD launcher on
    26-10-06]. So the output, both streams, is the only signal. A 404 is the one failure to
    accept: the instance is already gone (its host dropped it, or its own timer destroyed it).
    """
    log(f"Destroying instance {instance_id}")
    result = subprocess.run(
        ["vastai", "destroy", "instance", str(instance_id), "-y"],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    output = (result.stdout + result.stderr).strip()
    log(output)
    assert output == f"destroying instance {instance_id}." or "error 404" in output, (
        f"vast.ai did not confirm destroying instance {instance_id} ({output!r}), so it may still "
        f"be billing. Check `vastai show instances` and destroy it with: "
        f"vastai destroy instance {instance_id} -y"
    )
