"""Typed tool schemas and tool executors.

Implements specs/tools.md (architecture §4.5). These are the only actions the
model may request. ``execute`` runs a request that the controller has already
approved; it is the only code that calls mutating methods on ``Board`` and
``SudokuKB`` (architecture §5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Callable

from pydantic import BaseModel, ConfigDict, Field

from sudoku_agent.session import Session
from sudoku_agent.validation import ValidationResult, validate_solution

MAX_REPORTED_REASONS = 10   # tools §4.3: keeps submit observations short

# ---------------------------------------------------------------- §2 argument schemas

Index = Annotated[int, Field(strict=True, ge=1, le=9)]
Formula = Annotated[str, Field(strict=True, min_length=1)]


class _Args(BaseModel):
    """Base schema: unknown fields are errors (tools §2)."""

    model_config = ConfigDict(extra="forbid")


class NoArgs(_Args):
    """Arguments of a tool that takes none."""


class RowArgs(_Args):
    row: Index


class ColArgs(_Args):
    col: Index


class BoxArgs(_Args):
    box: Index


class CellArgs(_Args):
    row: Index
    col: Index


class PlaceArgs(_Args):
    row: Index
    col: Index
    digit: Index


class FormulaArgs(_Args):
    formula: Formula


TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "read_board": NoArgs,
    "read_cell": CellArgs,
    "read_row": RowArgs,
    "read_col": ColArgs,
    "read_box": BoxArgs,
    "get_candidates": CellArgs,
    "place_number": PlaceArgs,
    "undo": NoArgs,
    "kb_tell": FormulaArgs,
    "kb_ask": FormulaArgs,
    "kb_infer_cell": CellArgs,
    "kb_clear": NoArgs,
    "submit": NoArgs,
}

_DESCRIPTIONS: dict[str, str] = {
    "read_board": "Return the whole 9x9 board as text with '.' for empty cells; costs 1 action.",
    "read_cell": "Return one cell's digit (0 if empty), whether it is a given, and its candidates; costs 1 action.",
    "read_row": "Return the 9 cells of one row as a string ('.' = empty); costs 1 action.",
    "read_col": "Return the 9 cells of one column as a string ('.' = empty); costs 1 action.",
    "read_box": "Return the 9 cells of one box (1-9, row-major) as a string ('.' = empty); costs 1 action.",
    "get_candidates": "Return the digits that do not conflict with the cell's row, column and box; costs 1 action.",
    "place_number": "Place a digit in an empty cell and return newly forced cells, dead cells and KB consistency; costs 1 action.",
    "undo": "Remove the most recent placement and the KB facts told since it; costs 1 action.",
    "kb_tell": "Add a propositional fact or rule (variables v{row}{col}{digit}) to the knowledge base; costs 1 action.",
    "kb_ask": "Ask whether a formula is entailed, contradicted or unresolved by the knowledge base; costs 1 action.",
    "kb_infer_cell": "Prove which candidates of one cell are ruled out and, if decided, its digit; costs 1 action.",
    "kb_clear": "Remove all facts you told the knowledge base (the Sudoku rules stay); costs 1 action.",
    "submit": "Submit the board for independent validation; accepted only if it is a correct solution; costs 1 action.",
}


def tool_definitions() -> list[dict]:
    """The 13 tools in the OpenAI function format accepted by ``bind_tools`` (tools §2)."""
    definitions = []
    for name, schema in TOOL_SCHEMAS.items():
        parameters = schema.model_json_schema()
        parameters.pop("title", None)
        definitions.append({
            "type": "function",
            "function": {"name": name, "description": _DESCRIPTIONS[name], "parameters": parameters},
        })
    return definitions


# ---------------------------------------------------------------- §3 execution interface

@dataclass(frozen=True)
class ToolOutcome:
    """Result of executing one tool (tools §3); the controller adds the budget."""

    accepted: bool
    reason: str | None
    message: str
    data: dict


def execute(session: Session, tool_name: str, args: BaseModel) -> ToolOutcome:
    """Run an approved tool call against ``session`` (tools §3).

    Raises ``KeyError`` for an unknown tool name.
    """
    executor = _EXECUTORS[tool_name]
    return executor(session, args)


def invalid_solution_data(result: ValidationResult) -> dict:
    """The ``data`` of a rejected submit: the first reasons and their total (tools §4.3)."""
    return {"reasons": list(result.reasons[:MAX_REPORTED_REASONS]), "total": len(result.reasons)}


def _cells_text(digits: list[int]) -> str:
    """A row, column or box as 9 characters, '.' for empty (tools §4)."""
    return "".join(str(d) if d else "." for d in digits)


def _rejected(reason: str, message: str) -> ToolOutcome:
    return ToolOutcome(False, reason, message, {"reason": reason})


# ---------------------------------------------------------------- §4 read tools

def _read_board(session: Session, args: NoArgs) -> ToolOutcome:
    board = session.board
    empty = len(board.empty_cells())
    return ToolOutcome(True, None, f"Board read; {empty} empty cells.",
                       {"board": board.render(), "empty": empty})


def _read_cell(session: Session, args: CellArgs) -> ToolOutcome:
    board = session.board
    r, c = args.row, args.col
    data = {"row": r, "col": c, "digit": board.cell(r, c), "given": board.is_given(r, c),
            "candidates": board.candidates(r, c)}
    return ToolOutcome(True, None, f"Read r{r}c{c}.", data)


def _read_row(session: Session, args: RowArgs) -> ToolOutcome:
    cells = _cells_text(session.board.row(args.row))
    return ToolOutcome(True, None, f"Row {args.row}: {cells}", {"row": args.row, "cells": cells})


def _read_col(session: Session, args: ColArgs) -> ToolOutcome:
    cells = _cells_text(session.board.col(args.col))
    return ToolOutcome(True, None, f"Column {args.col}: {cells}", {"col": args.col, "cells": cells})


def _read_box(session: Session, args: BoxArgs) -> ToolOutcome:
    cells = _cells_text(session.board.box(args.box))
    return ToolOutcome(True, None, f"Box {args.box}: {cells}", {"box": args.box, "cells": cells})


def _get_candidates(session: Session, args: CellArgs) -> ToolOutcome:
    r, c = args.row, args.col
    candidates = session.board.candidates(r, c)
    return ToolOutcome(True, None, f"Candidates for r{r}c{c}: {candidates}",
                       {"row": r, "col": c, "candidates": candidates})


# ---------------------------------------------------------------- §4.1 place_number

_CONTRADICTION_HINT = "This placement leads to a contradiction; undo it."


def _place_number(session: Session, args: PlaceArgs) -> ToolOutcome:
    board, kb = session.board, session.kb
    result = board.place(args.row, args.col, args.digit)
    if not result.accepted:
        return _rejected(result.reason, result.message)

    kb.rebuild(board)
    consistent = kb.is_consistent()
    data = {
        "placed": [args.row, args.col, args.digit],
        "forced": [list(cell) for cell in result.forced_cells],
        "dead": [list(cell) for cell in result.dead_cells],
        "kb_consistent": consistent,
        "empty": len(board.empty_cells()),
    }
    parts = [result.message]
    if result.forced_cells:
        parts.append("Forced: " + ", ".join(f"r{r}c{c}={d}" for r, c, d in result.forced_cells) + ".")
    if result.dead_cells:
        parts.append("Dead cells (no candidates): " + ", ".join(f"r{r}c{c}" for r, c in result.dead_cells) + ".")
    if result.dead_cells or not consistent:
        parts.append(_CONTRADICTION_HINT)
    return ToolOutcome(True, None, " ".join(parts), data)


# ---------------------------------------------------------------- §4.2 undo

def _undo(session: Session, args: NoArgs) -> ToolOutcome:
    board, kb = session.board, session.kb
    result = board.undo()
    if not result.accepted:
        return _rejected(result.reason, result.message)

    kb.rebuild(board)
    rolled_back = kb.rollback_to(board.depth)
    data = {
        "removed": list(result.removed),
        "facts_rolled_back": rolled_back,
        "kb_consistent": kb.is_consistent(),
        "empty": len(board.empty_cells()),
    }
    return ToolOutcome(True, None, f"{result.message} {rolled_back} KB facts rolled back.", data)


# ---------------------------------------------------------------- KB tools

def _kb_tell(session: Session, args: FormulaArgs) -> ToolOutcome:
    result = session.kb.tell(args.formula)
    if not result.accepted:
        return _rejected(result.reason, result.message)
    return ToolOutcome(True, None, result.message, {"facts": len(session.kb.agent_facts())})


def _kb_ask(session: Session, args: FormulaArgs) -> ToolOutcome:
    result = session.kb.ask(args.formula)
    if not result.accepted:
        return _rejected(result.reason, result.message)
    return ToolOutcome(True, None, result.message, {"answer": result.answer.value})


def _kb_infer_cell(session: Session, args: CellArgs) -> ToolOutcome:
    result = session.kb.infer_cell(args.row, args.col)
    if not result.accepted:
        return _rejected(result.reason, result.message)
    data = {"row": args.row, "col": args.col, "digit": result.digit,
            "possible": list(result.possible), "ruled_out": list(result.ruled_out)}
    return ToolOutcome(True, None, result.message, data)


def _kb_clear(session: Session, args: NoArgs) -> ToolOutcome:
    removed = session.kb.clear_agent_facts()
    return ToolOutcome(True, None, f"Cleared {removed} KB facts; the Sudoku rules remain.",
                       {"removed": removed})


# ---------------------------------------------------------------- §4.3 submit

def _submit(session: Session, args: NoArgs) -> ToolOutcome:
    result = validate_solution(session.original_puzzle, session.board.grid())
    if not result.valid:
        return ToolOutcome(False, "INVALID_SOLUTION",
                           f"Not a valid solution ({len(result.reasons)} problems).",
                           invalid_solution_data(result))
    return ToolOutcome(True, None, "The board is a valid solution.", {"result": "SOLVED"})


_EXECUTORS: dict[str, Callable[[Session, BaseModel], ToolOutcome]] = {
    "read_board": _read_board,
    "read_cell": _read_cell,
    "read_row": _read_row,
    "read_col": _read_col,
    "read_box": _read_box,
    "get_candidates": _get_candidates,
    "place_number": _place_number,
    "undo": _undo,
    "kb_tell": _kb_tell,
    "kb_ask": _kb_ask,
    "kb_infer_cell": _kb_infer_cell,
    "kb_clear": _kb_clear,
    "submit": _submit,
}
