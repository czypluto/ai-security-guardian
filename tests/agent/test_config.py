"""
测试 AgentConfig: 环境变量解析, provider 加载, LLMProvider dataclass
"""
from __future__ import annotations

import os
from unittest.mock import patch

from agent.config import DEFAULT_SYSTEM_PROMPT, AgentConfig, LLMProvider

# ---- LLMProvider Dataclass ----

class TestLLMProvider:
    """LLMProvider dataclass basic behavior."""

    def test_default_values(self):
        p = LLMProvider(name="test", api_key="k", base_url="http://x", model="m")
        assert p.name == "test"
        assert p.max_tokens == 1024
        assert p.temperature == 0.7
        assert p.timeout == 15
        assert p.priority == 0
        assert p.enabled is True

    def test_chat_url_strips_trailing_slash(self):
        p = LLMProvider(name="t", api_key="k", base_url="https://api.example.com/v1/", model="m")
        assert p.chat_url == "https://api.example.com/v1/chat/completions"

    def test_chat_url_no_trailing_slash(self):
        p = LLMProvider(name="t", api_key="k", base_url="https://api.example.com/v1", model="m")
        assert p.chat_url == "https://api.example.com/v1/chat/completions"

    def test_priority_sorting(self):
        """Lower priority number = higher precedence."""
        providers = [
            LLMProvider(name="low", api_key="k", base_url="u", model="m", priority=10),
            LLMProvider(name="high", api_key="k", base_url="u", model="m", priority=0),
            LLMProvider(name="mid", api_key="k", base_url="u", model="m", priority=5),
        ]
        sorted_providers = sorted(providers, key=lambda p: p.priority)
        assert sorted_providers[0].name == "high"
        assert sorted_providers[1].name == "mid"
        assert sorted_providers[2].name == "low"


# ---- AgentConfig 基本构造 ----

class TestAgentConfigConstruction:
    """AgentConfig dataclass construction."""

    def test_default_config(self):
        cfg = AgentConfig()
        assert cfg.providers == []
        assert cfg.max_iterations == 10
        assert cfg.stream_output is True
        assert cfg.knowledge_base_enabled is True

    def test_custom_values(self, mock_provider):
        cfg = AgentConfig(
            providers=[mock_provider],
            max_iterations=20,
            stream_output=False,
            knowledge_base_enabled=False,
        )
        assert len(cfg.providers) == 1
        assert cfg.max_iterations == 20
        assert cfg.stream_output is False


# ---- 环境变量解析 ----

class TestEnvResolution:
    """AgentConfig._resolve_env — ${ENV_VAR} placeholder substitution."""

    def test_resolves_env_var(self):
        with patch.dict(os.environ, {"TEST_KEY": "my-secret-value"}, clear=False):
            result = AgentConfig._resolve_env("${TEST_KEY}")
            assert result == "my-secret-value"

    def test_plain_string_unchanged(self):
        assert AgentConfig._resolve_env("plain-text") == "plain-text"

    def test_no_placeholder_unchanged(self):
        assert AgentConfig._resolve_env("https://api.example.com") == "https://api.example.com"

    def test_missing_env_var_becomes_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            result = AgentConfig._resolve_env("${NONEXISTENT}")
            assert result == ""

    def test_multiple_placeholders(self):
        with patch.dict(os.environ, {"A": "1", "B": "2"}, clear=False):
            result = AgentConfig._resolve_env("${A}_${B}")
            assert result == "1_2"


# ---- .env 文件加载 ----

class TestDotenvLoading:
    """AgentConfig._load_dotenv — load .env into os.environ."""

    def test_loads_env_file(self, monkeypatch, tmp_path):
        """_load_dotenv 应把 .env 中的 KEY=VALUE 写入 os.environ。"""
        env_file = tmp_path / ".env"
        env_file.write_text("DEEPSEEK_API_KEY=sk-test-from-env-file\n", encoding="utf-8")

        # _load_dotenv 固定读取项目根/.env，把 os.path.join 指到临时文件即可触发
        from agent import config as config_mod
        monkeypatch.setattr(config_mod.os.path, "join", lambda *a: str(env_file))
        monkeypatch.setattr(config_mod.os.path, "exists", lambda *a: True)

        AgentConfig._load_dotenv()

        assert os.environ.get("DEEPSEEK_API_KEY") == "sk-test-from-env-file"
        # 清理，避免污染其他测试
        os.environ.pop("DEEPSEEK_API_KEY", None)

    def test_idempotent_does_not_override(self, monkeypatch):
        """Existing env vars should NOT be overridden by _load_dotenv."""
        monkeypatch.setenv("EXISTING_KEY", "original-value")
        # _load_dotenv skips keys already in os.environ
        # We can test this by calling the method and checking
        from agent.config import AgentConfig
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value = iter([
                "EXISTING_KEY=new-value\n"
            ])
            AgentConfig._load_dotenv()
        # Original value should be preserved
        assert os.environ["EXISTING_KEY"] == "original-value"


