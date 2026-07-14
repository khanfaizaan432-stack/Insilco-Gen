from __future__ import annotations

import importlib.util

from pydantic import BaseModel


class LangGraphAvailability(BaseModel):
    available: bool
    reason: str


class ControlledLangGraphAdapter:
    """Detect optional LangGraph support without importing or executing a graph."""

    def availability(self) -> LangGraphAvailability:
        package = importlib.util.find_spec("langgraph")
        graph_module = importlib.util.find_spec("langgraph.graph") if package else None
        if package and graph_module:
            return LangGraphAvailability(available=True, reason="langgraph package is importable")
        return LangGraphAvailability(available=False, reason="langgraph package is not installed")
