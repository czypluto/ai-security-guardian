"""LangGraph 状态图 —— 取代手写 while 循环的 agent 编排。

拓扑::

    START → prepare → agent ─┬─(无 tool_calls)→ END
                             └─(有 tool_calls)→ approval → tools → agent
                                                  ↑ 全图唯一的 interrupt()

三个设计要点，都是踩过才知道的：

1. **interrupt() 必须独占一个纯节点。**
   节点在恢复时会**从头重放** —— 框架只把已缓存的中断返回值喂回原来的位置，
   中间代码会再跑一遍（实测确认：恢复时 approval 节点函数被再次进入）。
   若把 interrupt() 放进 tools 节点：工具 #1 已产生真实副作用（起进程 / 写文件）、
   工具 #2 触发中断，用户批准后节点重放 → **工具 #1 被执行两次**。
   独立纯节点重放零代价，tools 节点永不含 interrupt()，因此副作用恰好发生一次。

2. **被取消时停在干净边界。**
   中断点恰好落在 approval 结束、tools 开始之前，所以不存在「工具执行到一半」
   的持久化状态 —— 这让 GUI 侧的超时终止变得安全。

3. **事件契约由节点直接产出。**
   节点内用 ``get_stream_writer()`` 发原来的 ``{type: text|tool_start|tool_result}``
   事件，``AgentCore.run_stream`` 因此近乎直通，``agent_cli.display_stream``
   一行都不用改。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt

from .config import DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger("Guardian.Graph")


# ---- 状态 ----

def _merge_dict(a: Optional[dict], b: Optional[dict]) -> dict:
    """approvals 的合并 reducer —— 多工具/并行写入时按 id 累积而非覆盖。"""
    return {**(a or {}), **(b or {})}


class GuardianState(MessagesState):
    """图状态。

    ``messages`` 由 ``MessagesState`` 提供，带 ``add_messages`` reducer，
    存的是 langchain ``BaseMessage`` 对象 —— 这是 ``bind_tools`` / ``interrupt``
    恢复语义的基础。与 OpenAI dict 的互转集中在 ``graph_model`` 单点完成。

    其余字段语义：
      user_input       本轮原始提问（技能匹配 / KB 检索用）
      kb_context       本轮注入的知识库片段
      active_skill     本轮命中的技能名 —— 注意这是**每轮状态**而非常驻实例属性，
                       所以旧实现里「异常后技能永久粘滞」的 bug 在结构上不可能发生
      iteration        LLM 调用计数（替代原来的 while 计数器）
      approvals        tool_call_id -> 审批决策
      pending_approval 最近一次待审批载荷快照（只读、供日志/UI 观测）
      final_text       本轮最终文本
      error            非致命错误留痕
    """

    user_input: str
    kb_context: str
    active_skill: Optional[str]
    iteration: int
    approvals: Annotated[dict, _merge_dict]
    pending_approval: Optional[dict]
    final_text: str
    error: str


# ---- 事件写出 ----

def _as_text(content) -> str:
    """把消息内容拍平成字符串（content 可能是 str，也可能是多模态 block 列表）。"""
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


def _stream_completion(bound, prompt_messages) -> AIMessage:
    """流式取一次补全：逐块把文本推给 UI，末尾组装成完整 AIMessage。

    事件仍是 ``{"type": "text", "content": <增量>}`` —— 契约不变，只是从
    「一次给整段」变成「分多次给增量」。两个消费方都天然正确：CLI 顺序写出即得全文，
    GUI 累积后渲染即打字机效果。所以 display_stream 与 _drive 都一行不用改。
    """
    accumulated = None
    for chunk in bound.stream(prompt_messages):
        accumulated = chunk if accumulated is None else accumulated + chunk
        piece = _as_text(chunk.content)
        if piece:
            _write({"type": "text", "content": piece})

    if accumulated is None:
        return AIMessage(content="")
    return AIMessage(
        content=_as_text(accumulated.content),
        tool_calls=list(getattr(accumulated, "tool_calls", None) or []),
    )


def _write(payload: dict) -> None:
    """向 custom 流写一个事件。

    不在流式上下文里（例如直接 ``invoke``）时静默忽略 —— 事件是给 UI 的锦上添花，
    不该因为它缺席就让整轮失败。
    """
    try:
        from langgraph.config import get_stream_writer

        get_stream_writer()(payload)
    except Exception:  # noqa: BLE001 - 见上：事件通道不可用不是致命错误
        pass


# ---- 审批策略 ----

def _stdin_is_tty() -> bool:
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except Exception:  # noqa: BLE001 - 某些托管环境 stdin 是怪对象
        return False


def resolve_approval_mode(config, interactive_available: Optional[bool] = None) -> str:
    """决定实际生效的审批模式（纯函数，可单测）。

    - 配置显式指定 ``auto_approve`` / ``auto_reject`` 时直接采纳；
    - 配置为 ``interactive`` 但**没有可交互的 stdin**（管道 / 重定向 / 服务化）时
      降级为 ``auto_reject`` —— fail-closed。

    为什么降级到「拒绝」而不是「批准」：闸门存在的意义就是拦住 run_command /
    install_skill 这类动作，无人可问时自动放行等于把它变成一行装饰性代码。
    本项目其余防线（沙箱白名单、install_skill 的安装前扫描、系统提示里
    「NEVER install MCP servers automatically」）也全是 fail-closed。

    注意：GUI 侧是**人在场**（用 QMessageBox 问），所以它显式设
    ``approval_mode="interactive"`` 且不调用本函数。
    """
    mode = getattr(config, "approval_mode", "interactive") or "interactive"
    if mode != "interactive":
        return mode
    if interactive_available is None:
        interactive_available = _stdin_is_tty()
    return "interactive" if interactive_available else "auto_reject"


def needs_approval(name: str, config, registry=None) -> bool:
    """是否需要人工审批。两个来源任一命中即可。

    1. 工具自带的 ``ToolDef.requires_approval``（主要来源，见 tools.py 注册处）；
    2. 配置层的追加名单 ``config.approval_required_tools``。
    """
    extra = getattr(config, "approval_required_tools", None) or ()
    if name in extra:
        return True
    if registry is not None:
        tool = registry.get(name)
        if tool is not None and getattr(tool, "requires_approval", False):
            return True
    return False


def _risk_of(name: str, registry) -> str:
    tool = registry.get(name) if registry is not None else None
    return getattr(tool, "risk_level", "unknown") if tool is not None else "unknown"


# ---- checkpointer ----

def _default_db_path() -> str:
    root = Path(__file__).resolve().parent.parent
    return str(root / "data" / "guardian_graph.sqlite")


def build_checkpointer(config):
    """按配置建 checkpointer。

    默认 SQLite 单文件：进程崩溃/重启后能用同一个 thread_id 续跑，
    这才是「可恢复」这个卖点真正的兑现方式。Postgres 对桌面程序太荒谬。

    **任何失败都降级到内存 saver** —— 桌面端不该因为某个可选后端装不上就起不来。
    """
    backend = (getattr(config, "checkpoint_backend", "sqlite") or "sqlite").lower()

    if backend == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()

    try:
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver

        path = getattr(config, "checkpoint_db_path", "") or _default_db_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # check_same_thread=False：GUI 侧图在 QThread 上跑，主线程会读取状态
        conn = sqlite3.connect(path, check_same_thread=False)
        logger.info("checkpointer: SQLite (%s)", path)
        return SqliteSaver(conn)
    except Exception as e:  # noqa: BLE001 - 降级是刻意的
        logger.warning("SQLite checkpointer 不可用(%s)，本次回退内存（重启后无法续跑）", e)
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()


# ---- 中断提取 ----

def extract_interrupts(update: Any) -> list:
    """从 ``stream_mode="updates"`` 的一个分片里取出 Interrupt 对象。

    实测形态：``{'__interrupt__': (Interrupt(value={...}, id='...'),)}``，
    与节点输出同层。这里同时容忍「嵌在某个节点名下面」的形态，免得
    某个版本改了排布就静默失灵。
    """
    found: list = []
    if not isinstance(update, dict):
        return found

    direct = update.get("__interrupt__")
    if direct:
        found.extend(direct)

    for value in update.values():
        if isinstance(value, dict):
            nested = value.get("__interrupt__")
            if nested:
                found.extend(nested)
    return found


# ---- 节点工厂 ----

def _retrieve_kb_context(kb, query: str, top_k: int, timeout: float) -> str:
    """取知识库上下文，带超时预算。

    BM25 检索通常毫秒级；保留预算用于兜底异常磁盘 I/O 或索引重建，
    超时后返回空串，退回「本轮没有 KB 上下文」，绝不阻塞。
    """
    if kb is None or not query:
        return ""

    if not timeout or timeout <= 0:
        try:
            return kb.build_context(query, top_k=top_k) or ""
        except Exception as e:  # noqa: BLE001
            logger.debug("KB 检索失败: %s", e)
            return ""

    box: dict = {}

    def worker():
        try:
            box["ctx"] = kb.build_context(query, top_k=top_k) or ""
        except Exception as e:  # noqa: BLE001
            logger.debug("KB 检索失败: %s", e)
            box["ctx"] = ""

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    return box.get("ctx", "")


def build_system_prompt(config, skills, state) -> str:
    """拼系统提示词：基础提示 + KB 上下文 + 命中的技能。

    与改造前 ``AgentCore._build_system_prompt`` 语义一致，只是技能改从
    **本轮 state** 读，而不是常驻的 ``self._active_skill``。
    """
    prompt = config.system_prompt or DEFAULT_SYSTEM_PROMPT

    kb_context = state.get("kb_context") or ""
    if kb_context:
        prompt += "\n\n" + kb_context

    if skills is not None:
        matched = None
        name = state.get("active_skill")
        if name:
            matched = next((s for s in skills.list_all() if s.name == name), None)
        prompt += "\n\n" + skills.build_skills_prompt(matched)

    return prompt


def make_prepare_node(config, skills=None, kb=None):
    """准备节点：技能匹配 + KB 检索 + 迭代计数归零。

    刻意**不含 interrupt()** —— 这样中断恢复时它不会被重放，KB 检索不会白跑第二遍。
    """

    def prepare(state: GuardianState) -> dict:
        user_input = state.get("user_input") or ""
        active_skill = None
        if skills is not None and user_input:
            matched = skills.match_triggers(user_input)
            active_skill = matched.name if matched else None

        kb_context = ""
        if kb is not None and getattr(config, "knowledge_base_enabled", True):
            kb_context = _retrieve_kb_context(
                kb, user_input,
                top_k=getattr(config, "knowledge_base_top_k", 3),
                timeout=getattr(config, "kb_context_timeout", 4.0),
            )

        return {"active_skill": active_skill, "kb_context": kb_context,
                "iteration": 0, "error": ""}

    return prepare


def make_agent_node(config, registry, model, skills=None):
    """LLM 节点：组装提示 -> 调模型 -> 无工具调用则终局。"""

    def agent(state: GuardianState) -> dict:
        messages = state["messages"]
        iteration = state.get("iteration", 0)

        # 迭代上限：语义与改造前 `while iterations < max_iterations` 完全一致。
        # 真正的闸门在这里，recursion_limit 只作兜底（见 build_graph 的调用方）。
        if iteration >= getattr(config, "max_iterations", 10):
            text = "[Max iterations reached]"
            _write({"type": "text", "content": text})
            return {"messages": [AIMessage(content=text)], "final_text": text}

        system_prompt = build_system_prompt(config, skills, state)
        history_limit = getattr(config, "history_limit", 20) or 0
        history = list(messages[-history_limit:]) if history_limit else list(messages)

        prompt_messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
        prompt_messages.extend(history)

        # 每次现取 schema：MCP 工具可能在 AgentCore 构造之后才注册进来
        schemas = registry.get_schemas()
        bound = model.bind_tools(schemas) if schemas else model

        streaming = bool(getattr(config, "stream_output", True))
        if streaming:
            ai_message = _stream_completion(bound, prompt_messages)
        else:
            ai_message = bound.invoke(prompt_messages)

        update: dict = {"messages": [ai_message], "iteration": iteration + 1}
        if not getattr(ai_message, "tool_calls", None):
            text = _as_text(ai_message.content)
            update["final_text"] = text
            # 流式路径已在 _stream_completion 里逐块发过，这里不能再发一遍
            if not streaming:
                _write({"type": "text", "content": text})
        return update

    return agent


def make_approval_node(config, registry=None):
    """审批节点：**全图唯一的 interrupt() 所在**，且是纯函数。

    纯 = 只读 state、只调 interrupt()、只返回决策 dict，没有任何副作用。
    因此恢复时重放它零代价。

    若一次响应里有多个待审批调用，它们是**天然串行**的：节点在第一个未恢复的
    interrupt() 处就停下并返回本次 stream，外部拿到一个中断 -> 问一次 ->
    ``Command(resume=...)`` 再跑一次 -> 节点重放时第一个 interrupt() 直接返回
    缓存值，于是走到第二个。UX 因此是「一次问一个」，正确且不别扭。
    """

    def approval(state: GuardianState) -> dict:
        last = state["messages"][-1]
        decisions: dict[str, dict] = {}

        for tc in getattr(last, "tool_calls", None) or []:
            name = tc.get("name", "")
            if not needs_approval(name, config, registry):
                continue
            decisions[tc.get("id", "")] = _ask(tc, config, registry)

        return {"approvals": decisions, "pending_approval": None}

    return approval


def _ask(tc: dict, config, registry) -> dict:
    """取一次审批决策 —— 可能在此处 interrupt() 并挂起。"""
    name = tc.get("name", "")
    mode = getattr(config, "approval_mode", "interactive") or "interactive"

    if mode == "auto_approve":
        return {"approved": True, "reason": "auto_approve"}
    if mode == "auto_reject":
        # 无人可问 -> 拒绝。fail-closed，见 resolve_approval_mode 的说明。
        return {"approved": False, "reason": "no_human"}

    # interrupt() 的载荷必须可 JSON 序列化（要进 checkpoint）
    decision = interrupt({
        "kind": "approval_request",
        "tool": name,
        "arguments": tc.get("args") or {},
        "risk_level": _risk_of(name, registry),
        "tool_call_id": tc.get("id", ""),
        "message": f"是否允许执行 {name}?",
    })

    if isinstance(decision, dict):
        return decision
    return {"approved": bool(decision)}  # 容忍调用方直接回一个裸 bool


def make_tools_node(config, registry):
    """工具执行节点 —— **永不含 interrupt()，因此永不重放**。

    副作用恰好发生一次，这是整个设计的核心保证。
    """

    def tools(state: GuardianState) -> dict:
        last = state["messages"][-1]
        approvals = state.get("approvals") or {}
        results: list[BaseMessage] = []

        for tc in getattr(last, "tool_calls", None) or []:
            name = tc.get("name", "")
            args = tc.get("args") or {}
            call_id = tc.get("id", "")

            decision = approvals.get(call_id)
            if decision is not None and not decision.get("approved"):
                # 被拒绝：不发 tool_start / tool_result —— UI 上不该留下「执行过」的
                # 痕迹，用户刚刚在审批提示里看过这个调用了。
                # 但仍要回一条 ToolMessage：OpenAI 要求每个 tool_call id 都有结果，
                # 缺口会让下一轮请求直接 400。
                content = json.dumps({
                    "status": "rejected_by_user",
                    "reason": decision.get("reason", ""),
                    "message": "该操作已被用户拒绝。不要重试同一个工具调用；"
                               "请改用其他方式，或向用户说明为什么需要这个操作。",
                }, ensure_ascii=False)
                results.append(ToolMessage(content=content, tool_call_id=call_id, name=name))
                continue

            _write({"type": "tool_start", "name": name, "arguments": args})
            content = registry.execute(name, args)
            results.append(ToolMessage(content=content, tool_call_id=call_id, name=name))
            _write({"type": "tool_result", "name": name, "result": content})

        return {"messages": results}

    return tools


def route_after_agent(state: GuardianState) -> Literal["approval", "__end__"]:
    """路由函数 —— 只读最后一条消息，零副作用。"""
    last = state["messages"][-1]
    return "approval" if getattr(last, "tool_calls", None) else END


# ---- 构图 ----

def build_graph(config, registry, model, checkpointer=None, skills=None, kb=None):
    """编译状态图。

    参数:
      config:       AgentConfig
      registry:     ToolRegistry（执行与 schema 的真相来源）
      model:        BaseChatModel（通常是 graph_model.GuardianChatModel）
      checkpointer: 不传则按 config 自建；interrupt() 依赖它做状态持久化
      skills/kb:    可选，供 prepare / agent 节点使用
    """
    if checkpointer is None:
        checkpointer = build_checkpointer(config)

    builder = StateGraph(GuardianState)
    builder.add_node("prepare", make_prepare_node(config, skills=skills, kb=kb))
    builder.add_node("agent", make_agent_node(config, registry, model, skills=skills))
    builder.add_node("approval", make_approval_node(config, registry=registry))
    builder.add_node("tools", make_tools_node(config, registry))

    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "agent")
    # 条件边的映射表里必须显式给 END 兜底，否则路由到未映射值会让图挂起
    builder.add_conditional_edges(
        "agent", route_after_agent, {"approval": "approval", END: END}
    )
    builder.add_edge("approval", "tools")
    builder.add_edge("tools", "agent")  # ReAct 回环

    return builder.compile(checkpointer=checkpointer)


def recursion_limit_for(config) -> int:
    """LangGraph 的 recursion_limit 是**超级步**计数，不是 LLM 轮数。

    一轮 = prepare(1) + agent(1) + [approval + tools] × k + 终局 agent(1)，
    最坏约 2*max_iterations + 3。LangGraph 默认 25，在 max_iterations=10 时
    会**先于语义上限触发** —— 所以必须显式抬高，留出余量让语义闸门先打招呼，
    recursion_limit 只作最后兜底。
    """
    return 4 * getattr(config, "max_iterations", 10) + 10
