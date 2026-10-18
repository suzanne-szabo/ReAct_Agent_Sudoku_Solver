# Functional Specification — `sudoku_agent.tools`

Status: **Approved v2 (orchestrator review 2026-10-17; v2 adds `kb_infer_cell`)**
Parent: `specs/architecture.md` §4.5. Uses `board` (`specs/board.md`), `logic`
(`specs/logic.md`) and `validation` (`specs/validation.md`).

## 1. Purpose

`tools` defines the **only** actions the model may request. For each action it
defines a typed argument schema and an executor that performs an
already-approved request against a `Session`. The executor is the only code
that calls mutating methods on `Board` and `SudokuKB`.

## 2. Argument schemas

All schemas are Pydantic v2 models with `extra="forbid"`. Integer fields are
**strict**: JSON integers only. Strings such as `"3"`, floats and booleans are
schema errors.

| Tool | Schema fields |
|---|---|
| `read_board` | *(none)* |
| `read_cell` | `row: int 1–9`, `col: int 1–9` |
| `read_row` | `row: int 1–9` |
| `read_col` | `col: int 1–9` |
| `read_box` | `box: int 1–9` |
| `get_candidates` | `row: int 1–9`, `col: int 1–9` |
| `place_number` | `row: int 1–9`, `col: int 1–9`, `digit: int 1–9` |
| `undo` | *(none)* |
| `kb_tell` | `formula: str` (min length 1) |
| `kb_ask` | `formula: str` (min length 1) |
| `kb_infer_cell` | `row: int 1–9`, `col: int 1–9` |
| `kb_clear` | *(none)* |
| `submit` | *(none)* |

- `TOOL_SCHEMAS: dict[str, type[BaseModel]]` maps tool names to their schemas.
- `tool_definitions()` returns the tools in the form LangChain's `bind_tools`
  accepts. Each definition carries a one-sentence description, written in
  `tools.py`, that tells the model what the tool returns and costs.
- The formula length limit is enforced by `logic` (`TOO_LONG`), so that limit
  has a single source of truth.

## 3. Execution interface

```python
@dataclass(frozen=True)
class ToolOutcome:
    accepted: bool
    reason: str | None   # domain rejection code from board/logic/validation, else None
    message: str         # short and human-readable, shown to the model
    data: dict           # JSON-serializable, tool-specific (§4)

def execute(session: Session, tool_name: str, args: BaseModel) -> ToolOutcome
```

- `execute` assumes the controller has already approved the request
  (`specs/controller.md`). It still never leaves the state partially changed:
  if `board` or `logic` rejects, the outcome is `accepted=False` and nothing
  has changed.
- The **budget is not included** here. The controller adds `budget_remaining`
  when it turns a `ToolOutcome` into an `Observation`.
- Unknown tool names raise `KeyError`. The controller is responsible for
  rejecting them first.

## 4. Per-tool behavior and `data`

Row, column and box strings are 9 characters of digits, with `.` for empty
cells, for example `"53..7...."`.

| Tool | On acceptance | Rejection reasons |
|---|---|---|
| `read_board` | `{"board": board.render(), "empty": n}` | — |
| `read_cell` | `{"row", "col", "digit": 0-9, "given": bool, "candidates": [..]}` | — |
| `read_row` | `{"row": r, "cells": "53..7...."}` | — |
| `read_col` | `{"col": c, "cells": "…"}` | — |
| `read_box` | `{"box": b, "cells": "…"}` (row-major within the box) | — |
| `get_candidates` | `{"row", "col", "candidates": [..]}` (`[]` if filled) | — |
| `place_number` | See §4.1. | `GIVEN_CELL`, `CELL_FILLED`, `CONFLICT` |
| `undo` | See §4.2. | `EMPTY_STACK` |
| `kb_tell` | `{"facts": count of agent facts}` | `PARSE_ERROR`, `INVALID_SYMBOL`, `TOO_LONG`, `INCONSISTENT`, `KB_INCONSISTENT` |
| `kb_ask` | `{"answer": "entailed" \| "contradicted" \| "unresolved"}` | `PARSE_ERROR`, `INVALID_SYMBOL`, `TOO_LONG`, `KB_INCONSISTENT` |
| `kb_infer_cell` | `{"row", "col", "digit": d or null, "possible": [..], "ruled_out": [..]}` | `KB_INCONSISTENT` |
| `kb_clear` | `{"removed": n}` | — |
| `submit` | `{"result": "SOLVED"}` | `INVALID_SOLUTION` (§4.3) |

Read tools, `kb_ask` and `kb_infer_cell` never change the board or the KB's content (only `logic`'s answer cache).

### 4.1 `place_number`

1. Call `board.place(r, c, d)`. If it is rejected, return the board's reason and
   message, with `data = {"reason": code}`.
2. If it is accepted: call `kb.rebuild(board)`, then compute
   `consistent = kb.is_consistent()`.
3. Return the following `data`:
   ```json
   {"placed": [r, c, d],
    "forced": [[r, c, d], ...],
    "dead":   [[r, c], ...],
    "kb_consistent": true,
    "empty": n}
   ```
4. The `message` summarizes the result and must name each forced cell in the
   form `r{R}c{C}={D}`, for example `"Placed 4 at r1c3. Forced: r1c4=6, r2c3=2."`
   - If `dead` is non-empty or `kb_consistent` is false, the message must also
     say: `"This placement leads to a contradiction; undo it."`

### 4.2 `undo`

1. Call `board.undo()`. If it is rejected, return `EMPTY_STACK`.
2. If it is accepted: call `kb.rebuild(board)`, then
   `n = kb.rollback_to(board.depth)`.
3. Return `data = {"removed": [r, c, d], "facts_rolled_back": n, "kb_consistent": bool, "empty": n_empty}`.

### 4.3 `submit`

1. Call `validate_solution(session.original_puzzle, board.grid())`.
2. If it is valid: `accepted=True`, `data={"result": "SOLVED"}`. The controller
   sets the terminal status.
3. If it is not valid: `accepted=False`, `reason="INVALID_SOLUTION"`, and
   `data={"reasons": first 10 reasons, "total": len(reasons)}`. The list is
   capped at 10 to keep observations short.

## 5. Test obligations (black-box)

- **Schemas:** valid arguments are accepted. Missing fields, extra fields, out
  of range (0, 10), string, float and bool values are all schema errors.
  `tool_definitions()` has exactly the 13 tool names.
- **Each read tool** returns the specified `data` for a known puzzle and leaves
  the board and KB unchanged.
- **`place_number`:**
  - acceptance with `forced` on a constructed cascade;
  - each rejection code, with no change afterward;
  - a wrong-but-legal placement gives `kb_consistent: false` and the undo hint
    in the message.
- **`undo`:** restores the board, rolls back facts told after the placement and
  keeps earlier ones; `EMPTY_STACK` on a fresh session.
- **`kb_infer_cell`:** returns the proven digit on an easy-puzzle cell and leaves
  the board unchanged.
- **`kb_tell`, `kb_ask`, `kb_clear`:** the codes pass through from `logic`, and
  `kb_clear` leaves rule-based answers unchanged.
- **`submit`:** the solved board is accepted; an incomplete board is rejected
  with `EMPTY` reasons capped at 10 and the correct `total`.
- **JSON:** every outcome's `data` survives `json.dumps`.
