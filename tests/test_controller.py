"""Black-box tests for sudoku_agent.controller, derived from specs/controller.md."""

from __future__ import annotations

import json

import pytest

from sudoku_agent.controller import (
    Approval, Config, Controller, Observation, TerminalStatus, TraceEntry,
)
from sudoku_agent.session import Session
from conftest import EASY, EASY_SOLUTION, WRONG_LEGAL_NO_DEAD, solution_placements, to_grid

SOLVE_STEPS = solution_placements(EASY, EASY_SOLUTION)       # 51 placements


def make(**cfg):
    config = Config(**cfg)
    session = Session.new(EASY, config)
    return session, Controller(session, config)


def state(session):
    return session.board.grid(), session.board.depth, session.kb.agent_facts()


def place(ctl, r, c, d):
    return ctl.handle("place_number", {"row": r, "col": c, "digit": d})


def solve(ctl):
    for r, c, d in SOLVE_STEPS:
        assert place(ctl, r, c, d).accepted
    return ctl.handle("submit", {})


# ---------------------------------------------------------------- config & basic handling

def test_config_defaults():
    c = Config()
    assert (c.max_actions, c.max_consecutive_rejections, c.history_window) == (500, 5, 12)
    assert c.model_name == "Qwen3.8-27B"


def test_accepted_call_observation():
    session, ctl = make()
    obs = ctl.handle("read_cell", {"row": 1, "col": 3})
    assert isinstance(obs, Observation)
    assert (obs.tool, obs.accepted, obs.policy, obs.reason) == ("read_cell", True, None, None)
    assert obs.data["candidates"] == [1, 2, 4]
    assert obs.budget_remaining == 499
    assert ctl.actions_used == 1 and ctl.budget_remaining == 499


def test_observation_to_json():
    _, ctl = make()
    obs = ctl.handle("read_board", {})
    parsed = json.loads(obs.to_json())
    assert parsed["budget_remaining"] == 499
    assert parsed["accepted"] is True
    assert "data" in parsed


# ---------------------------------------------------------------- policies P1–P10

def _assert_rejected(ctl, session, obs, policy, reason, before, charged=True, used_before=0):
    assert obs.accepted is False
    assert (obs.policy, obs.reason) == (policy, reason)
    assert obs.message
    assert state(session) == before
    assert ctl.actions_used == used_before + (1 if charged else 0)
    assert ctl.trace[-1].policy == policy


def test_p1_after_terminal_not_charged():
    session, ctl = make(max_actions=1)
    ctl.handle("read_board", {})
    assert ctl.check_terminal() is TerminalStatus.ACTION_LIMIT
    before, n_trace = state(session), len(ctl.trace)
    obs = ctl.handle("read_board", {})
    _assert_rejected(ctl, session, obs, "P1", "TERMINAL", before, charged=False, used_before=1)
    assert len(ctl.trace) == n_trace + 1


def test_p2_unknown_tool():
    session, ctl = make()
    before = state(session)
    _assert_rejected(ctl, session, ctl.handle("fly", {}), "P2", "UNKNOWN_TOOL", before)


@pytest.mark.parametrize("raw", [
    {"row": "1", "col": 3, "digit": 4},
    {"row": 1, "col": 3},
    {"row": 1, "col": 3, "digit": 4, "x": 0},
    {"row": 0, "col": 3, "digit": 4},
    '{"row": 1, "col":',            # not JSON
    '[1, 3, 4]',                    # JSON but not an object
])
def test_p3_bad_args(raw):
    session, ctl = make()
    before = state(session)
    _assert_rejected(ctl, session, ctl.handle("place_number", raw), "P3", "BAD_ARGS", before)


def test_json_string_args_accepted():
    session, ctl = make()
    obs = ctl.handle("place_number", '{"row": 1, "col": 3, "digit": 4}')
    assert obs.accepted is True
    assert session.board.cell(1, 3) == 4


def test_p4_given_cell():
    session, ctl = make()
    before = state(session)
    _assert_rejected(ctl, session, place(ctl, 1, 1, 5), "P4", "GIVEN_CELL", before)


def test_p5_cell_filled():
    session, ctl = make()
    place(ctl, 1, 3, 4)
    before = state(session)
    _assert_rejected(ctl, session, place(ctl, 1, 3, 2), "P5", "CELL_FILLED", before, used_before=1)


def test_p6_conflict():
    session, ctl = make()
    before = state(session)
    _assert_rejected(ctl, session, place(ctl, 1, 3, 5), "P6", "CONFLICT", before)


