"""Scripted fake chat model for deterministic agent-loop tests (specs/agent.md §7).

No network, no API key. Each invoke() returns (or raises) the next scripted
item; when the script is exhausted it returns an AIMessage with no tool calls.
"""

from __future__ import annotations

import itertools
from typing import Any

from langchain_core.messages import AIMessage

_ids = itertools.count(1)


def call(name: str, **args: Any) -> dict:
    """One well-formed tool call."""
    return {"name": name, "args": args, "id": f"call_{next(_ids)}", "type": "tool_call"}


def turn(*calls: dict, content: str = "") -> AIMessage:
    """An AIMessage carrying the given tool calls."""
    return AIMessage(content=content, tool_calls=list(calls))


def bad_json_turn(name: str, raw_args: str) -> AIMessage:
    """An AIMessage whose single tool call has unparseable JSON arguments."""
    return AIMessage(content="", invalid_tool_calls=[{
        "name": name, "args": raw_args, "id": f"call_{next(_ids)}",
        "error": "invalid JSON", "type": "invalid_tool_call",
    }])


class ScriptedModel:
    def __init__(self, responses: list[AIMessage | Exception]) -> None:
        self.responses = list(responses)
        self.inputs: list[list[Any]] = []
        self.bound_tools: list[Any] | None = None
        self.bound_tool_choice: Any = None
        self.bind_kwargs: dict = {}

    def bind_tools(self, tools, tool_choice=None, **kwargs):
        self.bound_tools = list(tools)
        self.bound_tool_choice = tool_choice
        self.bind_kwargs = kwargs
        return self

    def invoke(self, messages, config=None, **kwargs):
        self.inputs.append(list(messages))
        if not self.responses:
            return AIMessage(content="")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
