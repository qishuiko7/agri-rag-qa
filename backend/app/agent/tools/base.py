"""Agent 工具注册机制。

每个工具由三部分组成：
1. schema —— 提供给大模型的 function 定义（OpenAI tools 格式）
2. handler —— 实际执行函数，入参为 dict，返回结构化结果
3. meta —— 展示信息（中文名、说明）

新增工具只需在 tools/__init__.py 里注册，执行器自动发现。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    """一个可被 Agent 调用的工具。"""

    name: str
    label: str
    description: str
    parameters: dict
    handler: Callable[[dict], dict]
    tags: list[str] = field(default_factory=list)

    def schema(self) -> dict:
        """转为 OpenAI function calling 的 tools 定义。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def run(self, args: dict) -> dict:
        """执行工具，异常统一转成可读错误，避免中断 Agent 循环。"""
        try:
            result = self.handler(args or {})
            if not isinstance(result, dict):
                result = {"result": result}
            return {"ok": True, **result}
        except Exception as exc:  # noqa: BLE001
            logger.warning("工具 %s 执行失败：%s", self.name, exc)
            return {"ok": False, "error": str(exc)}


class ToolRegistry:
    """工具注册表。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def describe(self) -> list[dict]:
        """给前端展示的工具清单。"""
        return [
            {
                "name": t.name,
                "label": t.label,
                "description": t.description,
                "tags": t.tags,
            }
            for t in self._tools.values()
        ]


registry = ToolRegistry()


def tool(
    *,
    name: str,
    label: str,
    description: str,
    parameters: dict,
    tags: list[str] | None = None,
):
    """装饰器：把函数注册为工具。"""

    def deco(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
        registry.register(
            Tool(
                name=name,
                label=label,
                description=description,
                parameters=parameters,
                handler=fn,
                tags=tags or [],
            )
        )
        return fn

    return deco
