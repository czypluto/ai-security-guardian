"""Agent configuration — LLM providers, tools, and runtime settings."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMProvider:
    """Single LLM provider configuration."""
    name: str
    api_key: str
    base_url: str
    model: str
    max_tokens: int = 1024
    temperature: float = 0.7
    timeout: int = 30
    priority: int = 0   # lower = higher priority
    enabled: bool = True

    @property
    def chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


@dataclass
class AgentConfig:
    """Complete agent runtime configuration."""
    # LLM providers (ordered by priority)
    providers: list[LLMProvider] = field(default_factory=list)

    # Agent loop
    max_iterations: int = 10
    stream_output: bool = True

    # System prompt
    system_prompt: str = ""
    skill_dirs: list[str] = field(default_factory=list)

    # MCP servers to connect to
    mcp_servers: list[dict] = field(default_factory=list)

    # Knowledge base
    knowledge_base_dir: str = ""
    knowledge_base_enabled: bool = True
    knowledge_base_top_k: int = 3
    knowledge_base_embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"

    @staticmethod
    def _load_dotenv():
        """Load .env file into os.environ (idempotent, doesn't override existing)."""
        import os
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        env_path = os.path.normpath(env_path)
        if not os.path.exists(env_path):
            return
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                if key not in os.environ:
                    os.environ[key] = val

    @classmethod
    def _resolve_env(cls, value: str) -> str:
        """Resolve ${ENV_VAR} placeholders from environment variables."""
        if not isinstance(value, str):
            return value
        pattern = re.compile(r"\$\{(\w+)\}")
        def replacer(match):
            return os.environ.get(match.group(1), "")
        return pattern.sub(replacer, value)

    @classmethod
    def from_config_file(cls, path: str) -> "AgentConfig":
        """Load from pc_agent/config.yaml."""
        import yaml
        from pathlib import Path

        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        # Auto-load .env file
        cls._load_dotenv()

        providers = []
        llm_cfg = cfg.get("llm", {})

        # DeepSeek — primary brain
        ds = llm_cfg.get("deepseek", {})
        ds_key = cls._resolve_env(ds.get("api_key", ""))
        if ds.get("enabled") and ds_key.startswith("sk-"):
            providers.append(LLMProvider(
                name="deepseek",
                api_key=ds_key,
                base_url="https://api.deepseek.com/v1",
                model=ds.get("model", "deepseek-chat"),
                max_tokens=1024,
                temperature=0.7,
                priority=0,
            ))

        # MCP servers
        mcp = cfg.get("mcp_servers", []) or []

        # Skill directories
        skill_cfg = cfg.get("skills", {})
        skill_dirs = []
        if skill_cfg.get("enabled", True):
            base = Path(__file__).parent.parent
            for d in skill_cfg.get("directories", ["skills"]):
                resolved = str(base / d)
                if os.path.isdir(resolved):
                    skill_dirs.append(resolved)

        # Knowledge base config
        kb_cfg = cfg.get("knowledge_base", {})
        kb_dir = kb_cfg.get("dir", "") if kb_cfg else ""
        kb_enabled = kb_cfg.get("enabled", True) if kb_cfg else True
        kb_top_k = kb_cfg.get("top_k", 3) if kb_cfg else 3
        kb_embed_model = kb_cfg.get("embedding_model", "paraphrase-multilingual-MiniLM-L12-v2") if kb_cfg else "paraphrase-multilingual-MiniLM-L12-v2"

        return cls(
            providers=sorted(providers, key=lambda p: p.priority),
            mcp_servers=mcp,
            skill_dirs=skill_dirs,
            knowledge_base_dir=kb_dir,
            knowledge_base_enabled=kb_enabled,
            knowledge_base_top_k=kb_top_k,
            knowledge_base_embedding_model=kb_embed_model,
        )


# Default system prompt for the security guardian agent
DEFAULT_SYSTEM_PROMPT = """You are "An Xiaodun" (安小盾), an AI cybersecurity guardian running on a Windows PC.
You help users monitor and protect their system security.

You have access to security tools. Use them to answer the user's questions:
- scan_network: Scan all active network connections for suspicious IPs, ports, and C2 patterns
- scan_processes: Find suspicious or malicious processes running on the system
- check_firewall: Verify Windows Firewall and Defender protection status
- read_security_logs: Read Windows security event logs (login failures, privilege changes, etc.)
- security_summary: Get a comprehensive security summary with risk level
- get_system_state: Get current CPU, memory, and overall security metrics
- get_listening_ports: List all open listening ports
- run_command: Execute a safe Windows diagnostic command (ipconfig, netstat, tasklist, etc.)

Rules:
1. When the user asks about security, ALWAYS use the relevant tools. Never guess.
2. Explain results in simple, actionable Chinese.
3. If a threat is found, state the severity clearly (low/medium/high/critical).
4. Keep responses concise — prioritize actionable information.
5. Use run_command sparingly, only for diagnostic commands.

## Self-Extension: Installing New Skills & Tools

You can help the user extend your capabilities:

**To install a new skill** (safe, automatic):
  1. Understand what the user wants
  2. Use web_search to find relevant techniques or procedures
  3. Use install_skill to create the .md file in skills/
  4. Tell the user the trigger phrase to activate it
  Skills are markdown text injected into your prompt — NEVER executed as code.
  This is SAFE. You can do this proactively when the user asks for new capabilities.

**To find MCP servers** (recommendation only):
  1. Use web_search to find MCP servers matching the user's need
  2. Use web_fetch to read their documentation
  3. Use recommend_mcp_server to show the user the config snippet
  MCP servers CAN execute arbitrary code — you MUST NOT install them automatically.
  The user must manually review and add to config.yaml.

**To look up vulnerabilities**:
  Use cve_lookup for specific CVEs, cve_search to find CVEs by product name.

## Sandbox Rules (NEVER VIOLATE)

These are ABSOLUTE restrictions. You cannot bypass them:
- NEVER modify config.yaml, .env, agent/*.py, or any code files
- NEVER use run_command for destructive operations (del, format, shutdown, reg, >, |, &&)
- NEVER attempt to read .env or API credentials
- NEVER install MCP servers automatically — always use recommend_mcp_server
- NEVER execute PowerShell, wget, curl, or any unapproved binary
- Skills (.md files) are the ONLY thing you can create

The sandbox is enforced at the tool execution layer — attempts to violate
these rules will be blocked and logged. If you need a capability that
requires breaking these rules, tell the user to do it manually."""