def test_p7_empty_undo():
    session, ctl = make()
    before = state(session)
    _assert_rejected(ctl, session, ctl.handle("undo", {}), "P7", "EMPTY_STACK", before)


@pytest.mark.parametrize("tool,args,reason", [
    ("kb_tell", {"formula": "p &"}, "PARSE_ERROR"),
    ("kb_tell", {"formula": "v131"}, "INCONSISTENT"),
    ("kb_ask", {"formula": "v105"}, "INVALID_SYMBOL"),
])
def test_p8_kb_rejections(tool, args, reason):
    session, ctl = make()
    before = state(session)
    _assert_rejected(ctl, session, ctl.handle(tool, args), "P8", reason, before)


def test_p8_kb_inconsistent_for_infer_cell():
    session, ctl = make()
    place(ctl, *WRONG_LEGAL_NO_DEAD)
    before = state(session)
    obs = ctl.handle("kb_infer_cell", {"row": 2, "col": 2})
    _assert_rejected(ctl, session, obs, "P8", "KB_INCONSISTENT", before, used_before=1)


def test_p9_invalid_submit():
    session, ctl = make()
    before = state(session)
    obs = ctl.handle("submit", {})
    _assert_rejected(ctl, session, obs, "P9", "INVALID_SOLUTION", before)
    assert len(obs.data["reasons"]) == 10 and obs.data["total"] == 78
    assert ctl.check_terminal() is None


def test_p10_extra_call():
    session, ctl = make()
    before = state(session)
    obs = ctl.reject_extra_call("place_number", {"row": 1, "col": 3, "digit": 4})
    _assert_rejected(ctl, session, obs, "P10", "ONE_CALL_PER_TURN", before)
    assert ctl.consecutive_rejections == 1


# ---------------------------------------------------------------- priority between policies

def test_bad_args_on_given_cell_reports_p3():
    _, ctl = make()
    assert ctl.handle("place_number", {"row": 1, "col": 1, "digit": "5"}).policy == "P3"


def test_given_cell_that_conflicts_reports_p4():
    _, ctl = make()
    assert place(ctl, 1, 1, 3).policy == "P4"


def test_call_after_solved_is_p1_and_not_charged():
    _, ctl = make()
    assert solve(ctl).accepted
    assert ctl.check_terminal() is TerminalStatus.SOLVED
    used = ctl.actions_used
    obs = ctl.handle("read_board", {})
    assert obs.policy == "P1"
    assert ctl.actions_used == used


# ---------------------------------------------------------------- validate / execute split

def test_validate_returns_approval_without_mutation_and_charges_once():
    session, ctl = make()
    before = state(session)
    approval = ctl.validate("place_number", {"row": 1, "col": 3, "digit": 4})
    assert isinstance(approval, Approval)
    assert approval.tool == "place_number"
    assert (approval.args.row, approval.args.col, approval.args.digit) == (1, 3, 4)
    assert state(session) == before
    assert ctl.actions_used == 1
    assert len(ctl.trace) == 0                 # trace written after execute
    obs = ctl.execute(approval)
    assert obs.accepted is True
    assert session.board.cell(1, 3) == 4
    assert ctl.actions_used == 1               # not charged twice
    assert len(ctl.trace) == 1


def test_validate_rejection_is_observation():
    session, ctl = make()
    obs = ctl.validate("place_number", {"row": 1, "col": 1, "digit": 5})
    assert isinstance(obs, Observation) and obs.policy == "P4"
    assert len(ctl.trace) == 1


@pytest.mark.parametrize("tool,args", [
    ("read_board", {}), ("read_cell", {"row": 5, "col": 5}), ("read_row", {"row": 2}),
    ("read_col", {"col": 7}), ("read_box", {"box": 3}), ("get_candidates", {"row": 1, "col": 3}),
    ("place_number", {"row": 1, "col": 3, "digit": 4}), ("kb_tell", {"formula": "p"}),
    ("kb_ask", {"formula": "v134"}), ("kb_infer_cell", {"row": 1, "col": 3}), ("kb_clear", {}),
])
def test_validated_requests_execute_without_rejection(tool, args):
    _, ctl = make()
    approval = ctl.validate(tool, args)
    assert isinstance(approval, Approval)
    assert ctl.execute(approval).accepted is True


# ---------------------------------------------------------------- budget

def test_budget_arithmetic():
    _, ctl = make()
    for i in range(1, 8):
        obs = ctl.handle("read_board", {}) if i % 2 else ctl.handle("fly", {})
        assert obs.budget_remaining == 500 - i
    assert ctl.actions_used == 7


