# Functional Specification — `sudoku_agent.board`

Status: **Approved v1 (orchestrator review 2026-10-17)**
Parent: `specs/architecture.md` §4.1. Conventions (1–9 coordinates, box
numbering, `0` = empty) are defined in architecture §2.

## 1. Purpose

`Board` holds the state of one Sudoku puzzle: the immutable givens, the current
digits, and the undo stack. It enforces the Sudoku placement invariants and
provides read views and candidates. It knows nothing about tools, budgets,
the knowledge base or the model.

## 2. Types

```python
Cell = tuple[int, int]            # (row, col), 1-9 each
Placement = tuple[int, int, int]  # (row, col, digit)

@dataclass(frozen=True)
class PlaceResult:
    accepted: bool
    reason: str | None            # None when accepted; else a code from §4.6
    message: str                  # short human-readable explanation
    forced_cells: tuple[Placement, ...]   # see §4.6; () when rejected
    dead_cells: tuple[Cell, ...]          # see §4.6; () when rejected

@dataclass(frozen=True)
class UndoResult:
    accepted: bool
    reason: str | None            # None or "EMPTY_STACK"
    message: str
    removed: Placement | None     # the placement that was undone
```

## 3. Construction

### `Board.from_string(puzzle: str) -> Board`

- Whitespace (spaces, tabs, newlines) is removed first, so puzzle files may be
  formatted as 9 lines.
- After that, the string must be exactly 81 characters, each one of `0-9` or `.`.
  `0` and `.` mean empty; `1-9` are givens.
- **Errors:**
  - `TypeError` if `puzzle` is not a `str`.
  - `ValueError` if the length is not 81 after whitespace removal, if any other
    character appears, or if the givens already contain a duplicate digit in a
    row, column or box.
- Whether the puzzle has a unique solution, or any solution, is **not** checked.
- The new board has `depth == 0`.

## 4. Operations

All coordinate arguments must be `int` (not `bool`) in the range 1–9, and
`digit` arguments must be `int` (not `bool`) in 1–9. Violations raise
`TypeError` for the wrong type or `ValueError` for an out-of-range value, and
mutate nothing. (The controller validates the schema first, so these are
defensive errors, not normal rejections.)

### 4.1 Read views (never mutate)

| Method | Returns |
|---|---|
| `cell(r, c) -> int` | The digit at (r, c), or `0` if empty. |
| `row(r) -> list[int]` | 9 digits, left to right. |
| `col(c) -> list[int]` | 9 digits, top to bottom. |
| `box(b) -> list[int]` | 9 digits of box `b` in row-major order within the box. |
| `grid() -> tuple[tuple[int, ...], ...]` | An immutable 9×9 snapshot; later board changes do not affect it. |
| `is_given(r, c) -> bool` | `True` if the cell was a given in the original puzzle. |
| `empty_cells() -> list[Cell]` | All empty cells in row-major order. |
| `is_complete() -> bool` | `True` when there are no empty cells. |
| `depth -> int` (property) | The number of placements currently on the undo stack. |
| `placements() -> tuple[Placement, ...]` | The undo stack, oldest first. |

### 4.2 `render() -> str`

A compact text grid for the model. The exact format is 11 lines with no
trailing spaces:

```
   123 456 789
1  53. .7. ...
2  6.. 195 ...
3  .98 ... .6.
   --- --- ---
4  8.. .6. ..3
...
9  ... .8. .79
```

- Line 1 is a column header: three spaces, then `123 456 789`.
- Each row line is the row number, two spaces, then the three box groups
  separated by single spaces. Empty cells are shown as `.`.
- A separator line `   --- --- ---` comes after rows 3 and 6.

### 4.3 `candidates(r, c) -> list[int]`

- For an empty cell: the sorted digits 1–9 that do **not** appear in the
  cell's row, column or box.
- For a filled cell (given or placed): `[]`.
- An empty cell may have `[]` (a "dead" cell); this means the current board
  has no valid completion.

### 4.3a `forced_placements() -> list[Placement]` *(v4)*

The placements forced by simple pencil-mark logic on the current board, without
the knowledge base:

- **Single candidate:** an empty cell whose `candidates` list has exactly one
  digit `d` gives `(r, c, d)`.
- **Only place in a unit:** for a row, column or box and a digit `d` not yet
  in it, if exactly one empty cell of that unit has `d` as a candidate, that
  cell gives `(r, c, d)`.

The result has no duplicates and is sorted by (row, col, digit). It is empty when
nothing is forced. A dead cell (no candidates) gives nothing. Read-only.

### 4.4 `peers(r, c) -> set[Cell]`

The 20 cells that share a row, column or box with (r, c), excluding (r, c) itself.

### 4.5 Undo stack

The stack holds accepted placements, oldest first. Only accepted `place` calls
push to it; only accepted `undo` calls pop from it.

### 4.6 `place(r, c, d) -> PlaceResult`

The checks are applied **in this order**. The first failing check determines
the rejection, and a rejection mutates nothing:

1. `GIVEN_CELL` — (r, c) is a given.
2. `CELL_FILLED` — (r, c) already holds a placed digit.
3. `CONFLICT` — `d` already appears in the row, column or box of (r, c). The
   message names the conflicting unit, for example `"7 already in row 3"`.

If all checks pass, the digit is written, `(r, c, d)` is pushed onto the undo
stack, and the result is `accepted=True` with:

- **`forced_cells`** — every empty peer of (r, c) whose candidate list had
  more than one digit **before** the placement and exactly one digit **after**
  it, given as `(row, col, only_candidate)`, sorted by (row, col). This is the
  cascade report.
- **`dead_cells`** — every empty peer of (r, c) whose candidate list is empty
  after the placement, sorted. A non-empty `dead_cells` means the placement
  was wrong.

Placing a digit that does not conflict but is not part of the solution is
**accepted** (architecture D9).

### 4.7 `undo() -> UndoResult`

- If the stack is empty: `accepted=False`, `reason="EMPTY_STACK"`, and nothing
  changes.
- Otherwise: pop the most recent placement `(r, c, d)`, set that cell back to
  `0`, and return `accepted=True, removed=(r, c, d)`.
- Givens can never be removed by undo.

## 5. Invariants (must hold after every public call)

- **I1** Every given cell holds its original digit.
- **I2** No row, column or box contains the same non-zero digit twice.
- **I3** `depth == len(placements())`, and the non-given filled cells are
  exactly the cells in `placements()`.
- **I4** A call that is rejected or raises leaves `grid()`, `depth` and
  `placements()` unchanged.
- **I5** `place` followed by an accepted `undo` restores the previous `grid()`
  exactly.

## 6. Test obligations (black-box)

- Parsing: valid strings with `.` and `0`; multi-line whitespace; wrong length;
  a bad character; duplicate givens; a non-`str` input.
- Views: `cell`, `row`, `col` and `box` (including boxes 1, 5 and 9) against a
  known puzzle; `grid()` is a snapshot; the exact `render()` output.
- Candidates: an empty cell; a filled cell returns `[]`; a dead cell.
- `forced_placements()`: the exact list on the easy puzzle's starting board (4 single-candidate
  cells and 12 only-place-in-unit cells, 16 entries); empty on a complete board; read-only.
- Placement: each rejection code in priority order (a given cell that also
  conflicts reports `GIVEN_CELL`); acceptance; `forced_cells` on a constructed
  cascade; `dead_cells` after a wrong placement; argument type and range errors.
- Undo: an empty stack; LIFO order over three placements; a restore check (I5).
- Invariants I1–I4 checked after sequences of mixed accepted and rejected calls.