# ---- from_config_file 集成 ----

class TestFromConfigFile:
    """AgentConfig.from_config_file() — full YAML config parsing."""

    def test_loads_valid_config(self, temp_yaml_config):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-integration-test"}, clear=False):
            cfg = AgentConfig.from_config_file(temp_yaml_config)
            assert len(cfg.providers) == 1
            assert cfg.providers[0].name == "deepseek"
            assert cfg.providers[0].model == "deepseek-chat"
            assert cfg.providers[0].api_key == "sk-integration-test"


# ---- 多 provider ----

def _write_yaml(tmp_path, llm_section):
    import yaml

    config = {"llm": llm_section, "mcp_servers": [], "skills": {"enabled": False}}
    path = tmp_path / "multi.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return str(path)


class TestMultipleProviders:
    """三家供应商都要能装配上 —— 「多模型自动故障转移」的前提是有对象可转。

    原先 from_config_file 只构造 DeepSeek，另外两家藏在一个几乎走不到的回退
    分支里，于是文档宣称的故障转移实际从未发生过。
    """

    def test_all_three_configured(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "deepseek": {"enabled": True, "api_key": "sk-deepseek-real"},
            "zhipu": {"enabled": True, "api_key": "zhipu-key-real"},
            "siliconflow": {"enabled": True, "api_key": "sk-silicon-real"},
        })
        cfg = AgentConfig.from_config_file(path)
        assert [p.name for p in cfg.providers] == ["deepseek", "zhipu", "siliconflow"]
        # 真实端点与真实模型 id
        assert cfg.providers[1].base_url == "https://open.bigmodel.cn/api/paas/v4"
        assert all("v4-pro" not in p.model for p in cfg.providers)

    def test_disabled_provider_is_skipped(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "deepseek": {"enabled": True, "api_key": "sk-deepseek-real"},
            "zhipu": {"enabled": False, "api_key": "zhipu-key-real"},
        })
        cfg = AgentConfig.from_config_file(path)
        assert [p.name for p in cfg.providers] == ["deepseek"]

    def test_missing_key_is_skipped(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "deepseek": {"enabled": True, "api_key": "${NOT_SET_ANYWHERE_XYZ}"},
        })
        cfg = AgentConfig.from_config_file(path)
        assert cfg.providers == []

    def test_placeholder_key_is_not_treated_as_configured(self, tmp_path):
        """`sk-xxxxx` 这类占位符不能算「已配置」—— 否则会拿它去请求然后吃 401。"""
        path = _write_yaml(tmp_path, {
            "deepseek": {"enabled": True, "api_key": "sk-xxxxxxxxxxxxxxxx"},
            "zhipu": {"enabled": True, "api_key": "your-api-key-here"},
        })
        cfg = AgentConfig.from_config_file(path)
        assert cfg.providers == []

    def test_priority_defaults_order_the_failover(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "deepseek": {"enabled": True, "api_key": "sk-deepseek-real"},
            "zhipu": {"enabled": True, "api_key": "zhipu-key-real"},
            "siliconflow": {"enabled": True, "api_key": "sk-silicon-real"},
        })
        cfg = AgentConfig.from_config_file(path)
        assert [p.priority for p in cfg.providers] == [0, 1, 2]

    def test_explicit_model_override(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "deepseek": {"enabled": True, "api_key": "sk-deepseek-real",
                         "model": "deepseek-reasoner"},
        })
        cfg = AgentConfig.from_config_file(path)
        assert cfg.providers[0].model == "deepseek-reasoner"
        assert cfg.providers[0].base_url == "https://api.deepseek.com/v1"

    def test_disabled_provider_skipped(self, tmp_path):
        """Providers with enabled=false should be skipped."""
        import yaml
        config = {
            "llm": {
                "deepseek": {
                    "enabled": False,
                    "api_key": "${DEEPSEEK_API_KEY}",
                    "model": "deepseek-chat",
                }
            },
            "mcp_servers": [],
            "skills": {"enabled": False},
        }
        path = tmp_path / "config_disabled.yaml"
        with open(path, "w") as f:
            yaml.dump(config, f)

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}, clear=False):
            cfg = AgentConfig.from_config_file(str(path))
            assert len(cfg.providers) == 0  # No enabled providers

    def test_empty_api_key_skipped(self, tmp_path):
        """Providers with empty/non-sk API keys should be skipped."""
        import yaml
        config = {
            "llm": {
                "deepseek": {
                    "enabled": True,
                    "api_key": "your-api-key-here",  # Placeholder, not real
                    "model": "deepseek-chat",
                }
            },
            "mcp_servers": [],
            "skills": {"enabled": False},
        }
        path = tmp_path / "config_no_key.yaml"
        with open(path, "w") as f:
            yaml.dump(config, f)

        cfg = AgentConfig.from_config_file(str(path))
        assert len(cfg.providers) == 0  # API key doesn't start with sk-

    def test_mcp_servers_propagated(self, temp_yaml_config):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}, clear=False):
            cfg = AgentConfig.from_config_file(temp_yaml_config)
            assert cfg.mcp_servers == []

    def test_skill_dirs_resolved(self, temp_yaml_config, tmp_path):
        """Skill directories should be resolved relative to project root."""
        # Create a real skills dir
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}, clear=False):
            cfg = AgentConfig.from_config_file(temp_yaml_config)
            # Should work without crashing
            assert isinstance(cfg.skill_dirs, list)