def test_action_limit():
    _, ctl = make(max_actions=3)
    ctl.handle("read_board", {}); ctl.handle("read_board", {})
    assert ctl.check_terminal() is None
    obs = ctl.handle("read_board", {})
    assert obs.budget_remaining == 0
    assert ctl.check_terminal() is TerminalStatus.ACTION_LIMIT
    assert ctl.terminal_status is TerminalStatus.ACTION_LIMIT
    assert ctl.terminal_reason


def test_budget_never_negative():
    _, ctl = make(max_actions=1)
    ctl.handle("read_board", {})
    ctl.check_terminal()
    ctl.handle("read_board", {})
    assert ctl.budget_remaining == 0


# ---------------------------------------------------------------- rejection streak

def test_rejection_limit():
    session, ctl = make()
    for _ in range(4):
        place(ctl, 1, 1, 5)
        assert ctl.check_terminal() is None
    place(ctl, 1, 1, 5)
    assert ctl.consecutive_rejections == 5
    assert ctl.check_terminal() is TerminalStatus.REJECTION_LIMIT
    assert session.board.grid() == to_grid(EASY)


def test_acceptance_resets_streak():
    _, ctl = make()
    for _ in range(4):
        ctl.handle("fly", {})
    assert ctl.consecutive_rejections == 4
    ctl.handle("read_board", {})
    assert ctl.consecutive_rejections == 0
    assert ctl.check_terminal() is None


# ---------------------------------------------------------------- terminal ordering

def test_solved_on_last_budgeted_action_is_solved():
    _, ctl = make(max_actions=len(SOLVE_STEPS) + 1)
    assert solve(ctl).accepted
    assert ctl.budget_remaining == 0
    assert ctl.check_terminal() is TerminalStatus.SOLVED


def test_no_action():
    _, ctl = make()
    ctl.record_no_action()
    assert ctl.check_terminal() is TerminalStatus.NO_ACTION
    assert ctl.actions_used == 0


def test_model_error():
    _, ctl = make()
    ctl.record_model_error(RuntimeError("gateway down"))
    assert ctl.check_terminal() is TerminalStatus.MODEL_ERROR
    assert ctl.actions_used == 0


def test_rejection_limit_precedes_no_action():
    _, ctl = make()
    for _ in range(5):
        ctl.handle("fly", {})
    ctl.record_no_action()
    assert ctl.check_terminal() is TerminalStatus.REJECTION_LIMIT


def test_no_action_precedes_model_error():
    _, ctl = make()
    ctl.record_no_action()
    ctl.record_model_error(RuntimeError("x"))
    assert ctl.check_terminal() is TerminalStatus.NO_ACTION


def test_terminal_status_is_final():
    _, ctl = make()
    ctl.record_no_action()
    assert ctl.check_terminal() is TerminalStatus.NO_ACTION
    ctl.record_model_error(RuntimeError("x"))
    assert ctl.check_terminal() is TerminalStatus.NO_ACTION
    assert ctl.terminal_status is TerminalStatus.NO_ACTION


def test_not_terminal_initially():
    _, ctl = make()
    assert ctl.check_terminal() is None
    assert ctl.terminal_status is None


# ---------------------------------------------------------------- trace

def test_trace_entries():
    _, ctl = make()
    place(ctl, 1, 3, 4)                                       # accepted, depth 1
    place(ctl, 1, 1, 5)                                       # P4
    ctl.handle("read_row", '{"row": 1}')                      # accepted, raw str args
    ctl.reject_extra_call("undo", {})                         # P10
    t = ctl.trace
    assert all(isinstance(e, TraceEntry) for e in t)
    assert [e.step for e in t] == [1, 2, 3, 4]
    assert [e.tool for e in t] == ["place_number", "place_number", "read_row", "undo"]
    assert [e.accepted for e in t] == [True, False, True, False]
    assert [e.policy for e in t] == [None, "P4", None, "P10"]
    assert t[0].args == {"row": 1, "col": 3, "digit": 4}
    assert t[2].args == '{"row": 1}'
    assert [e.budget_remaining for e in t] == [499, 498, 497, 496]
    assert [e.board_depth for e in t] == [1, 1, 1, 1]
    assert t[1].reason == "GIVEN_CELL" and t[1].message


def test_trace_is_read_only_tuple():
    _, ctl = make()
    ctl.handle("read_board", {})
    assert isinstance(ctl.trace, tuple)
