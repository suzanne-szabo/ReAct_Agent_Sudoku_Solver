"""Sudoku board: puzzle state, placement, undo, views and candidates.

Implements specs/board.md (architecture §4.1). Coordinates, boxes and digits
follow architecture §2: rows, columns and boxes are numbered 1-9 and an empty
cell is stored as 0. The board knows nothing about tools, budgets, the
knowledge base or the model.
"""

from __future__ import annotations

from dataclasses import dataclass

Cell = tuple[int, int]            # (row, col), 1-9 each
Placement = tuple[int, int, int]  # (row, col, digit)

DIGITS = range(1, 10)


@dataclass(frozen=True)
class PlaceResult:
    """Outcome of ``Board.place`` (board §2, §4.6)."""

    accepted: bool
    reason: str | None
    message: str
    forced_cells: tuple[Placement, ...]
    dead_cells: tuple[Cell, ...]


@dataclass(frozen=True)
class UndoResult:
    """Outcome of ``Board.undo`` (board §2, §4.7)."""

    accepted: bool
    reason: str | None
    message: str
    removed: Placement | None


def _check_index(value: object, name: str) -> int:
    """Return ``value`` if it is an int (not bool) in 1-9 (board §4).

    Raises ``TypeError`` for a wrong type and ``ValueError`` for a value out of
    range.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value not in DIGITS:
        raise ValueError(f"{name} must be in 1-9, got {value}")
    return value


def box_of(row: int, col: int) -> int:
    """Box number (1-9, row-major) containing the cell (architecture §2)."""
    return 3 * ((row - 1) // 3) + (col - 1) // 3 + 1


def box_cells(box: int) -> list[Cell]:
    """The 9 cells of ``box`` in row-major order (architecture §2)."""
    top = 3 * ((box - 1) // 3) + 1
    left = 3 * ((box - 1) % 3) + 1
    return [(top + i, left + j) for i in range(3) for j in range(3)]


class Board:
    """One puzzle's givens, current digits and undo stack (board §1)."""

    def __init__(self, grid: list[list[int]]) -> None:
        """Create a board whose non-zero entries are the givens.

        Use ``Board.from_string``; it validates the input first.
        """
        self._grid = [list(row) for row in grid]
        self._givens = frozenset(
            (r, c) for r in DIGITS for c in DIGITS if grid[r - 1][c - 1] != 0
        )
        self._stack: list[Placement] = []

    # ------------------------------------------------------------ §3 construction

    @classmethod
    def from_string(cls, puzzle: str) -> Board:
        """Parse an 81-character puzzle string (board §3).

        Whitespace is ignored. ``0`` and ``.`` mean empty. Raises ``TypeError``
        for a non-``str`` and ``ValueError`` for a wrong length, a bad
        character or duplicate givens.
        """
        if not isinstance(puzzle, str):
            raise TypeError(f"puzzle must be a str, got {type(puzzle).__name__}")
        text = "".join(puzzle.split())
        if len(text) != 81:
            raise ValueError(f"puzzle must have 81 cells, got {len(text)}")
        bad = sorted(set(text) - set("0123456789."))
        if bad:
            raise ValueError(f"puzzle contains invalid characters: {''.join(bad)!r}")
        text = text.replace(".", "0")
        grid = [[int(text[r * 9 + c]) for c in range(9)] for r in range(9)]
        board = cls(grid)
        for r, c in board._givens:
            d = board.cell(r, c)
            if board._conflicting_unit(r, c, d, ignore=(r, c)) is not None:
                raise ValueError(f"duplicate given {d} at r{r}c{c}")
        return board

    # ------------------------------------------------------------ §4.1 read views

    def cell(self, r: int, c: int) -> int:
        """The digit at (r, c), or 0 if empty."""
        _check_index(r, "row")
        _check_index(c, "col")
        return self._grid[r - 1][c - 1]

    def row(self, r: int) -> list[int]:
        """The 9 digits of row ``r``, left to right."""
        _check_index(r, "row")
        return list(self._grid[r - 1])

    def col(self, c: int) -> list[int]:
        """The 9 digits of column ``c``, top to bottom."""
        _check_index(c, "col")
        return [self._grid[r][c - 1] for r in range(9)]

    def box(self, b: int) -> list[int]:
        """The 9 digits of box ``b``, row-major within the box."""
        _check_index(b, "box")
        return [self._grid[r - 1][c - 1] for r, c in box_cells(b)]

    def grid(self) -> tuple[tuple[int, ...], ...]:
        """An immutable 9x9 snapshot of the current digits."""
        return tuple(tuple(row) for row in self._grid)

    def is_given(self, r: int, c: int) -> bool:
        """Whether (r, c) was a given in the original puzzle."""
        _check_index(r, "row")
        _check_index(c, "col")
        return (r, c) in self._givens

    def empty_cells(self) -> list[Cell]:
        """All empty cells in row-major order."""
        return [(r, c) for r in DIGITS for c in DIGITS if self._grid[r - 1][c - 1] == 0]

    def is_complete(self) -> bool:
        """Whether the board has no empty cells."""
        return not self.empty_cells()

    @property
    def depth(self) -> int:
        """The number of placements on the undo stack."""
        return len(self._stack)

    def placements(self) -> tuple[Placement, ...]:
        """The undo stack, oldest first."""
        return tuple(self._stack)

    # ------------------------------------------------------------ §4.2 render

    def render(self) -> str:
        """The compact 11-line text grid shown to the model (board §4.2)."""
        separator = "   --- --- ---"
        lines = ["   123 456 789"]
        for r in DIGITS:
            text = "".join(str(d) if d else "." for d in self._grid[r - 1])
            lines.append(f"{r}  {text[0:3]} {text[3:6]} {text[6:9]}")
            if r in (3, 6):
                lines.append(separator)
        return "\n".join(lines)

    # ------------------------------------------------------------ §4.3, §4.4

    def candidates(self, r: int, c: int) -> list[int]:
        """Sorted digits not used in the cell's row, column or box; [] if filled."""
        if self.cell(r, c) != 0:
            return []
        used = set(self.row(r)) | set(self.col(c)) | set(self.box(box_of(r, c)))
        return [d for d in DIGITS if d not in used]

    def forced_placements(self) -> list[Placement]:
        """Placements forced by pencil-mark logic alone (board §4.3a, v4).

        A cell with a single candidate, or the only cell of a row, column or box
        that can still take a missing digit. Sorted, without duplicates.
        """
        candidates = {cell: self.candidates(*cell) for cell in self.empty_cells()}
        forced = {(r, c, digits[0]) for (r, c), digits in candidates.items() if len(digits) == 1}
        units = [[(r, c) for c in DIGITS] for r in DIGITS]
        units += [[(r, c) for r in DIGITS] for c in DIGITS]
        units += [box_cells(b) for b in DIGITS]
        for unit in units:
            for d in DIGITS:
                spots = [cell for cell in unit if d in candidates.get(cell, ())]
                if len(spots) == 1:
                    forced.add((*spots[0], d))
        return sorted(forced)

    def peers(self, r: int, c: int) -> set[Cell]:
        """The 20 cells sharing a row, column or box with (r, c)."""
        _check_index(r, "row")
        _check_index(c, "col")
        cells = {(r, j) for j in DIGITS} | {(i, c) for i in DIGITS}
        cells |= set(box_cells(box_of(r, c)))
        cells.discard((r, c))
        return cells

    # ------------------------------------------------------------ §4.6 place

    def place(self, r: int, c: int, d: int) -> PlaceResult:
        """Place digit ``d`` at (r, c), applying the checks of board §4.6 in order."""
        _check_index(r, "row")
        _check_index(c, "col")
        _check_index(d, "digit")

        if self.is_given(r, c):
            return _rejected_place("GIVEN_CELL", f"r{r}c{c} is a given and cannot be changed.")
        if self.cell(r, c) != 0:
            return _rejected_place(
                "CELL_FILLED", f"r{r}c{c} already holds {self.cell(r, c)}; undo it first."
            )
        unit = self._conflicting_unit(r, c, d)
        if unit is not None:
            return _rejected_place("CONFLICT", f"{d} already in {unit}")

        open_peers = sorted(p for p in self.peers(r, c) if self.cell(*p) == 0)
        counts_before = {p: len(self.candidates(*p)) for p in open_peers}

        self._grid[r - 1][c - 1] = d
        self._stack.append((r, c, d))

        forced: list[Placement] = []
        dead: list[Cell] = []
        for p in open_peers:
            after = self.candidates(*p)
            if not after:
                dead.append(p)
            elif len(after) == 1 and counts_before[p] > 1:
                forced.append((p[0], p[1], after[0]))
        return PlaceResult(True, None, f"Placed {d} at r{r}c{c}.", tuple(forced), tuple(dead))

    def _conflicting_unit(
        self, r: int, c: int, d: int, ignore: Cell | None = None
    ) -> str | None:
        """Name the first unit ("row R", "column C", "box B") already holding ``d``.

        ``ignore`` excludes one cell (used when checking a given against its peers).
        """
        units = (
            (f"row {r}", [(r, j) for j in DIGITS]),
            (f"column {c}", [(i, c) for i in DIGITS]),
            (f"box {box_of(r, c)}", box_cells(box_of(r, c))),
        )
        for name, cells in units:
            if any(cell != ignore and self.cell(*cell) == d for cell in cells):
                return name
        return None

    # ------------------------------------------------------------ §4.7 undo

    def undo(self) -> UndoResult:
        """Remove the most recent placement (LIFO); givens are never removed."""
        if not self._stack:
            return UndoResult(False, "EMPTY_STACK", "There is no placement to undo.", None)
        r, c, d = self._stack.pop()
        self._grid[r - 1][c - 1] = 0
        return UndoResult(True, None, f"Removed {d} from r{r}c{c}.", (r, c, d))


def _rejected_place(reason: str, message: str) -> PlaceResult:
    """A rejected ``PlaceResult``: nothing changed, nothing forced or dead."""
    return PlaceResult(False, reason, message, (), ())
