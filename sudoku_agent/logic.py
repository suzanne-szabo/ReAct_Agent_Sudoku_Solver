"""Sudoku knowledge base (``SudokuKB``) wrapping the vendored ``proplogic`` package.

Implements specs/logic.md (architecture §4.4, §7). The KB is the conjunction of

- a **rule layer** generated from a board snapshot (logic §3), which the agent
  can never remove; and
- an **agent layer** of ``(depth, formula)`` entries told by the agent (logic §4).

All satisfiability checks go through ``proplogic.KnowledgeBase`` (unmodified,
architecture D1). This module only reads the board; it never mutates it.
"""

from __future__ import annotations

import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from itertools import combinations
from typing import Iterable, Iterator

from proplogic import Clause, KnowledgeBase, Literal, to_cnf

from sudoku_agent.board import DIGITS, Board, box_cells

MAX_FORMULA_LENGTH = 500   # logic §2: guards against exponential CNF growth

_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")   # proplogic's symbol/keyword token
_CELL_VARIABLE = re.compile(r"v(\d)(\d)(\d)")      # logic §2 reserved form

# Python frames used by proplogic's DPLL per assigned symbol, plus headroom
# for the caller's own stack (logic §6, "Recursion").
_FRAMES_PER_SYMBOL = 2
_RECURSION_HEADROOM = 1000


class Answer(Enum):
    """Three-valued answer to ``ask`` (logic §5, architecture D4)."""

    ENTAILED = "entailed"
    CONTRADICTED = "contradicted"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class TellResult:
    """Outcome of ``SudokuKB.tell`` (logic §5.3)."""

    accepted: bool
    reason: str | None
    message: str


@dataclass(frozen=True)
class AskResult:
    """Outcome of ``SudokuKB.ask`` (logic §5.4)."""

    accepted: bool
    answer: Answer | None
    reason: str | None
    message: str


@dataclass(frozen=True)
class InferResult:
    """Outcome of ``SudokuKB.infer_cell`` (logic §5.7)."""

    accepted: bool
    digit: int | None
    possible: tuple[int, ...]
    ruled_out: tuple[int, ...]
    reason: str | None
    message: str


@dataclass(frozen=True)
class _AgentEntry:
    """One agent-layer entry: the board depth, the formula text and its CNF."""

    depth: int
    formula: str
    clauses: tuple[Clause, ...]


