"""Composition root holding one puzzle run's state.

Implements architecture §4.7. The controller state (budget, trace, terminal
status) lives in ``Controller``, which is constructed with the session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sudoku_agent.board import Board
from sudoku_agent.logic import SudokuKB

if TYPE_CHECKING:   # only for the annotation; avoids an import cycle with controller
    from sudoku_agent.controller import Config


@dataclass(frozen=True)
class Session:
    """One run's board, knowledge base, original puzzle and configuration.

    The attributes are read-only; the objects they refer to are changed only
    by ``tools`` (architecture §5).
    """

    board: Board
    kb: SudokuKB
    original_puzzle: str
    config: Config

    @classmethod
    def new(cls, puzzle: str, config: Config) -> Session:
        """Create a session for ``puzzle``; a malformed puzzle raises ``ValueError``."""
        board = Board.from_string(puzzle)
        return cls(board=board, kb=SudokuKB(board), original_puzzle=puzzle, config=config)
