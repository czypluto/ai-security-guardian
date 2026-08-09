"""
pytest fixtures for agent/ module tests.

All tests use mocks — no real LLM calls, no network, no ctypes/Windows APIs.
Each test file handles its own ctypes mocking at module level.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch


# ================================================================
#  Config fixtures
# ================================================================

@pytest.fixture
def mock_provider():
    """A mock LLM provider (like DeepSeek)."""
    from agent.config import LLMProvider
    return LLMProvider(
        name="deepseek",
        api_key="sk-test-mock-key",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        max_tokens=1024,
        temperature=0.7,
        timeout=30,
        priority=0,
    )


@pytest.fixture
def mock_config(mock_provider):
    """A minimal AgentConfig with one provider."""
    from agent.config import AgentConfig
    return AgentConfig(
        providers=[mock_provider],
        max_iterations=5,
        stream_output=False,
        mcp_servers=[],
        skill_dirs=[],
        knowledge_base_enabled=False,
    )


# ================================================================
#  Tool fixtures
# ================================================================

@pytest.fixture
def tool_registry():
    """A ToolRegistry pre-populated with test tools."""
    from agent.tools import ToolRegistry, ToolDef

    registry = ToolRegistry()
    registry.register(ToolDef(
        name="test_tool",
        description="A test tool for unit tests",
        parameters={"param1": {"type": "string", "description": "Test param"}},
        handler=lambda param1="default": {"result": param1},
    ))
    registry.register(ToolDef(
        name="scan_network",
        description="Scan network connections",
        parameters={},
        handler=lambda: {"status": "normal", "suspicious_ips": 0},
    ))
    return registry


# ================================================================
#  Temp file fixtures
# ================================================================

@pytest.fixture
def temp_yaml_config(tmp_path):
    """Write a minimal config.yaml to a temp directory and return its path."""
    import yaml
    config = {
        "llm": {
            "deepseek": {
                "enabled": True,
                "api_key": "${DEEPSEEK_API_KEY}",
                "model": "deepseek-chat",
            }
        },
        "device": {"mode": "none"},
        "security": {
            "scan_interval": 5,
            "network": {},
            "process": {"cpu_threshold": 80, "mem_threshold": 80},
            "firewall": {},
        },
        "ai": {"enabled": False},
        "system_tray": {"enabled": False},
        "character": {},
        "logging": {"level": "WARNING"},
        "mcp_servers": [],
        "skills": {"enabled": False},
    }
    path = tmp_path / "config.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return str(path)


@pytest.fixture
def temp_env_file(tmp_path):
    """Write a minimal .env file to a temp directory."""
    env_path = tmp_path / ".env"
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("DEEPSEEK_API_KEY=sk-test-key-from-env-file\n")
    return str(env_path)
