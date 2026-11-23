"""Tests for ic-serve's pure parts (src/ic_eval/serve/): configs, script arguments, the served
name, and reading vLLM's and serve_vllm.sh's log lines. Nothing here rents or calls ssh."""

import subprocess

import pytest

from ic_eval.paths import REPO_ROOT
from ic_eval.serve.cli import (
    derive_max_connections,
    expected_served_name,
    parse_cache_tokens,
    parse_serve_line,
    serve_script_args,
    session_env_text,
)
from ic_eval.serve.config import available_configs, load_serve_config, resolve_checkpoint

FINAL_SHA = "d97e442d7cc678210054dbcc9b440894d62c89a4"  # allenai/Olmo-3-7B-Think main, 26-11-23


@pytest.mark.parametrize("name", available_configs())
def test_every_config_loads(name: str) -> None:
    config = load_serve_config(name)
    assert config.checkpoints


def test_olmo_config_has_the_paper_checkpoints() -> None:
    config = load_serve_config("olmo-3-7b-think")
    assert {"sft", "dpo", "step_0200", "final"} <= config.checkpoints.keys()


def test_unknown_config_raises() -> None:
    with pytest.raises(ValueError, match="unknown serve config 'olmo'"):
        load_serve_config("olmo")


def test_checkpoint_resolution() -> None:
    """A single-checkpoint config needs no name; a multi-checkpoint one must get a valid name."""
    assert resolve_checkpoint(load_serve_config("phi-4"), None)[0] == "default"
    olmo = load_serve_config("olmo-3-7b-think")
    with pytest.raises(ValueError, match="--checkpoint is needed"):
        resolve_checkpoint(olmo, None)
    with pytest.raises(ValueError, match="unknown checkpoint 'sf'"):
        resolve_checkpoint(olmo, "sf")
    assert resolve_checkpoint(olmo, "step_0200")[1].revision == "step_0200"


def test_script_args_in_serve_vllm_order() -> None:
    """serve_vllm.sh reads $1 model, $2 revision, $3 parser, $4 context length."""
    config = load_serve_config("phi-4")
    _, ckpt = resolve_checkpoint(config, None)
    assert serve_script_args(config, ckpt) == ["microsoft/phi-4", "main", "none", "16384"]


def test_served_name_of_the_real_reference_run() -> None:
    """The name vLLM actually served for the reference run of 26-11-23."""
    assert (
        expected_served_name("allenai/Olmo-3-7B-Think", "main", FINAL_SHA)
        == "olmo-3-7b-think.main.d97e442"
    )


def test_python_and_bash_derive_the_same_served_name() -> None:
    """Catches the two derivations drifting apart: runs serve_vllm.sh's SERVED_NAME line."""
    script = (REPO_ROOT / "scripts/vm/serve_vllm.sh").read_text().splitlines()
    (line,) = [x for x in script if x.startswith("SERVED_NAME=")]
    model, revision = "allenai/Olmo-3-7B-Think-SFT", "step_0200"
    bash = f'MODEL={model}; REVISION={revision}; SHA={FINAL_SHA}; {line}; echo "$SERVED_NAME"'
    out = subprocess.run(["bash", "-c", bash], check=True, capture_output=True, text=True).stdout
    assert out.strip() == expected_served_name(model, revision, FINAL_SHA)


def test_parse_serve_line() -> None:
    text = (
        "some earlier output\n"
        f"[serve_vllm] 2026-11-23T13:20:01+00:00 model=allenai/Olmo-3-7B-Think revision=main "
        f"sha={FINAL_SHA} served_name=olmo-3-7b-think.main.d97e442 reasoning_parser=olmo3 "
        "max_model_len=32768 vllm=0.34.0\n"
    )
    assert parse_serve_line(text) == {
        "model": "allenai/Olmo-3-7B-Think",
        "revision": "main",
        "sha": FINAL_SHA,
        "served_name": "olmo-3-7b-think.main.d97e442",
    }


def test_cache_tokens_and_connections_reproduce_the_a6000_optimum() -> None:
    """vLLM's line from the A6000 start of 26-11-21 (quoted in the harness LOG) must give the
    measured optimum of 32 connections with the Olmo config."""
    text = "INFO ... Maximum concurrency for 32,768 tokens per request: 3.55x\n"
    tokens = parse_cache_tokens(text)
    assert tokens == round(32768 * 3.55)
    n, how = derive_max_connections(load_serve_config("olmo-3-7b-think"), "48gb", tokens)
    assert n == 32, how


def test_missing_cache_line_fails_loudly() -> None:
    with pytest.raises(AssertionError, match="Maximum concurrency"):
        parse_cache_tokens("vLLM log without the line")


def test_session_env() -> None:
    text = session_env_text("phi-4.main.abcdef0", 25, 3600)
    assert "export INSPECT_EVAL_MODEL=openai-api/vllm/phi-4.main.abcdef0\n" in text
    assert "export INSPECT_EVAL_MAX_CONNECTIONS=25\n" in text
    assert "export INSPECT_EVAL_MODEL_ARGS=client_timeout=3600\n" in text


def test_new_log_lines_shows_only_new_lines_and_last_progress_state() -> None:
    """Catches repeated output on every poll and progress bars printed state by state."""
    from ic_eval.serve.cli import new_log_lines

    text = "first\nLoading 10%\rLoading 50%\rLoading 100%\n\nthird\nDownload 3%\rDownload 7%"
    lines, seen, progress = new_log_lines(text, 0)
    assert lines == ["first", "Loading 100%", "third"]
    assert (seen, progress) == (4, "Download 7%")
    lines, seen, progress = new_log_lines(text + "\rDownload 100%\nfourth\n", seen)
    assert lines == ["Download 100%", "fourth"] and (seen, progress) == (6, "")


def test_hf_token_profile_quotes_the_token() -> None:
    """The profile line must export exactly the token, even with shell-special characters."""
    import subprocess as sp

    from ic_eval.serve.cli import hf_token_profile

    token = "hf_ab$c'd e"  # not a real token
    line = hf_token_profile(token)
    out = sp.run(["bash", "-c", line + 'printf %s "$HF_TOKEN"'], capture_output=True, text=True)
    assert out.stdout == token


def test_missing_hf_token_fails_before_anything_else(tmp_path) -> None:
    from ic_eval.serve.cli import read_hf_token

    env = tmp_path / ".env"
    env.write_text("VLLM_API_KEY=none\n")
    with pytest.raises(AssertionError, match="HF_TOKEN missing"):
        read_hf_token(env)
    env.write_text("HF_TOKEN=hf_fake\n")
    assert read_hf_token(env) == "hf_fake"
