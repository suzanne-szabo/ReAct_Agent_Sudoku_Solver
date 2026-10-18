"""Black-box tests for the LangGraph ReAct loop (sudoku_agent.agent), derived from specs/agent.md.

All tests use the scripted fake model: no network, no API key.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from sudoku_agent.agent import RunResult, run
from sudoku_agent.controller import Config, TerminalStatus
from fakes import ScriptedModel, bad_json_turn, call, turn
from conftest import EASY, EASY_SOLUTION, solution_placements, to_grid

TOOL_NAMES = {
    "read_board", "read_cell", "read_row", "read_col", "read_box",
    "place_number", "undo", "kb_tell", "kb_ask", "kb_infer_cell", "kb_clear", "submit",
}


def solving_script():
    turns = [turn(call("place_number", row=r, col=c, digit=d))
             for r, c, d in solution_placements(EASY, EASY_SOLUTION)]
    return turns + [turn(call("submit"))]


def tool_messages(msgs):
    return [m for m in msgs if isinstance(m, ToolMessage)]


# ---------------------------------------------------------------- happy path

def test_happy_path_solves():
    model = ScriptedModel(solving_script())
    result = run(EASY, Config(), model=model)
    assert isinstance(result, RunResult)
    assert result.status is TerminalStatus.SOLVED
    assert result.solved is True
    assert result.actions_used == 51 + 1
    assert result.final_grid == to_grid(EASY_SOLUTION)
    assert len(result.trace) == 52
    assert result.reason


# ---------------------------------------------------------------- model input

def test_first_input_is_system_then_task():
    model = ScriptedModel([])
    run(EASY, Config(), model=model)
    first = model.inputs[0]
    assert isinstance(first[0], SystemMessage)
    assert isinstance(first[-1], HumanMessage)
    assert "Solve this Sudoku." in first[-1].content
    assert "1  53. .7. ..." in first[-1].content


def test_observation_and_status_reach_model():
    model = ScriptedModel([turn(call("place_number", row=1, col=3, digit=4))])
    run(EASY, Config(), model=model)
    second = model.inputs[1]
    tms = tool_messages(second)
    assert len(tms) == 1
    obs = json.loads(tms[0].content)
    assert obs["accepted"] is True
    assert obs["budget_remaining"] == 499
    status = second[-1]
    assert isinstance(status, HumanMessage)
    assert "1  534 .7. ..." in status.content
    assert "budget remaining: 499" in status.content
    assert "empty: 50" in status.content


def test_binding_forced_tool_choice_and_all_tools():
    from langchain_core.utils.function_calling import convert_to_openai_tool
    model = ScriptedModel([])
    run(EASY, Config(), model=model)
    assert model.bound_tool_choice == "required"
    names = {convert_to_openai_tool(t)["function"]["name"] for t in model.bound_tools}
    assert names == TOOL_NAMES


# ---------------------------------------------------------------- model text cannot win

def test_text_claiming_success_is_no_action():
    model = ScriptedModel([AIMessage(content="SOLVED! The puzzle is complete.")])
    result = run(EASY, Config(), model=model)
    assert result.status is TerminalStatus.NO_ACTION
    assert result.solved is False
    assert result.actions_used == 0
    assert result.final_grid == to_grid(EASY)


# ---------------------------------------------------------------- limits

def test_rejection_limit_leaves_board_unchanged():
    model = ScriptedModel([turn(call("place_number", row=1, col=1, digit=5)) for _ in range(10)])
    result = run(EASY, Config(), model=model)
    assert result.status is TerminalStatus.REJECTION_LIMIT
    assert result.actions_used == 5
    assert result.final_grid == to_grid(EASY)
    assert all(e.policy == "P4" for e in result.trace)


def test_action_limit():
    model = ScriptedModel([turn(call("read_board")) for _ in range(10)])
    result = run(EASY, Config(max_actions=3), model=model)
    assert result.status is TerminalStatus.ACTION_LIMIT
    assert result.actions_used == 3
    assert len(model.inputs) == 3


# ---------------------------------------------------------------- one call per turn

def test_extra_calls_rejected_and_every_call_answered():
    first = call("place_number", row=1, col=3, digit=4)
    second = call("place_number", row=1, col=4, digit=6)
    model = ScriptedModel([turn(first, second)])
    result = run(EASY, Config(), model=model)
    assert result.final_grid[0][2] == 4
    assert result.final_grid[0][3] == 0
    assert result.actions_used == 2
    assert [e.policy for e in result.trace] == [None, "P10"]
    ids = [m.tool_call_id for m in tool_messages(model.inputs[1])]
    assert sorted(ids) == sorted([first["id"], second["id"]])


def test_invalid_json_args_become_p3():
    model = ScriptedModel([bad_json_turn("place_number", '{"row": 1, "col":')])
    result = run(EASY, Config(), model=model)
    assert result.trace[0].policy == "P3"
    assert result.trace[0].accepted is False
    assert result.final_grid == to_grid(EASY)
    assert len(tool_messages(model.inputs[1])) == 1


def test_first_call_rejected_still_answered():
    model = ScriptedModel([turn(call("fly"))])
    result = run(EASY, Config(), model=model)
    assert result.trace[0].policy == "P2"
    tms = tool_messages(model.inputs[1])
    assert len(tms) == 1 and json.loads(tms[0].content)["accepted"] is False


# ---------------------------------------------------------------- model errors

def test_single_model_error_is_retried():
    model = ScriptedModel([RuntimeError("blip"), turn(call("read_board"))])
    result = run(EASY, Config(), model=model)
    assert [e.tool for e in result.trace] == ["read_board"]
    assert result.status is TerminalStatus.NO_ACTION        # script then runs out


def test_two_consecutive_model_errors_end_run():
    model = ScriptedModel([RuntimeError("down"), RuntimeError("still down")])
    result = run(EASY, Config(), model=model)
    assert result.status is TerminalStatus.MODEL_ERROR
    assert result.actions_used == 0


# ---------------------------------------------------------------- history window

def test_history_window_keeps_complete_turns():
    model = ScriptedModel([turn(call("read_row", row=i)) for i in range(1, 7)])
    run(EASY, Config(history_window=2), model=model)
    last = model.inputs[-1]
    assert isinstance(last[0], SystemMessage)
    assert isinstance(last[-1], HumanMessage)
    middle = last[1:-1]
    ais = [m for m in middle if isinstance(m, AIMessage)]
    assert 1 <= len(ais) <= 2
    known_ids = {tc["id"] for m in ais for tc in m.tool_calls}
    for m in tool_messages(middle):
        assert m.tool_call_id in known_ids          # no orphaned ToolMessage
    for m in ais:                                    # and every call has its answer
        answered = {t.tool_call_id for t in tool_messages(middle)}
        assert {tc["id"] for tc in m.tool_calls} <= answered
    # the most recent turn (read_row 6) is present
    assert any(tc["args"] == {"row": 6} for m in ais for tc in m.tool_calls)


# ---------------------------------------------------------------- trace & callbacks

def test_trace_one_entry_per_tool_call_and_on_step():
    seen = []
    model = ScriptedModel([turn(call("read_board")), turn(call("fly")), turn(call("undo"))])
    result = run(EASY, Config(), model=model, on_step=seen.append)
    assert [e.tool for e in result.trace] == ["read_board", "fly", "undo"]
    assert [e.step for e in seen] == [1, 2, 3]


def test_malformed_puzzle_raises():
    with pytest.raises(ValueError):
        run("123", Config(), model=ScriptedModel([]))