# ---- DEFAULT_SYSTEM_PROMPT ----

class TestDefaultSystemPrompt:
    """DEFAULT_SYSTEM_PROMPT sanity checks."""

    def test_prompt_is_not_empty(self):
        assert len(DEFAULT_SYSTEM_PROMPT) > 100

    def test_contains_critical_rules(self):
        prompt = DEFAULT_SYSTEM_PROMPT
        assert "安小盾" in prompt
        assert "sandbox" in prompt.lower() or "Sandbox" in prompt
        assert "scan_network" in prompt
        assert "check_firewall" in prompt

    def test_contains_safety_constraints(self):
        prompt = DEFAULT_SYSTEM_PROMPT
        # Must contain key safety rules
        assert "NEVER" in prompt
        assert ".env" in prompt or "API credentials" in prompt


# ---- 向量库默认值 ----
# 这几条锁的是「默认进程内」这个决定必须落在**代码**里而不是只写在配置文件里：
# pc_agent/config.yaml 被 .gitignore 忽略且仓库无模板，新克隆可能根本没有该文件。
# 只改配置的话，「默认 local」不会真正生效，用户会静默退化成纯关键词检索。

def _write_cfg(tmp_path, kb_section):
    import yaml
    config = {
        "llm": {"deepseek": {"api_key": "${DEEPSEEK_API_KEY}", "model": "deepseek-chat"}},
        "mcp_servers": [],
        "skills": {"enabled": False},
    }
    if kb_section is not None:
        config["knowledge_base"] = kb_section
    path = tmp_path / "cfg.yaml"
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return str(path)


class TestVectorDbDefault:
    def test_missing_knowledge_base_section_defaults_to_local(self, tmp_path):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}, clear=False):
            cfg = AgentConfig.from_config_file(_write_cfg(tmp_path, None))
        assert cfg.knowledge_base_vector_db == {"provider": "local"}

    def test_missing_vector_db_key_defaults_to_local(self, tmp_path):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}, clear=False):
            cfg = AgentConfig.from_config_file(_write_cfg(tmp_path, {"enabled": True}))
        assert cfg.knowledge_base_vector_db == {"provider": "local"}

    def test_explicit_config_wins(self, tmp_path):
        """想切回 Milvus 时，显式配置必须盖过默认值。"""
        section = {"enabled": True, "vector_db": {"provider": "milvus", "fallback": "qdrant"}}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}, clear=False):
            cfg = AgentConfig.from_config_file(_write_cfg(tmp_path, section))
        assert cfg.knowledge_base_vector_db["provider"] == "milvus"

