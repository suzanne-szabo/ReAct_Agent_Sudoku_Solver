"""Shared fixtures and verified puzzle data for the black-box test suite.

Puzzle strings are copied from puzzles/*.txt, whose unique solutions were
verified by exhaustive search (see puzzles/README.md). Expected values used by
individual tests (cascades, dead cells) were computed by an independent script
during test design, not by the implementation under test.
"""

from __future__ import annotations

import pytest

EASY = "530070000600195000098000060800060003400803001700020006060000280000419005000080079"
EASY_SOLUTION = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"
HARD = "400000805030000000000700000020000060000080400000010000000603070500200000104000000"
HARD_SOLUTION = "417369825632158947958724316825437169791586432346912758289643571573291684164875293"
EXPERT = "800000000003600000070090200050007000000045700000100030001000068008500010090000400"
EXPERT_SOLUTION = "812753649943682175675491283154237896369845721287169534521974368438526917796318452"

EASY_EMPTY_COUNT = 51


def to_grid(s: str) -> tuple[tuple[int, ...], ...]:
    """81-char string ('0' or '.' = empty) -> 9x9 tuple of ints."""
    s = s.replace(".", "0")
    return tuple(tuple(int(s[r * 9 + c]) for c in range(9)) for r in range(9))


def sol_digit(solution: str, r: int, c: int) -> int:
    """Solution digit at 1-based (r, c)."""
    return int(solution[(r - 1) * 9 + (c - 1)])


def empty_cells_of(puzzle: str) -> list[tuple[int, int]]:
    """1-based empty cells in row-major order."""
    return [(i // 9 + 1, i % 9 + 1) for i, ch in enumerate(puzzle) if ch in "0."]


def solution_placements(puzzle: str, solution: str) -> list[tuple[int, int, int]]:
    """Every (row, col, digit) needed to complete puzzle into solution, row-major."""
    return [(r, c, sol_digit(solution, r, c)) for r, c in empty_cells_of(puzzle)]


# Wrong-but-legal placements on EASY (computed independently during test design):
WRONG_LEGAL_NO_DEAD = (1, 3, 1)      # r1c3 candidates are {1,2,4}; solution is 4; no peer dies
WRONG_WITH_DEAD = (1, 9, 4)          # solution is 2; leaves r7c9 with no candidates
WRONG_WITH_DEAD_CELL = (7, 9)
# A correct placement on EASY whose cascade forces four peers:
CASCADE_PLACEMENT = (3, 6, 2)
CASCADE_FORCED = [(1, 4, 6), (3, 1, 1), (3, 4, 3), (9, 6, 6)]


@pytest.fixture
def easy_board():
    from sudoku_agent.board import Board
    return Board.from_string(EASY)


@pytest.fixture
def config():
    from sudoku_agent.controller import Config
    return Config()


@pytest.fixture
def easy_session(config):
    from sudoku_agent.session import Session
    return Session.new(EASY, config)
