"""工具包统一注册入口。

新增工具时，只需在此导入对应模块，装饰器会自动完成注册。
"""
from app.agent.tools import agri, knowledge, weather  # noqa: F401
from app.agent.tools.base import registry, tool  # noqa: F401

__all__ = ["registry", "tool"]
