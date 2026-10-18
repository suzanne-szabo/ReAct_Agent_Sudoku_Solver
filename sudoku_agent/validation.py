"""Independent solution validator (pure function).

Implements specs/validation.md (architecture §4.2). It re-parses the original
puzzle itself and must not import ``board``, so a bug in the board's
bookkeeping can never make an incorrect board count as solved.
"""

from __future__ import annotations

from dataclasses import dataclass

_FULL_UNIT = set(range(1, 10))


@dataclass(frozen=True)
class ValidationResult:
    """Whether a grid solves the original puzzle, and why not (validation §2)."""

    valid: bool
    reasons: tuple[str, ...]


def _parse_givens(original_puzzle: str) -> list[list[int]]:
    """Parse the original puzzle into a 9x9 list of ints, 0 for empty (validation §2)."""
    if not isinstance(original_puzzle, str):
        raise TypeError("original_puzzle must be a str")
    text = "".join(original_puzzle.split())
    if len(text) != 81 or any(ch not in "0123456789." for ch in text):
        raise ValueError("original_puzzle must be 81 characters of 0-9 or '.'")
    text = text.replace(".", "0")
    return [[int(text[r * 9 + c]) for c in range(9)] for r in range(9)]


def _has_shape(grid) -> bool:
    """Whether ``grid`` is a sequence of 9 sequences of 9 entries."""
    try:
        return len(grid) == 9 and all(len(row) == 9 for row in grid)
    except TypeError:
        return False


def _is_value(entry) -> bool:
    """Whether an entry is an int (not bool) in 0-9."""
    return isinstance(entry, int) and not isinstance(entry, bool) and 0 <= entry <= 9


def _unit_is_complete(entries: list) -> bool:
    """Whether a unit holds exactly the digits 1-9, each once, all valid values."""
    return all(_is_value(e) for e in entries) and set(entries) == _FULL_UNIT


def validate_solution(original_puzzle: str, grid) -> ValidationResult:
    """Check ``grid`` against ``original_puzzle`` (validation §3).

    ``grid`` is never mutated. Every failure is reported, grouped by code in
    the order of validation §3.
    """
    givens = _parse_givens(original_puzzle)
    if not _has_shape(grid):
        return ValidationResult(False, ("BAD_SHAPE",))

    cells = [[grid[r][c] for c in range(9)] for r in range(9)]   # local read-only copy
    positions = [(r, c) for r in range(9) for c in range(9)]

    bad_value = [f"BAD_VALUE r{r + 1}c{c + 1}" for r, c in positions if not _is_value(cells[r][c])]
    empty = [
        f"EMPTY r{r + 1}c{c + 1}"
        for r, c in positions
        if _is_value(cells[r][c]) and cells[r][c] == 0
    ]
    given_changed = [
        f"GIVEN_CHANGED r{r + 1}c{c + 1}"
        for r, c in positions
        if givens[r][c] != 0 and not (_is_value(cells[r][c]) and cells[r][c] == givens[r][c])
    ]
    rows = [f"ROW_INVALID {r + 1}" for r in range(9) if not _unit_is_complete(cells[r])]
    cols = [
        f"COL_INVALID {c + 1}"
        for c in range(9)
        if not _unit_is_complete([cells[r][c] for r in range(9)])
    ]
    boxes = [
        f"BOX_INVALID {b + 1}"
        for b in range(9)
        if not _unit_is_complete([
            cells[3 * (b // 3) + i][3 * (b % 3) + j] for i in range(3) for j in range(3)
        ])
    ]

    reasons = tuple(bad_value + empty + given_changed + rows + cols + boxes)
    return ValidationResult(not reasons, reasons)
