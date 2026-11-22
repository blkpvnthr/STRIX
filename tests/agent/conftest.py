"""Pytest fixtures for agent tests."""

from __future__ import annotations

import pytest
from tests.agent.agent_fixtures import build_config

from strix.agent.config import AgentConfig


@pytest.fixture
def config() -> AgentConfig:
    return build_config()
