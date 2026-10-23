"""LangGraph 适配层 —— 把自研 ToolDef 包成 LangChain BaseTool。

`ToolDef`（agent/tools.py）是本项目自己的工具抽象，32 个内置工具都以它注册；
`BaseTool` 是 LangGraph / langchain-core 认的形态。

包一层的三个用处：
  1. `requires_approval` / `risk_level` 有了统一载体，供 approval 节点读取；
  2. `_run` 仍委托 `registry.execute()` —— `require_admin` 校验、JSON 序列化、
     异常兜底这些**既有语义一条不少**，两条执行路径不会分叉；
  3. 将来若要用 `ToolNode`（要求 BaseTool），这条路是通的。

注意：图里执行工具走的是 `registry.execute()`（见 agent/graph.py 的 tools 节点），
**不是** `ToolNode` —— 因为审批必须串行、且副作用节点绝不能重放。本模块主要是
元数据载体 + 给未来留口子。
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from .tools import ToolDef, ToolRegistry, schema_properties


def build_object_schema(parameters: dict) -> dict:
    """把 ToolDef.parameters（properties 字典）补成完整 JSON Schema 对象。

    与 `ToolDef.to_openai_schema()` 里内联的结构保持**同一口径** ——
    以每个参数自己的 `required` 键为准，而不是另设一份清单；
    属性内的 `required` 布尔键会被剥离（它不是合法 JSON Schema）。
    """
    parameters = parameters or {}
    return {
        "type": "object",
        "properties": schema_properties(parameters),
        "required": [k for k, v in parameters.items()
                     if isinstance(v, dict) and v.get("required", False)],
    }


class GuardianTool(BaseTool):
    """一个 ToolDef 的 BaseTool 外观；执行委托给 ToolRegistry。"""

    # 注意：不要用 property 覆写 args_schema —— 它在 BaseTool 里是 pydantic 字段，
    # 构造时直接传入更干净。
    parameters: dict = {}
    registry: Any = None
    requires_approval: bool = False
    risk_level: str = "safe"

    def _run(self, *args: Any, **kwargs: Any) -> str:
        # 兼容两种调用约定：LangChain 可能把工具入参作为单个位置 dict 传入，
        # 也可能展开成关键字参数。
        if args and not kwargs and isinstance(args[0], dict):
            payload = dict(args[0])
        else:
            payload = dict(kwargs)
        payload.pop("run_manager", None)
        return self.registry.execute(self.name, payload)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        # 全链路同步执行；不提供真正的异步实现。
        return self._run(*args, **kwargs)


def to_langchain_tool(td: ToolDef, registry: ToolRegistry) -> GuardianTool:
    """单个 ToolDef -> GuardianTool。"""
    return GuardianTool(
        name=td.name,
        description=td.description,
        args_schema=build_object_schema(td.parameters),
        parameters=td.parameters,
        registry=registry,
        requires_approval=bool(getattr(td, "requires_approval", False)),
        risk_level=getattr(td, "risk_level", "safe"),
    )


def to_langchain_tools(registry: ToolRegistry) -> list[GuardianTool]:
    """注册表里的全部内置工具 -> GuardianTool 列表。"""
    return [to_langchain_tool(td, registry) for td in registry.list_all()]
