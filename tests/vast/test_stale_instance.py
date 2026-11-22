"""`ic-vast rent`'s check of a leftover instance record, with vast.ai's answer faked.

`show_instance` is replaced by a stub; the record file and the rental history point at
temporary files. Nothing touches vast.ai.
"""

import json
from pathlib import Path

import pytest

from ic_eval.vast import cli, records


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    current = tmp_path / "vast_current_instance.json"
    rentals = tmp_path / "rentals.jsonl"
    monkeypatch.setattr(cli, "CURRENT_INSTANCE_PATH", current)
    monkeypatch.setattr(records, "RENTALS_PATH", rentals)
    current.write_text(json.dumps({"instance_id": 123, "host_id": 7}))
    return current, rentals


def test_gone_instance_is_recorded_and_forgotten(
    paths: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    current, rentals = paths
    asked: list[int] = []
    monkeypatch.setattr(cli, "show_instance", lambda i: asked.append(i))  # returns None: gone

    cli._forget_instance_if_gone()

    assert asked == [123]
    assert not current.exists()
    (end,) = records.load_records()
    assert isinstance(end, records.End), end
    assert (end.instance_id, end.reason, end.watchdog_starts) == (123, "gone", None)


def test_existing_instance_blocks_the_rent(
    paths: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An instance that still exists (here stopped, which still bills for disk) is not forgotten."""
    current, rentals = paths
    monkeypatch.setattr(cli, "show_instance", lambda i: {"actual_status": "exited"})

    with pytest.raises(AssertionError, match="ic-vast destroy"):
        cli._forget_instance_if_gone()

    assert current.exists()
    assert not rentals.exists()


def test_no_record_asks_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "CURRENT_INSTANCE_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(cli, "show_instance", lambda i: pytest.fail("vast.ai was asked"))
    cli._forget_instance_if_gone()
