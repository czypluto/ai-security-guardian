"""Agent Core — ReAct loop with MCP tools, skills, KB, and streaming output."""
from __future__ import annotations

import json
import logging
from typing import Generator, Optional, TYPE_CHECKING

from .config import AgentConfig, DEFAULT_SYSTEM_PROMPT
from .llm import LLMRouter
from .tools import ToolRegistry, create_tool_registry, ToolDef
from .mcp_client import MCPManager
from .skill_loader import SkillManager, Skill

if TYPE_CHECKING:
    from .knowledge_base import KnowledgeBase

logger = logging.getLogger("Guardian.Agent")


class AgentCore:
    """ReAct agent: Think -> Act -> Observe -> Repeat.

    Architecture:
      LLM Router (DeepSeek-v4-pro)
        |
      Tool Registry (built-in + MCP-discovered + skills)
        |
      +-- Built-in tools (scan_network, check_firewall, ...)
      +-- MCP Client (external MCP servers, JSON-RPC 2.0)
      +-- Skill Manager (local .md files, prompt injection)
      +-- Knowledge Base (vector search for past conversations)
    """

    def __init__(self, config: AgentConfig, tool_registry: ToolRegistry = None,
                 knowledge_base: "KnowledgeBase" = None):
        self.config = config
        self.llm = LLMRouter(config.providers)
        self.tools = tool_registry or create_tool_registry()
        self._conversation_id: Optional[str] = None

        # Knowledge base (optional)
        self.kb = knowledge_base
        self._kb_enabled = config.knowledge_base_enabled and self.kb is not None
        self._kb_top_k = config.knowledge_base_top_k

        # MCP: connect to external MCP servers
        self.mcp = MCPManager()
        self.mcp.add_servers_from_config(config.mcp_servers)
        self._merge_mcp_tools()

        # Skills: auto-load from skills/ directories
        self.skills = SkillManager(config.skill_dirs)
        self.skills.load_all()
        self._active_skill: Optional[Skill] = None

        # Conversation tracking for KB save
        self._conversation_messages: list[dict] = []

    # ================================================================
    #  MCP & Skills integration
    # ================================================================

    def _merge_mcp_tools(self):
        """Register MCP-discovered tools into the built-in registry."""
        for mcp_tool in self.mcp.get_all_tools():
            self.tools.register(ToolDef(
                name=mcp_tool.name,
                description=mcp_tool.description,
                parameters=mcp_tool.input_schema.get("properties", {}),
                handler=lambda args, tn=mcp_tool.name: self._mcp_tool_handler(tn, args),
            ))
        mc = self.mcp.total_tools
        if mc:
            logger.info(f"MCP: {mc} external tools merged (servers: {self.mcp.connected_servers})")

    def _mcp_tool_handler(self, tool_name: str, arguments: dict) -> dict:
        """Handler for MCP tools — routed through MCP client."""
        result_json, server = self.mcp.call_tool(tool_name, arguments)
        try:
            return json.loads(result_json)
        except json.JSONDecodeError:
            return {"result": result_json}

    def _build_system_prompt(self, kb_context: str = "") -> str:
        """Build system prompt with active skill, tool list, and KB context."""
        prompt = self.config.system_prompt or DEFAULT_SYSTEM_PROMPT

        # Inject knowledge base context
        if kb_context:
            prompt += "\n\n" + kb_context

        # Inject matched skill
        skill_prompt = self.skills.build_skills_prompt(self._active_skill)
        prompt += "\n\n" + skill_prompt

        return prompt

    # ================================================================
    #  Public API
    # ================================================================

    def run(self, user_input: str) -> str:
        """Run agent, return final text."""
        result_parts: list[str] = []
        for event in self.run_stream(user_input):
            if event["type"] == "text":
                result_parts.append(event["content"])
            elif event["type"] == "error":
                result_parts.append(f"\n[Error: {event['content']}]\n")
        return "".join(result_parts)

    def run_stream(self, user_input: str) -> Generator[dict, None, None]:
        """Run agent with streaming output. Yields events."""
        # Check for skill triggers
        matched = self.skills.match_triggers(user_input)
        if matched and not self._active_skill:
            self._active_skill = matched

        # Track user message for KB
        self._conversation_messages.append({"role": "user", "content": user_input})

        # Search knowledge base for relevant context
        kb_context = ""
        if self._kb_enabled:
            try:
                kb_context = self.kb.build_context(user_input, top_k=self._kb_top_k)
                if kb_context:
                    logger.debug(f"KB: 检索到相关知识 ({len(kb_context)} 字符)")
            except Exception as e:
                logger.debug(f"KB 检索跳过: {e}")

        system_prompt = self._build_system_prompt(kb_context)
        tool_schemas = self.tools.get_schemas()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]

        iterations = 0
        final_text = ""

        while iterations < self.config.max_iterations:
            iterations += 1

            response = self.llm.chat(
                messages=messages,
                tools=tool_schemas if tool_schemas else None,
                max_tokens=1024,
            )

            if not response.get("_ok"):
                yield {"type": "error", "content": response.get("_error", "LLM call failed")}
                self._active_skill = None
                return

            if self.llm.has_tool_calls(response):
                tool_calls = self.llm.extract_tool_calls(response)
                if not tool_calls:
                    yield {"type": "error", "content": "Tool call parse failed"}
                    self._active_skill = None
                    return

                messages.append(response["choices"][0]["message"])

                for tc in tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "unknown")
                    try:
                        args = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}

                    yield {"type": "tool_start", "name": name, "arguments": args}

                    result = self.tools.execute(name, args)
                    yield {"type": "tool_result", "name": name, "result": result}

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": result,
                    })
                continue

            reply = self.llm.extract_reply(response)
            final_text = reply
            yield {"type": "text", "content": reply}
            self._active_skill = None

            # Track assistant message for KB
            self._conversation_messages.append({"role": "assistant", "content": reply})
            return

        if not final_text:
            yield {"type": "text", "content": "[Max iterations reached]"}
        self._active_skill = None

    # ================================================================
    #  Knowledge Base
    # ================================================================

    def save_conversation(self, metadata: dict = None) -> Optional[str]:
        """Save current conversation to knowledge base."""
        if not self._conversation_messages:
            return None
        if not self._kb_enabled or self.kb is None:
            return None
        try:
            conv_id = self.kb.add_conversation(self._conversation_messages, metadata)
            logger.info(f"对话已保存到知识库: {conv_id}")
            return conv_id
        except Exception as e:
            logger.warning(f"保存对话失败: {e}")
            return None

    def clear_conversation(self):
        """Clear conversation history (but keep KB)."""
        self._conversation_messages.clear()
        self._active_skill = None

    # ================================================================
    #  Info
    # ================================================================

    @property
    def active_model(self) -> str:
        p = self.llm.active_provider
        return f"{p.name}/{p.model}" if p else "none"

    @property
    def tool_count(self) -> int:
        builtin = len(self.tools.list_all())
        mcp = self.mcp.total_tools
        if mcp:
            return builtin  # MCP tools are already merged
        return builtin

    @property
    def skill_count(self) -> int:
        return len(self.skills.list_all())

    def summary(self) -> dict:
        result = {
            "model": self.active_model,
            "builtin_tools": len(self.tools.list_all()) - self.mcp.total_tools,
            "mcp_tools": self.mcp.total_tools,
            "mcp_servers": self.mcp.connected_servers,
            "skills": len(self.skills.list_all()),
            "skills_active": self._active_skill.name if self._active_skill else None,
            "kb_count": self.kb.count if self.kb else 0,
            "kb_convs": self.kb.conversation_count if self.kb else 0,
        }
        return result
