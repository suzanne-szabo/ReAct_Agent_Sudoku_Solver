"""White-box tests, written AFTER the implementation by reading the coverage report.

They target branches the spec-derived black-box tests did not reach (CLI, error
paths, rare branches). They supplement, and never replace, the black-box suite.
Coverage before these tests: 94% branch coverage (cli.py untested).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from sudoku_agent import cli
from sudoku_agent.agent import recent_turns, run as agent_run
from sudoku_agent.board import Board
from sudoku_agent.controller import Approval, Config, Controller, TerminalStatus
from sudoku_agent.logic import SudokuKB
from sudoku_agent.session import Session
from sudoku_agent.tools import TOOL_SCHEMAS
from conftest import EASY, EASY_SOLUTION, solution_placements
from fakes import ScriptedModel, call, turn

pytestmark = pytest.mark.whitebox
REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- cli.py (0% before)

def _scripted_run(script):
    """Replacement for cli.run that injects a scripted model (no network)."""
    seen = {}

    def fake_run(puzzle, config, on_step=None):
        seen["config"] = config
        return agent_run(puzzle, config, model=ScriptedModel(list(script)), on_step=on_step)
    return fake_run, seen


def _solving_script():
    return [turn(call("place_number", row=r, col=c, digit=d))
            for r, c, d in solution_placements(EASY, EASY_SOLUTION)] + [turn(call("submit"))]


def test_cli_solved_run_prints_steps_and_writes_trace(monkeypatch, tmp_path, capsys):
    fake, seen = _scripted_run(_solving_script())
    monkeypatch.setattr(cli, "run", fake)
    trace = tmp_path / "trace.jsonl"
    code = cli.main([str(REPO / "puzzles" / "easy.txt"), "--model", "M", "--max-actions", "60",
                     "--history", "3", "--trace-out", str(trace)])
    out = capsys.readouterr().out
    assert code == 0
    assert "[  1] place_number" in out and "Status: SOLVED" in out and "Actions used: 52" in out
    assert "1  534 678 912" in out                      # final board rendered
    assert (seen["config"].model_name, seen["config"].max_actions, seen["config"].history_window) == ("M", 60, 3)
    lines = trace.read_text().splitlines()
    assert len(lines) == 52 and json.loads(lines[-1])["tool"] == "submit"


def test_cli_quiet_and_unsolved_exit_code(monkeypatch, capsys):
    fake, _ = _scripted_run([turn(call("place_number", row=1, col=1, digit=5))] * 5)
    monkeypatch.setattr(cli, "run", fake)
    code = cli.main([str(REPO / "puzzles" / "easy.txt"), "--quiet"])
    out = capsys.readouterr().out
    assert code == 1
    assert "[  1]" not in out and "Status: REJECTION_LIMIT" in out


def test_cli_model_defaults_to_environment(monkeypatch):
    fake, seen = _scripted_run([])
    monkeypatch.setattr(cli, "run", fake)
    monkeypatch.setenv("SUDOKU_MODEL", "Some-Model")
    cli.main([str(REPO / "puzzles" / "easy.txt"), "--quiet"])
    assert seen["config"].model_name == "Some-Model"


def test_cli_missing_file(capsys, tmp_path):
    assert cli.main([str(tmp_path / "nope.txt")]) == 1
    assert "cannot load puzzle" in capsys.readouterr().err


def test_cli_conflicting_givens(capsys, tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text("55" + "0" * 79 + "\n")              # well-formed, but two 5s in row 1
    assert cli.main([str(bad)]) == 1
    assert "invalid puzzle" in capsys.readouterr().err


def test_format_step_rejected_and_string_args():
    s = Session.new(EASY, Config())
    ctl = Controller(s, s.config)
    ctl.handle("place_number", '{"row": 1, "col": 1, "digit": 5}')
    line = cli.format_step(ctl.trace[0])
    assert line.startswith("[  1] place_number {\"row\": 1") and "REJECTED P4 GIVEN_CELL" in line


def test_module_entry_point_help():
    out = subprocess.run([sys.executable, "-m", "sudoku_agent", "--help"], cwd=REPO,
                         capture_output=True, text=True)
    assert out.returncode == 0 and "PUZZLE_FILE" in out.stdout


# ---------------------------------------------------------------- agent.py

def test_run_without_api_key_is_model_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOLEM_API_KEY", "x")
    monkeypatch.delenv("GOLEM_API_KEY")
    result = agent_run(EASY, Config())                  # model=None -> make_model fails
    assert result.status is TerminalStatus.MODEL_ERROR
    assert "GOLEM_API_KEY" in result.reason


def test_recent_turns_drops_leading_orphan_and_zero_window():
    ai = AIMessage(content="", tool_calls=[{"name": "read_board", "args": {}, "id": "a", "type": "tool_call"}])
    orphan = ToolMessage(content="{}", tool_call_id="zzz")
    answer = ToolMessage(content="{}", tool_call_id="a")
    assert recent_turns([orphan, ai, answer], 5) == [ai, answer]
    assert recent_turns([ai, answer], 0) == []


def test_reply_reusing_a_message_id_is_still_appended():
    # Found by white-box testing: the same AIMessage object (same id) returned twice used to
    # replace the earlier message in graph state and crash the controller node.
    same = turn(call("read_board"))
    result = agent_run(EASY, Config(), model=ScriptedModel([same, same, same]))
    assert [e.tool for e in result.trace] == ["read_board"] * 3
    assert result.status is TerminalStatus.NO_ACTION


# ---------------------------------------------------------------- controller.py

def test_execute_foreign_approval_traces_model_dump():
    s = Session.new(EASY, Config())
    ctl = Controller(s, s.config)
    obs = ctl.execute(Approval("read_cell", TOOL_SCHEMAS["read_cell"](row=1, col=3)))
    assert obs.accepted
    assert ctl.trace[0].args == {"row": 1, "col": 3}


def test_conflict_message_names_box_only_conflict():
    s = Session.new(EASY, Config())
    obs = Controller(s, s.config).handle("place_number", {"row": 2, "col": 2, "digit": 8})
    assert obs.policy == "P6" and obs.message == "8 already in box 1"


# ---------------------------------------------------------------- logic.py

def test_infer_cell_undecided_on_board_with_two_solutions():
    # Blank a "deadly rectangle" of the easy solution: r4c6/r4c9/r5c6/r5c9 hold 1 and 3,
    # and swapping them gives a second valid solution, so neither digit can be proven.
    cells = [(4, 6), (4, 9), (5, 6), (5, 9)]
    s = list(EASY_SOLUTION)
    for r, c in cells:
        s[(r - 1) * 9 + (c - 1)] = "0"
    kb = SudokuKB(Board.from_string("".join(s)))
    res = kb.infer_cell(4, 6)
    assert res.accepted and res.digit is None
    assert tuple(res.possible) == (1, 3) and tuple(res.ruled_out) == ()
    assert "not decided" in res.message


# ---------------------------------------------------------------- validation.py, puzzles.py, llm.py

@pytest.mark.parametrize("grid", [None, 5, [1, 2, 3, 4, 5, 6, 7, 8, 9]])
def test_validation_non_sequence_grid_is_bad_shape(grid):
    from sudoku_agent.validation import validate_solution
    assert validate_solution(EASY, grid).reasons == ("BAD_SHAPE",)


def test_puzzle_file_with_extra_blank_lines(tmp_path):
    from sudoku_agent.puzzles import load
    f = tmp_path / "p.txt"
    f.write_text("\n\n# comment\n" + EASY + "\n\n\n" + EASY_SOLUTION + "\n\n")
    p = load(f)
    assert (p.puzzle, p.solution) == (EASY, EASY_SOLUTION)


def test_default_model_name(monkeypatch, tmp_path):
    from sudoku_agent.llm import default_model_name
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUDOKU_MODEL", raising=False)
    assert default_model_name() == Config().model_name
    monkeypatch.setenv("SUDOKU_MODEL", "Other")
    assert default_model_name() == "Other"
