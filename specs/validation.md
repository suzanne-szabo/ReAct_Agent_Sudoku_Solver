# Functional Specification — `sudoku_agent.validation`

Status: **Draft v1 — awaiting orchestrator review**
Parent: `specs/architecture.md` §4.2.

## 1. Purpose

Decide whether a final grid is a correct solution of the **original** puzzle.
The validator is deliberately independent of `Board`: it re-parses the
original puzzle string itself and does not import `board`. As a result, a bug in
the board's bookkeeping cannot make an incorrect board count as solved.

## 2. Interface

```python
@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reasons: tuple[str, ...]   # () when valid

def validate_solution(original_puzzle: str, grid) -> ValidationResult
```

- `original_puzzle` uses the same format as `Board.from_string`: 81 characters
  of `0-9` or `.` after whitespace removal.
  - A malformed `original_puzzle` raises `ValueError`, or `TypeError` if it is
    not a `str`.
  - Duplicate givens are not checked here, since the grid checks would catch them.
- `grid` is any sequence of 9 sequences of 9 values. It is never mutated.

## 3. Checks and reason codes

1. **Shape.** If `grid` is not 9 rows of 9 entries, return immediately with
   `("BAD_SHAPE",)`.
2. Then all of the following are evaluated, and **every** failure is reported,
   in this order:
   - **`BAD_VALUE r{R}c{C}`** — the entry is not an `int` in 0–9 (`bool` counts as invalid).
   - **`EMPTY r{R}c{C}`** — the entry is `0`.
   - **`GIVEN_CHANGED r{R}c{C}`** — a given cell does not hold its original digit.
   - **`ROW_INVALID {R}`**, **`COL_INVALID {C}`**, **`BOX_INVALID {B}`** — the unit's
     values are not exactly the set {1,…,9}. (Units containing a `BAD_VALUE`
     or `EMPTY` entry also fail this check.)
3. Within each code, reasons are listed in row-major (or unit-number) order.
4. `valid` is `True` exactly when `reasons` is empty.

## 4. Test obligations (black-box)

- A known correct solution is valid.
- A complete grid with two swapped digits in one row is invalid, with
  `ROW_INVALID`, `COL_INVALID` and/or `BOX_INVALID` as appropriate.
- An incomplete grid reports `EMPTY` for each empty cell.
- A changed given reports `GIVEN_CHANGED`, even if the grid is otherwise a valid Sudoku.
- Wrong shapes (8 rows, a row of 10) report `BAD_SHAPE` only.
- Non-int, out-of-range and `bool` entries report `BAD_VALUE`.
- A malformed original puzzle raises.
- The grid argument is not mutated.