class _FormulaError(Exception):
    """A formula failed the syntax checks of logic §2 (carries the reason code)."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def cell_variable(row: int, col: int, digit: int) -> str:
    """The propositional variable ``v{r}{c}{d}`` (architecture §2)."""
    return f"v{row}{col}{digit}"


def _var(row: int, col: int, digit: int, positive: bool = True) -> Literal:
    return Literal(cell_variable(row, col, digit), positive)


def _negation(formula: str) -> str:
    """The negation of ``formula`` in proplogic syntax."""
    return f"~({formula})"


def rule_clauses(board: Board) -> tuple[Clause, ...]:
    """The materialized rule layer for ``board`` (logic §3.1-§3.5), without duplicates.

    Only empty cells and their candidates are encoded (architecture D2). Filled
    cells (§3.6) are handled lazily by ``SudokuKB._materialize``.
    """
    clauses: dict[Clause, None] = {}   # insertion-ordered set

    def add(literals: Iterable[Literal]) -> None:
        clauses.setdefault(frozenset(literals), None)

    empty = board.empty_cells()
    candidates = {cell: board.candidates(*cell) for cell in empty}

    for (r, c), cands in candidates.items():
        add(_var(r, c, d) for d in DIGITS)                                   # §3.1
        for d in DIGITS:
            if d not in cands:
                add([_var(r, c, d, positive=False)])                         # §3.2
        for a, b in combinations(cands, 2):
            add([_var(r, c, a, positive=False), _var(r, c, b, positive=False)])  # §3.3

    units = [[(r, c) for c in DIGITS] for r in DIGITS]
    units += [[(r, c) for r in DIGITS] for c in DIGITS]
    units += [box_cells(b) for b in DIGITS]
    for unit in units:
        present = {board.cell(*cell) for cell in unit}
        open_cells = [cell for cell in unit if cell in candidates]
        for d in DIGITS:
            if d in present:
                continue
            add(_var(r, c, d) for r, c in open_cells)                       # §3.4
            holders = [cell for cell in open_cells if d in candidates[cell]]
            for (r1, c1), (r2, c2) in combinations(holders, 2):
                add([_var(r1, c1, d, positive=False), _var(r2, c2, d, positive=False)])  # §3.5
    return tuple(clauses)


def _check_formula(formula: str) -> tuple[tuple[Clause, ...], set[str]]:
    """Apply the syntax checks of logic §2 in order; return the CNF and symbols.

    Raises ``_FormulaError`` with ``TOO_LONG``, ``PARSE_ERROR`` or ``INVALID_SYMBOL``.
    """
    if len(formula) > MAX_FORMULA_LENGTH:
        raise _FormulaError(
            "TOO_LONG",
            f"Formula has {len(formula)} characters; the limit is {MAX_FORMULA_LENGTH}.",
        )
    try:
        clauses = to_cnf(formula)
    except ValueError as error:
        raise _FormulaError("PARSE_ERROR", f"Could not parse formula: {error}") from None
    # After a successful parse, every identifier-shaped run is a symbol or an
    # operator word, exactly as proplogic's tokenizer reads it.
    symbols = set(_SYMBOL.findall(formula))
    for symbol in sorted(symbols):
        match = _CELL_VARIABLE.fullmatch(symbol)
        if match and "0" in match.groups():
            raise _FormulaError(
                "INVALID_SYMBOL",
                f"{symbol} is not a valid cell variable: rows, columns and digits are 1-9.",
            )
    return clauses, symbols


def _check_depth(depth: object) -> int:
    """Validate a ``rollback_to`` depth: an int (not bool) >= 0 (logic §5.6)."""
    if isinstance(depth, bool) or not isinstance(depth, int):
        raise TypeError(f"depth must be an int, got {type(depth).__name__}")
    if depth < 0:
        raise ValueError(f"depth must be >= 0, got {depth}")
    return depth


@contextmanager
def _recursion_limit(minimum: int) -> Iterator[None]:
    """Temporarily raise the recursion limit to at least ``minimum`` (logic §6)."""
    previous = sys.getrecursionlimit()
    sys.setrecursionlimit(max(previous, minimum))
    try:
        yield
    finally:
        sys.setrecursionlimit(previous)


_INCONSISTENT_HINT = (
    "The knowledge base is inconsistent (the board cannot be completed or your facts "
    "contradict it). Undo the last placement or clear your facts."
)


class SudokuKB:
    """Rule layer from the board plus the agent layer (logic §1, §5)."""

    def __init__(self, board: Board) -> None:
        self._agent: list[_AgentEntry] = []
        self.rebuild(board)

    # ------------------------------------------------------------ maintenance

    def rebuild(self, board: Board) -> None:
        """Regenerate the rule layer from ``board``; keep the agent layer (logic §5.1)."""
        self._board = board
        self._rules = rule_clauses(board)
        self._reset_solver()

    def _reset_solver(self) -> None:
        """Rebuild the proplogic KB from both layers and clear the cache (logic §5.8)."""
        self._solver = KnowledgeBase(self._rules)
        self._symbols = {literal.symbol for clause in self._rules for literal in clause}
        self._materialized: set[str] = set()
        self._cache: dict[str, bool] = {}
        self._consistent: bool | None = None
        for entry in self._agent:
            self._add_clauses(entry.clauses)

    def _add_clauses(self, clauses: Iterable[Clause]) -> None:
        """Add CNF clauses to the solver, with the filled-cell facts they need."""
        clauses = tuple(clauses)
        self._materialize({literal.symbol for clause in clauses for literal in clause})
        for clause in clauses:
            self._solver.add_clause(*clause)
            self._symbols.update(literal.symbol for literal in clause)

    def _materialize(self, symbols: Iterable[str]) -> None:
        """Add the §3.6 facts for filled-cell variables among ``symbols``.

        These facts are part of the rule layer by definition, so adding them
        never changes any answer (and does not clear the cache). Unmentioned
        filled-cell variables occur in no clause and so need no facts.
        """
        for symbol in symbols:
            match = _CELL_VARIABLE.fullmatch(symbol)
            if match is None or symbol in self._materialized:
                continue
            r, c, d = (int(g) for g in match.groups())
            filled = self._board.cell(r, c)
            if filled:
                self._solver.add_fact(Literal(symbol, filled == d))
                self._symbols.add(symbol)
                self._materialized.add(symbol)

    # ------------------------------------------------------------ satisfiability

    def _solve(self, check):
        """Run one proplogic check with a recursion limit large enough (logic §6)."""
        needed = _FRAMES_PER_SYMBOL * (len(self._symbols) + 1) + _RECURSION_HEADROOM
        with _recursion_limit(needed):
            return check()

    def _entails(self, query: str) -> bool:
        """Whether the KB entails ``query`` (a valid formula), memoized (logic §5.8)."""
        if query not in self._cache:
            self._cache[query] = self._solve(lambda: self._solver.entails(query))
        return self._cache[query]

    def is_consistent(self) -> bool:
        """Whether rule layer and agent layer together are satisfiable (logic §5.2)."""
        if self._consistent is None:
            self._consistent = self._solve(self._solver.is_consistent)
        return self._consistent

    # ------------------------------------------------------------ §5.3 tell

    def tell(self, formula: str) -> TellResult:
        """Add a formula to the agent layer unless a check of logic §5.3 rejects it."""
        try:
            clauses, symbols = _check_formula(formula)
        except _FormulaError as error:
            return TellResult(False, error.reason, error.message)
        if not self.is_consistent():
            return TellResult(False, "KB_INCONSISTENT", _INCONSISTENT_HINT)
        if any(entry.formula == formula for entry in self._agent):
            return TellResult(True, None, "Already known; not stored twice.")

        self._materialize(symbols)
        if self._entails(_negation(formula)):
            return TellResult(
                False,
                "INCONSISTENT",
                "Rejected: this formula contradicts the Sudoku rules, the board or your earlier facts.",
            )

        self._agent.append(_AgentEntry(self._board.depth, formula, clauses))
        self._add_clauses(clauses)
        self._cache.clear()
        self._consistent = True   # just shown: KB and formula are jointly satisfiable
        return TellResult(True, None, f"Added. The agent layer holds {len(self._agent)} facts.")

    # ------------------------------------------------------------ §5.4 ask

    def ask(self, formula: str) -> AskResult:
        """Answer ENTAILED, CONTRADICTED or UNRESOLVED (logic §5.4); never changes the KB."""
        try:
            _, symbols = _check_formula(formula)
        except _FormulaError as error:
            return AskResult(False, None, error.reason, error.message)
        if not self.is_consistent():
            return AskResult(False, None, "KB_INCONSISTENT", _INCONSISTENT_HINT)

        self._materialize(symbols)
        if self._entails(formula):
            answer = Answer.ENTAILED
        elif self._entails(_negation(formula)):
            answer = Answer.CONTRADICTED
        else:
            answer = Answer.UNRESOLVED
        return AskResult(True, answer, None, f"{formula}: {answer.value}.")

    # ------------------------------------------------------------ §5.5, §5.6

    def clear_agent_facts(self) -> int:
        """Empty the agent layer; return the number of entries removed (logic §5.5)."""
        removed = len(self._agent)
        self._agent = []
        self._reset_solver()
        return removed

    def rollback_to(self, depth: int) -> int:
        """Drop agent entries told at a depth greater than ``depth`` (logic §5.6)."""
        _check_depth(depth)
        kept = [entry for entry in self._agent if entry.depth <= depth]
        removed = len(self._agent) - len(kept)
        if removed:
            self._agent = kept
            self._reset_solver()
        return removed

    def agent_facts(self) -> tuple[tuple[int, str], ...]:
        """The agent layer as ``(depth, formula)`` pairs, oldest first."""
        return tuple((entry.depth, entry.formula) for entry in self._agent)

    # ------------------------------------------------------------ §5.7 infer_cell

    def infer_cell(self, row: int, col: int) -> InferResult:
        """Per-cell sweep over the board candidates of (row, col) (logic §5.7).

        Each candidate ``d`` is ruled out when KB entails ``~v{r}{c}{d}``. The
        digit is proven exactly when one candidate remains: KB then entails it
        through the "cell has a digit" rule (§3.1), and if two or more remain,
        the "at most one digit" rule (§3.3) means neither can be entailed
        without the other being ruled out. So one entailment check per
        candidate decides everything.
        """
        filled = self._board.cell(row, col)   # also validates row and col (board §4)
        if filled:
            return InferResult(True, filled, (filled,), (), None, f"r{row}c{col} already holds {filled}.")
        if not self.is_consistent():
            return InferResult(False, None, (), (), "KB_INCONSISTENT", _INCONSISTENT_HINT)

        possible: list[int] = []
        ruled_out: list[int] = []
        for d in self._board.candidates(row, col):
            variable = cell_variable(row, col, d)
            (ruled_out if self._entails(_negation(variable)) else possible).append(d)

        if len(possible) == 1:
            digit = possible[0]
            message = f"Proven: r{row}c{col}={digit}."
        else:
            digit = None
            message = f"r{row}c{col} is not decided; still possible: {possible}."
        return InferResult(True, digit, tuple(possible), tuple(ruled_out), None, message)
