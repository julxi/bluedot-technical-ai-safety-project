"""Tests for build_script_command (src/ic_eval/vast/remote.py): script arguments must reach the
remote script unchanged through two layers of shell quoting (ssh command, then `bash -lc`)."""

import shlex

from ic_eval.vast.remote import build_script_command


def remote_argv(command: str) -> list[str]:
    """The argv the remote `bash -lc` runs for the script, recovered from the built command."""
    outer = shlex.split(command)
    inner = outer[outer.index("-lc") + 1]  # the string bash -lc executes
    first = inner.split(";", 1)[0]  # "cd <repo> && bash <script> <args>"
    return shlex.split(first.split("&&", 1)[1])


def test_arguments_reach_the_script_unchanged() -> None:
    """Catches lost or split arguments, e.g. a model name with a space or a quote."""
    args = ["allenai/Olmo-3-7B-Think-SFT", "main", "it's a test"]
    command = build_script_command("scripts/vm/serve_vllm.sh", args, False, "/root/x.log")
    assert remote_argv(command) == ["bash", "scripts/vm/serve_vllm.sh", *args]


def test_no_arguments() -> None:
    command = build_script_command("scripts/vm/serve_vllm.sh", [], False, "/root/x.log")
    assert remote_argv(command) == ["bash", "scripts/vm/serve_vllm.sh"]
