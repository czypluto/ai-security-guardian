"""Agent configuration — LLM providers, tools, and runtime settings."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


@dataclass
class LLMProvider:
    """Single LLM provider configuration."""
    name: str
    api_key: str
    base_url: str
    model: str
    max_tokens: int = 1024
    temperature: float = 0.7
    timeout: int = 15
    priority: int = 0   # lower = higher priority
    enabled: bool = True

    @property
    def chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


def _is_placeholder_key(api_key: str) -> bool:
    """识别配置模板里没被替换掉的占位值。

    以前用的是形状检查 `api_key.startswith("sk-")` —— 而占位符 `sk-xxxxx`
    恰好也满足它，于是「没配」被当成「配好了」，接着线上拿它去请求、拿 401。
    """
    key = (api_key or "").strip().lower()
    if not key:
        return True
    if key.count("x") >= 3 and set(key) <= set("sk-xyz0123456789"):
        return True
    return any(marker in key for marker in
               ("your-api-key", "your_api_key", "changeme", "<your"))


@dataclass
class AgentConfig:
    """Complete agent runtime configuration."""
    # LLM providers (ordered by priority)
    providers: list[LLMProvider] = field(default_factory=list)

    # Agent loop
    max_iterations: int = 10
    stream_output: bool = True
    # 送给 LLM 的历史消息窗口（对齐 GUI 原有的 [-20:] 裁剪）
    history_limit: int = 20

    # 危险工具的人工审批闸门（实现见 agent/graph.py 的 approval 节点）
    #
    # 判据有**两个来源**，任一命中即需审批：
    #   1. ToolDef.requires_approval —— 工具自带的基线（run_command / install_skill /
    #      recommend_mcp_server 三个已标注），这是主要来源；
    #   2. 下面的 approval_required_tools —— 配置层的**追加**名单。
    # 默认留空，避免与工具自带标注重复维护成两处真相。
    approval_mode: str = "interactive"   # interactive | auto_approve | auto_reject
    approval_required_tools: list[str] = field(default_factory=list)
    approval_timeout_seconds: int = 300  # 0 = 无限等待

    # 图状态持久化（LangGraph checkpointer）
    checkpoint_backend: str = "sqlite"   # sqlite | memory
    checkpoint_db_path: str = ""         # 空 = <项目根>/data/guardian_graph.sqlite

    # KB 上下文检索的超时预算（秒）；0 = 不限。
    # GUI 靠它防止嵌入服务冷启动（约 20s）拖慢首条回复，CLI 顺带获得同样能力。
    kb_context_timeout: float = 4.0

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
    knowledge_base_vector_db: dict = None
    knowledge_base_embedding: dict = None

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
        from pathlib import Path

        import yaml

        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        # Auto-load .env file
        cls._load_dotenv()

        providers = []
        llm_cfg = cfg.get("llm", {})

        # LLM providers —— 三家都是**可选**的，配了哪家就启用哪家。
        # priority 决定 LLMRouter 的尝试顺序（数字小的先试）。
        #
        # 原先这里只构造 DeepSeek，另外两家藏在 pc_agent/main.py 的一个手动回退
        # 分支里、且只有在 AgentConfig 解析不出任何 provider 时才会走到 ——
        # 于是 README 宣称的「多模型自动故障转移」实际没有对象可转。
        # 表驱动之后，加一家供应商只需要往这里加一行。
        presets = {
            "deepseek": {
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "priority": 0,
            },
            "zhipu": {
                "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "model": "glm-4-flash",
                "priority": 1,
            },
            "siliconflow": {
                "base_url": "https://api.siliconflow.cn/v1",
                "model": "deepseek-ai/DeepSeek-V3",
                "priority": 2,
            },
        }

        for name, preset in presets.items():
            pcfg = llm_cfg.get(name) or {}
            if not pcfg.get("enabled"):
                continue
            api_key = cls._resolve_env(pcfg.get("api_key", ""))
            if not api_key or _is_placeholder_key(api_key):
                continue
            providers.append(LLMProvider(
                name=name,
                api_key=api_key,
                base_url=pcfg.get("base_url") or preset["base_url"],
                model=pcfg.get("model") or preset["model"],
                max_tokens=int(pcfg.get("max_tokens", 1024)),
                temperature=float(pcfg.get("temperature", 0.7)),
                timeout=int(pcfg.get("timeout", 30)),
                priority=int(pcfg.get("priority", preset["priority"])),
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
        # 默认走进程内向量库：零依赖、不用起容器。
        # 这里给的是**代码级默认**而不是只写在 config.yaml 里 ——
        # pc_agent/config.yaml 被 .gitignore 忽略且仓库里没有模板，
        # 新克隆下来可能根本没有这个文件；只改配置的话"默认 local"不会真正生效。
        # 配置里显式写了 vector_db 就以配置为准（想切回 milvus/qdrant 直接改配置）。
        kb_vector_db = (kb_cfg.get("vector_db") if kb_cfg else None) or {"provider": "local"}
        kb_embedding = kb_cfg.get("embedding") or None if kb_cfg else None

        # Agent 运行参数（可选段）。
        # 与下面 KB 段同理：pc_agent/config.yaml 被 .gitignore 忽略、仓库里没有模板，
        # 新克隆下来可能完全没有这个文件 —— 所以默认值必须落在**代码**里，
        # 不能只依赖 config.yaml 里写。
        agent_cfg = cfg.get("agent", {}) or {}

        return cls(
            providers=sorted(providers, key=lambda p: p.priority),
            mcp_servers=mcp,
            skill_dirs=skill_dirs,
            knowledge_base_dir=kb_dir,
            knowledge_base_enabled=kb_enabled,
            knowledge_base_top_k=kb_top_k,
            knowledge_base_embedding_model=kb_embed_model,
            knowledge_base_vector_db=kb_vector_db,
            knowledge_base_embedding=kb_embedding,
            # 以下此前**从未**从配置传入 —— yaml 里写了也不生效（配置哑变量）。
            max_iterations=agent_cfg.get("max_iterations", 10),
            history_limit=agent_cfg.get("history_limit", 20),
            system_prompt=agent_cfg.get("system_prompt", "") or "",
            approval_mode=agent_cfg.get("approval_mode", "interactive"),
            approval_required_tools=list(agent_cfg.get("approval_required_tools") or []),
            approval_timeout_seconds=agent_cfg.get("approval_timeout_seconds", 300),
            checkpoint_backend=agent_cfg.get("checkpoint_backend", "sqlite"),
            checkpoint_db_path=agent_cfg.get("checkpoint_db_path", "") or "",
            kb_context_timeout=agent_cfg.get("kb_context_timeout", 4.0),
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
