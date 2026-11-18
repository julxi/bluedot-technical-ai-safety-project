"""Shared fixtures: the real policy config with a shorter sampler, so tests run in seconds."""

import numpy as np
import pytest

from ic_eval.vast.config import PolicyConfig, load_policy_config


@pytest.fixture
def policy() -> PolicyConfig:
    real = load_policy_config()
    return PolicyConfig(
        **{
            **real.model_dump(),
            "n_posterior_draws": 400,
            "gibbs_iterations": 900,
            "gibbs_burn_in": 100,
        }
    )


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(12345)
