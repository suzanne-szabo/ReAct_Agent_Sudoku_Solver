"""LangGraph ReAct loop: llm -> controller -> tool -> continue?

Implements specs/agent.md §1-§4 (architecture §4.8). The graph state holds only
the conversation and the current turn's approval. The ``Session``,
``Controller`` and bound model reach the nodes through
``config["configurable"]``, never through graph state, so nothing the model
produces can touch application state except through ``Controller`` methods.

    START -> llm -> controller --(terminal already set)--> END
                        |
                        v
                      tool -> continue? --(terminal)--> END
                                  |
                                  +--(otherwise)--> llm
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Annotated, Callable, Optional, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from sudoku_agent import prompts
from sudoku_agent.controller import Approval, Config, Controller, Observation, TerminalStatus, TraceEntry
from sudoku_agent.llm import make_model
from sudoku_agent.session import Session
from sudoku_agent.tools import tool_definitions

RETRY_DELAY_SECONDS = 2   # agent §2.1: one retry after a failed model call

StepCallback = Callable[[TraceEntry], None]


class AgentState(TypedDict):
    """LangGraph state (agent §2): the conversation and the pending approval."""

    messages: Annotated[list[AnyMessage], add_messages]
    pending: Optional[Approval]


@dataclass(frozen=True)
class RunResult:
    """Outcome of one run (agent §4)."""

    status: TerminalStatus
    reason: str
    actions_used: int
    trace: tuple[TraceEntry, ...]
    final_grid: tuple[tuple[int, ...], ...]
    solved: bool


# ---------------------------------------------------------------- helpers

def _context(config: RunnableConfig) -> dict:
    """The run objects passed to every node through the run config."""
    return config["configurable"]


def _tool_calls(ai: AIMessage) -> list[tuple[str, dict | str, str]]:
    """``(name, raw_args, call_id)`` for every call, valid ones first (agent §2.2).

    Calls whose arguments could not be parsed keep their raw argument string,
    so they fail schema validation (P3) instead of crashing the loop.
    """
    calls = [(call["name"], call["args"], call["id"]) for call in ai.tool_calls]
    calls += [
        (call.get("name") or "", call.get("args") or "", call.get("id") or "")
        for call in ai.invalid_tool_calls
    ]
    return calls


def _last_ai_message(messages: list[BaseMessage]) -> AIMessage:
    return next(m for m in reversed(messages) if isinstance(m, AIMessage))


def _tool_message(observation: Observation, call_id: str) -> ToolMessage:
    return ToolMessage(content=observation.to_json(), tool_call_id=call_id, name=observation.tool)


def _report_steps(context: dict, first_new_step: int) -> None:
    """Call ``on_step`` for each trace entry appended since ``first_new_step``."""
    on_step: StepCallback | None = context["on_step"]
    if on_step is not None:
        for entry in context["controller"].trace[first_new_step:]:
            on_step(entry)


def recent_turns(messages: list[BaseMessage], window: int) -> list[BaseMessage]:
    """The last ``window`` complete turns (agent §3).

    A turn is one ``AIMessage`` and the ``ToolMessage``s that follow it, so the
    window never splits a turn or leaves an orphaned ``ToolMessage``.
    """
    turns: list[list[BaseMessage]] = []
    for message in messages:
        if isinstance(message, AIMessage):
            turns.append([message])
        elif turns:
            turns[-1].append(message)
    selected = turns[-window:] if window > 0 else []
    return [message for turn in selected for message in turn]


def model_input(messages: list[BaseMessage], session: Session, controller: Controller) -> list[BaseMessage]:
    """System prompt, recent history, then the regenerated status message (agent §3)."""
    history = recent_turns(messages, session.config.history_window)
    if messages:
        status = prompts.status_message(session, controller)
    else:
        status = prompts.initial_message(session, controller)
    return [SystemMessage(content=prompts.SYSTEM_PROMPT), *history, status]


# ---------------------------------------------------------------- nodes (agent §2.1-§2.4)

def _llm_node(state: AgentState, config: RunnableConfig) -> Command:
    """Call the model once, retrying once after a short delay on an exception."""
    context = _context(config)
    controller: Controller = context["controller"]
    request = model_input(state["messages"], context["session"], controller)
    try:
        ai = context["model"].invoke(request)
    except Exception:
        time.sleep(RETRY_DELAY_SECONDS)
        try:
            ai = context["model"].invoke(request)
        except Exception as error:
            controller.record_model_error(error)
            return Command(goto="continue")
    return Command(update={"messages": [ai]}, goto="controller")


def _controller_node(state: AgentState, config: RunnableConfig) -> Command:
    """Validate the first call, reject any extra calls (P10), answer every call id."""
    context = _context(config)
    controller: Controller = context["controller"]
    calls = _tool_calls(state["messages"][-1])
    if not calls:
        controller.record_no_action()
        return Command(goto="continue")

    first_new_step = len(controller.trace)
    (name, raw_args, call_id), *extra = calls
    replies: list[ToolMessage] = []
    pending = None
    result = controller.validate(name, raw_args)
    if isinstance(result, Approval):
        pending = result
    else:
        replies.append(_tool_message(result, call_id))
    for extra_name, extra_args, extra_id in extra:
        replies.append(_tool_message(controller.reject_extra_call(extra_name, extra_args), extra_id))
    _report_steps(context, first_new_step)

    goto = END if controller.terminal_status is not None else "tool"
    return Command(update={"messages": replies, "pending": pending}, goto=goto)


def _tool_node(state: AgentState, config: RunnableConfig) -> dict:
    """Execute the approved call, if any, and return its observation to the model."""
    pending = state["pending"]
    if pending is None:
        return {}
    context = _context(config)
    controller: Controller = context["controller"]
    first_new_step = len(controller.trace)
    observation = controller.execute(pending)
    _report_steps(context, first_new_step)
    _, _, call_id = _tool_calls(_last_ai_message(state["messages"]))[0]
    return {"messages": [_tool_message(observation, call_id)], "pending": None}


def _continue_node(state: AgentState, config: RunnableConfig) -> Command:
    """Apply the ordered terminal checks; end the run or loop back to the model."""
    controller: Controller = _context(config)["controller"]
    return Command(goto=END if controller.check_terminal() is not None else "llm")


def build_graph() -> CompiledStateGraph:
    """Compile the ReAct loop of agent §2."""
    builder = StateGraph(AgentState)
    builder.add_node("llm", _llm_node, destinations=("controller", "continue"))
    builder.add_node("controller", _controller_node, destinations=("tool", "continue", END))
    builder.add_node("tool", _tool_node)
    builder.add_node("continue", _continue_node, destinations=("llm", END))
    builder.add_edge(START, "llm")
    builder.add_edge("tool", "continue")
    return builder.compile()


# ---------------------------------------------------------------- public entry point (agent §4)

def run(puzzle: str, config: Config = Config(), model=None,
        on_step: StepCallback | None = None) -> RunResult:
    """Run one bounded episode on ``puzzle`` and report how it ended.

    ``model=None`` uses ``llm.make_model(config)``. Model and tool problems
    become terminal statuses; only a malformed puzzle raises (``ValueError``).
    """
    session = Session.new(puzzle, config)
    controller = Controller(session, config)
    try:
        chat_model = model if model is not None else make_model(config)
        bound_model = chat_model.bind_tools(tool_definitions(), tool_choice="required")
    except Exception as error:   # e.g. a missing API key: report it as a model error
        controller.record_model_error(error)
        controller.check_terminal()
    else:
        build_graph().invoke(
            {"messages": [], "pending": None},
            config={
                "recursion_limit": 4 * config.max_actions + 10,   # agent §2.5 backstop
                "configurable": {
                    "session": session,
                    "controller": controller,
                    "model": bound_model,
                    "on_step": on_step,
                },
            },
        )
    return RunResult(
        status=controller.terminal_status,
        reason=controller.terminal_reason,
        actions_used=controller.actions_used,
        trace=controller.trace,
        final_grid=session.board.grid(),
        solved=controller.terminal_status is TerminalStatus.SOLVED,
    )
