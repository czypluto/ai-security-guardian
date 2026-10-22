"""Agent Core —— 基于 LangGraph 状态图的 agent 编排。

这里曾经是一个手写的 ``while`` ReAct 循环。循环现在搬进了 ``agent/graph.py``
的状态图，``AgentCore`` 退化成「装配 + 翻译」的薄壳：

  * **装配**：LLMRouter / ToolRegistry / MCP / Skills / KB -> 一张编译好的图
  * **翻译**：把图产出的 custom 事件原样吐出；遇到 ``interrupt()`` 就交给
    调用方去问人，然后用 ``Command(resume=...)`` 续跑

对外契约（``run`` / ``run_stream`` / ``save_conversation`` / ``clear_conversation``
/ ``summary``）与改造前**完全一致**，因此 ``agent_cli.py`` 的调用方式一行都不用改。

顺带修掉的两个旧问题：
  * 「本轮命中哪个技能」现在是**每轮 state**，不是常驻实例属性 —— 旧实现里
    消费者提前跳出生成器或抛异常时 ``_active_skill`` 会永久残留，之后每轮都注入
    同一个技能；这在结构上不可能再发生了。
  * 对话历史由 checkpointer 按 ``thread_id`` 承载，而不是每轮重建
    ``[system, user]`` —— LLM 现在真的能看到上文。
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Generator, Optional

from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from .config import AgentConfig
from .graph import build_graph, build_system_prompt, extract_interrupts, recursion_limit_for
from .graph_model import LLMUnavailableError, build_chat_model
from .llm import LLMRouter
from .mcp_client import MCPManager
from .skill_loader import Skill, SkillManager
from .tools import ToolDef, ToolRegistry, create_tool_registry

if TYPE_CHECKING:
    from .knowledge_base import KnowledgeBase

logger = logging.getLogger("Guardian.Agent")


class AgentCore:
    """ReAct agent: Think -> Act -> Observe -> Repeat（由状态图驱动）。

    装配关系::

        LLM Router（多 provider 故障转移）
          |
        Tool Registry（内置 + MCP 发现 + 技能）
          |
        agent/graph.py 的状态图
          +-- prepare   技能匹配 + KB 检索
          +-- agent     组装提示词 -> 调模型
          +-- approval  interrupt() 等人工批准（仅敏感工具）
          +-- tools     执行（永不重放，副作用恰好一次）
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
        # 兼容保留的旧属性名（agent_cli 的 banner 会读）；真正的「本轮技能」
        # 在图的 state 里，见 graph.GuardianState.active_skill
        self._active_skill: Optional[Skill] = None
        self._last_active_skill: Optional[str] = None

        # Conversation tracking for KB save
        self._conversation_messages: list[dict] = []

        # 图与 thread：thread_id 决定 checkpoint 的归属，clear 时换一个新 thread
        self._thread_id: str = ""
        self._graph_config: dict = {}
        # 审批回调：由驱动方（GUI 的 worker）临时挂上。为空时走 CLI 的 input()。
        self.approval_callback = None
        self._model = build_chat_model(self.llm, config)
        self._graph = build_graph(
            config, self.tools, self._model, skills=self.skills, kb=self.kb,
        )
        self._new_thread()

    # ---- MCP & Skills integration ----

    def _merge_mcp_tools(self):
        """Register MCP-discovered tools into the built-in registry."""
        for mcp_tool in self.mcp.get_all_tools():
            self.tools.register(ToolDef(
                name=mcp_tool.name,
                description=mcp_tool.description,
                parameters=mcp_tool.input_schema.get("properties", {}),
                handler=lambda args, tn=mcp_tool.name: self._mcp_tool_handler(tn, args),
                # 外部 MCP server 可执行任意代码 —— 标注为最高风险等级。
                # 但 requires_approval 保持默认 False：审批名单锁定在三个内置工具上
                # （见 tool 定义处的 APPROVAL_REQUIRED_TOOLS），MCP 工具靠
                # installer 的安装前扫描 + 用户手工 review 把关。
                risk_level="dangerous",
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
        """兼容保留 —— 实际拼装在 graph 的 agent 节点里（同一份实现）。

        工具描述由 `bind_tools` 注入，所以这里能看到的工具名来自 config 的
        默认系统提示词。
        """
        return build_system_prompt(
            self.config, self.skills,
            {"kb_context": kb_context, "active_skill": None},
        )

    # ---- 图 / thread ----

    def _new_thread(self) -> str:
        """换一个 thread_id（= 丢掉上下文，开一段新对话）。

        旧 thread 的 checkpoint 自然成为孤儿；SQLite 里留着不影响新对话。
        """
        self._thread_id = f"guardian-{uuid.uuid4().hex}"
        self._graph_config = {
            "configurable": {"thread_id": self._thread_id},
            "recursion_limit": recursion_limit_for(self.config),
        }
        return self._thread_id

    # ---- Public API ----

    def run(self, user_input: str) -> str:
        """Run agent, return final text."""
        result_parts: list[str] = []
        for event in self.run_stream(user_input):
            if event["type"] == "text":
                result_parts.append(event["content"])
            elif event["type"] == "error":
                result_parts.append(f"\n[Error: {event['content']}]\n")
        return "".join(result_parts)

    def run_stream(self, user_input: str,
                   ephemeral: bool = False) -> Generator[dict, None, None]:
        """跑一轮，产出 `{type: text|tool_start|tool_result|error}` 事件。

        事件格式与改造前完全一致，所以 `agent_cli.display_stream` 无需改动。

        中断控制流：`graph.stream` 遇到 `interrupt()` 时本次迭代就结束了，
        于是在这里问用户，再用 `Command(resume=...)` **新开一次** stream。
        恢复不是「继续同一个生成器」，而是「用新输入再跑一次」。

        `ephemeral=True` 用于 GUI 的「生成安全报告 / 修复建议」这类一次性任务：
        走一个临时 thread，既不污染用户的对话历史，也不写进 KB 落库的消息里。
        """
        graph_config = self._graph_config
        if ephemeral:
            graph_config = {
                **self._graph_config,
                "configurable": {"thread_id": f"ephemeral-{uuid.uuid4().hex}"},
            }
        else:
            self._conversation_messages.append({"role": "user", "content": user_input})

        payload = {
            "messages": [HumanMessage(content=user_input)],
            "user_input": user_input,
        }

        try:
            while True:
                interrupts = []
                for part in self._graph.stream(
                    payload, graph_config,
                    stream_mode=["updates", "custom"], version="v2",
                ):
                    if part["type"] == "custom":
                        # 节点已按旧格式产出事件，直通即可
                        yield part["data"]
                    elif part["type"] == "updates":
                        interrupts.extend(extract_interrupts(part["data"]))

                if not interrupts:
                    break

                decisions = [self._ask_approval(item.value) for item in interrupts]
                # 通常一次只有一个（图会在第一个未恢复的中断处停下）
                payload = Command(resume=decisions[0] if len(decisions) == 1 else decisions)

        except LLMUnavailableError as e:
            yield {"type": "error", "content": str(e)}
            return
        except GraphRecursionError:
            # 兜底：语义上限（agent 节点里的 iteration 判断）本该先触发
            logger.warning("图触及 recursion_limit，按最大迭代截断")
            yield {"type": "text", "content": "[Max iterations reached]"}
            return

        if not ephemeral:
            self._record_result(graph_config)

    def _ask_approval(self, payload: dict) -> dict:
        """向用户征求一次执行批准。

        GUI 会在运行期间临时挂上 ``approval_callback``（由 worker 弹对话框），
        这里优先走它；否则退回终端交互，供 CLI 使用。
        """
        if self.approval_callback is not None:
            return self.approval_callback(payload)

        tool = payload.get("tool", "?")
        args = json.dumps(payload.get("arguments") or {}, ensure_ascii=False)
        risk = payload.get("risk_level", "unknown")

        print(f"\n  \033[33m[需确认]\033[0m {payload.get('message', f'是否允许执行 {tool}?')}"
              f"  \033[90m(风险等级: {risk})\033[0m")
        print(f"  \033[90m工具: {tool}\033[0m")
        print(f"  \033[90m参数: {args[:200]}\033[0m")
        try:
            answer = input("  \033[33m允许执行? (y/N): \033[0m").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"   # 与 agent_cli._confirm_and_save 的既有兜底风格一致

        approved = answer in ("y", "yes")
        return {"approved": approved, "reason": "cli_user" if approved else "cli_denied"}

    def _record_result(self, graph_config: dict = None):
        """一轮结束后把结果回写：KB 落库用的消息 + banner 展示用的技能名。"""
        try:
            values = self._graph.get_state(graph_config or self._graph_config).values or {}
        except Exception as e:  # noqa: BLE001 - 只是记录，失败不该让整轮报错
            logger.debug("读取图状态失败: %s", e)
            return

        final_text = values.get("final_text") or ""
        if final_text:
            self._conversation_messages.append(
                {"role": "assistant", "content": final_text})

        self._last_active_skill = values.get("active_skill")
        # 不在轮次之间残留（旧实现正是这里漏了清理才导致技能粘滞）
        self._active_skill = None

    # ---- Knowledge Base ----

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
        self._last_active_skill = None
        # 换 thread：旧 checkpoint 成为孤儿，历史不会再进新对话
        self._new_thread()

    # ---- Info ----

    @property
    def active_model(self) -> str:
        p = self.llm.active_provider
        return f"{p.name}/{p.model}" if p else "none"

    @property
    def tool_count(self) -> int:
        return len(self.tools.list_all())

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
            "skills_active": self._last_active_skill,
            "kb_chunks": self.kb.get_stats()["bm25_chunks"] if self.kb else 0,
            "kb_convs": self.kb.conversation_count if self.kb else 0,
        }
        return result
