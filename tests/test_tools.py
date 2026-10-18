"""Black-box tests for sudoku_agent.tools, derived from specs/tools.md."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from sudoku_agent.tools import TOOL_SCHEMAS, ToolOutcome, execute, tool_definitions
from conftest import (
    CASCADE_FORCED, CASCADE_PLACEMENT, EASY, EASY_EMPTY_COUNT, EASY_SOLUTION,
    WRONG_LEGAL_NO_DEAD, WRONG_WITH_DEAD, WRONG_WITH_DEAD_CELL, solution_placements, to_grid,
)

TOOL_NAMES = {
    "read_board", "read_cell", "read_row", "read_col", "read_box", "get_candidates",
    "place_number", "undo", "kb_tell", "kb_ask", "kb_infer_cell", "kb_clear", "submit",
}


def run(session, name, **args):
    out = execute(session, name, TOOL_SCHEMAS[name](**args))
    assert isinstance(out, ToolOutcome)
    json.dumps(out.data)            # every outcome's data must be JSON-serializable
    return out


def jd(outcome):
    """data after a JSON round trip (tuples become lists)."""
    return json.loads(json.dumps(outcome.data))


def state(session):
    return session.board.grid(), session.board.depth, session.kb.agent_facts()


# ---------------------------------------------------------------- §2 schemas

class TestSchemas:
    def test_exactly_thirteen_tools(self):
        assert set(TOOL_SCHEMAS) == TOOL_NAMES

    def test_tool_definitions_names(self):
        from langchain_core.utils.function_calling import convert_to_openai_tool
        defs = tool_definitions()
        names = [convert_to_openai_tool(d)["function"]["name"] for d in defs]
        assert sorted(names) == sorted(TOOL_NAMES)

    def test_tool_definitions_have_descriptions(self):
        from langchain_core.utils.function_calling import convert_to_openai_tool
        for d in tool_definitions():
            assert convert_to_openai_tool(d)["function"].get("description")

    @pytest.mark.parametrize("name,args", [
        ("read_board", {}), ("read_cell", {"row": 1, "col": 9}), ("read_row", {"row": 9}),
        ("read_col", {"col": 1}), ("read_box", {"box": 5}), ("get_candidates", {"row": 2, "col": 2}),
        ("place_number", {"row": 1, "col": 3, "digit": 4}), ("undo", {}),
        ("kb_tell", {"formula": "p"}), ("kb_ask", {"formula": "v134"}),
        ("kb_infer_cell", {"row": 1, "col": 3}), ("kb_clear", {}), ("submit", {}),
    ])
    def test_valid_arguments(self, name, args):
        TOOL_SCHEMAS[name].model_validate(args)

    @pytest.mark.parametrize("args", [
        {"row": 1, "col": 3},                              # missing digit
        {"row": 1, "col": 3, "digit": 4, "extra": 1},      # extra field
        {"row": 0, "col": 3, "digit": 4},
        {"row": 1, "col": 10, "digit": 4},
        {"row": 1, "col": 3, "digit": 0},
        {"row": 1, "col": 3, "digit": 10},
        {"row": "1", "col": 3, "digit": 4},                # numeric string
        {"row": 1.0, "col": 3, "digit": 4},                # float
        {"row": 1, "col": 3, "digit": True},               # bool
    ])
    def test_place_number_schema_errors(self, args):
        with pytest.raises(ValidationError):
            TOOL_SCHEMAS["place_number"].model_validate(args)

    @pytest.mark.parametrize("name,args", [
        ("read_box", {"box": 0}), ("read_row", {}), ("read_board", {"x": 1}),
        ("kb_tell", {"formula": ""}), ("kb_ask", {}), ("kb_tell", {"formula": 5}),
        ("undo", {"steps": 2}), ("kb_infer_cell", {"row": 1}),
    ])
    def test_other_schema_errors(self, name, args):
        with pytest.raises(ValidationError):
            TOOL_SCHEMAS[name].model_validate(args)


# ---------------------------------------------------------------- §4 read tools

class TestReadTools:
    def test_read_board(self, easy_session):
        before = state(easy_session)
        out = run(easy_session, "read_board")
        assert out.accepted is True
        assert out.data["board"] == easy_session.board.render()
        assert out.data["empty"] == EASY_EMPTY_COUNT
        assert state(easy_session) == before

    def test_read_cell_empty(self, easy_session):
        out = run(easy_session, "read_cell", row=1, col=3)
        assert jd(out) == {"row": 1, "col": 3, "digit": 0, "given": False, "candidates": [1, 2, 4]}

    def test_read_cell_given(self, easy_session):
        out = run(easy_session, "read_cell", row=1, col=1)
        assert jd(out) == {"row": 1, "col": 1, "digit": 5, "given": True, "candidates": []}

    def test_read_row_col_box(self, easy_session):
        before = state(easy_session)
        assert jd(run(easy_session, "read_row", row=1)) == {"row": 1, "cells": "53..7...."}
        assert jd(run(easy_session, "read_col", col=1)) == {"col": 1, "cells": "56.847..."}
        assert jd(run(easy_session, "read_box", box=1)) == {"box": 1, "cells": "53.6...98"}
        assert jd(run(easy_session, "read_box", box=9)) == {"box": 9, "cells": "28...5.79"}
        assert state(easy_session) == before

    def test_get_candidates(self, easy_session):
        assert jd(run(easy_session, "get_candidates", row=1, col=3)) == {"row": 1, "col": 3, "candidates": [1, 2, 4]}
        assert jd(run(easy_session, "get_candidates", row=1, col=1))["candidates"] == []


# ---------------------------------------------------------------- §4.1 place_number

class TestPlaceNumber:
    def test_accepted_with_cascade(self, easy_session):
        r, c, d = CASCADE_PLACEMENT
        out = run(easy_session, "place_number", row=r, col=c, digit=d)
        assert out.accepted is True and out.reason is None
        data = jd(out)
        assert data["placed"] == [r, c, d]
        assert data["forced"] == [list(x) for x in CASCADE_FORCED]
        assert data["dead"] == []
        assert data["kb_consistent"] is True
        assert data["empty"] == EASY_EMPTY_COUNT - 1
        assert easy_session.board.cell(r, c) == d

    def test_message_mentions_forced_cells(self, easy_session):
        out = run(easy_session, "place_number", row=3, col=6, digit=2)
        assert "r1c4=6" in out.message

    @pytest.mark.parametrize("args,reason", [
        ({"row": 1, "col": 1, "digit": 5}, "GIVEN_CELL"),
        ({"row": 1, "col": 3, "digit": 5}, "CONFLICT"),
    ])
    def test_rejections_change_nothing(self, easy_session, args, reason):
        before = state(easy_session)
        out = run(easy_session, "place_number", **args)
        assert (out.accepted, out.reason) == (False, reason)
        assert out.data == {"reason": reason}
        assert state(easy_session) == before

    def test_cell_filled_rejection(self, easy_session):
        run(easy_session, "place_number", row=1, col=3, digit=4)
        before = state(easy_session)
        out = run(easy_session, "place_number", row=1, col=3, digit=2)
        assert (out.accepted, out.reason, out.data) == (False, "CELL_FILLED", {"reason": "CELL_FILLED"})
        assert state(easy_session) == before

    def test_wrong_legal_placement_reports_inconsistency(self, easy_session):
        r, c, d = WRONG_LEGAL_NO_DEAD
        out = run(easy_session, "place_number", row=r, col=c, digit=d)
        assert out.accepted is True
        assert jd(out)["kb_consistent"] is False
        assert jd(out)["dead"] == []
        assert "undo" in out.message.lower()

    def test_dead_cells_reported(self, easy_session):
        r, c, d = WRONG_WITH_DEAD
        out = run(easy_session, "place_number", row=r, col=c, digit=d)
        assert jd(out)["dead"] == [list(WRONG_WITH_DEAD_CELL)]
        assert "undo" in out.message.lower()

    def test_kb_rebuilt_after_placement(self, easy_session):
        run(easy_session, "place_number", row=1, col=3, digit=4)
        assert jd(run(easy_session, "kb_ask", formula="v134"))["answer"] == "entailed"


# ---------------------------------------------------------------- §4.2 undo

class TestUndoTool:
    def test_empty_stack(self, easy_session):
        before = state(easy_session)
        out = run(easy_session, "undo")
        assert (out.accepted, out.reason) == (False, "EMPTY_STACK")
        assert state(easy_session) == before

    def test_undo_restores_board_and_rolls_back_facts(self, easy_session):
        run(easy_session, "kb_tell", formula="early")                 # depth 0
        run(easy_session, "place_number", row=1, col=3, digit=4)       # depth 1
        run(easy_session, "kb_tell", formula="late")                  # depth 1
        out = run(easy_session, "undo")
        assert out.accepted is True
        data = jd(out)
        assert data["removed"] == [1, 3, 4]
        assert data["facts_rolled_back"] == 1
        assert data["kb_consistent"] is True
        assert data["empty"] == EASY_EMPTY_COUNT
        assert easy_session.board.grid() == to_grid(EASY)
        assert easy_session.kb.agent_facts() == ((0, "early"),)

    def test_undo_of_wrong_placement_restores_consistency(self, easy_session):
        r, c, d = WRONG_LEGAL_NO_DEAD
        run(easy_session, "place_number", row=r, col=c, digit=d)
        assert jd(run(easy_session, "undo"))["kb_consistent"] is True
        assert jd(run(easy_session, "kb_ask", formula="v134"))["answer"] == "entailed"


# ---------------------------------------------------------------- KB tools

class TestKbTools:
    def test_tell_ask_clear(self, easy_session):
        assert jd(run(easy_session, "kb_ask", formula="p"))["answer"] == "unresolved"
        out = run(easy_session, "kb_tell", formula="p")
        assert out.accepted and jd(out) == {"facts": 1}
        assert jd(run(easy_session, "kb_ask", formula="p"))["answer"] == "entailed"
        assert jd(run(easy_session, "kb_ask", formula="~p"))["answer"] == "contradicted"
        clear = run(easy_session, "kb_clear")
        assert clear.accepted and jd(clear) == {"removed": 1}
        assert jd(run(easy_session, "kb_ask", formula="p"))["answer"] == "unresolved"
        assert jd(run(easy_session, "kb_ask", formula="v134"))["answer"] == "entailed"

    @pytest.mark.parametrize("formula,reason", [
        ("p &", "PARSE_ERROR"), ("v105", "INVALID_SYMBOL"), ("p" + " | p" * 200, "TOO_LONG"), ("v131", "INCONSISTENT"),
    ])
    def test_tell_rejections_pass_through(self, easy_session, formula, reason):
        before = state(easy_session)
        out = run(easy_session, "kb_tell", formula=formula)
        assert (out.accepted, out.reason) == (False, reason)
        assert state(easy_session) == before

    @pytest.mark.parametrize("formula,reason", [("p &", "PARSE_ERROR"), ("v000", "INVALID_SYMBOL")])
    def test_ask_rejections_pass_through(self, easy_session, formula, reason):
        out = run(easy_session, "kb_ask", formula=formula)
        assert (out.accepted, out.reason) == (False, reason)

    def test_kb_inconsistent_passes_through(self, easy_session):
        r, c, d = WRONG_LEGAL_NO_DEAD
        run(easy_session, "place_number", row=r, col=c, digit=d)
        for name, args in [("kb_tell", {"formula": "p"}), ("kb_ask", {"formula": "p"}),
                           ("kb_infer_cell", {"row": 2, "col": 2})]:
            out = run(easy_session, name, **args)
            assert (out.accepted, out.reason) == (False, "KB_INCONSISTENT")

    def test_infer_cell(self, easy_session):
        before = state(easy_session)
        out = run(easy_session, "kb_infer_cell", row=1, col=3)
        assert out.accepted is True
        assert jd(out) == {"row": 1, "col": 3, "digit": 4, "possible": [4], "ruled_out": [1, 2]}
        assert state(easy_session) == before


# ---------------------------------------------------------------- §4.3 submit

class TestSubmit:
    def test_solved_board_accepted(self, easy_session):
        for r, c, d in solution_placements(EASY, EASY_SOLUTION):
            assert run(easy_session, "place_number", row=r, col=c, digit=d).accepted
        out = run(easy_session, "submit")
        assert out.accepted is True
        assert jd(out) == {"result": "SOLVED"}

    def test_incomplete_board_rejected_with_capped_reasons(self, easy_session):
        before = state(easy_session)
        out = run(easy_session, "submit")
        assert (out.accepted, out.reason) == (False, "INVALID_SOLUTION")
        data = jd(out)
        assert len(data["reasons"]) == 10
        assert all(r.startswith("EMPTY") for r in data["reasons"])
        assert data["reasons"][0] == "EMPTY r1c3"
        assert data["total"] == 51 + 27
        assert state(easy_session) == before


def test_unknown_tool_raises_key_error(easy_session):
    with pytest.raises(KeyError):
        execute(easy_session, "fly", TOOL_SCHEMAS["read_board"]())
