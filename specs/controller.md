# Functional Specification — `sudoku_agent.controller`

Status: **Approved v1 (orchestrator review 2026-10-17)**
Parent: `specs/architecture.md` §4.6, §6, §8. Uses `tools` (`specs/tools.md`).

## 1. Purpose

The controller is the single gatekeeper between the model's requests and the
application state. It:

- validates every request before anything changes;
- dispatches approved requests to `tools.execute`;
- charges the action budget;
- records the trace; and
- owns the terminal status.

Nothing else may set the terminal status.

## 2. Configuration

```python
@dataclass(frozen=True)
class Config:
    max_actions: int = 500
    max_consecutive_rejections: int = 5
    model_name: str = "Qwen3.8-27B"
    history_window: int = 12        # used by agent (specs/agent.md)
```

## 3. Types

```python
class TerminalStatus(Enum):
    SOLVED = "SOLVED"
    ACTION_LIMIT = "ACTION_LIMIT"
    REJECTION_LIMIT = "REJECTION_LIMIT"
    NO_ACTION = "NO_ACTION"
    MODEL_ERROR = "MODEL_ERROR"

@dataclass(frozen=True)
class Observation:
    tool: str
    accepted: bool
    policy: str | None        # "P1".."P10" when rejected, else None
    reason: str | None        # domain or policy code
    message: str
    data: dict
    budget_remaining: int
    def to_json(self) -> str  # compact JSON; this is what the model sees

@dataclass(frozen=True)
class Approval:
    tool: str
    args: BaseModel           # the validated schema instance

@dataclass(frozen=True)
class TraceEntry:
    step: int                 # 1-based, one per handled call
    tool: str
    args: dict | str          # the raw args as received
    accepted: bool
    policy: str | None
    reason: str | None
    message: str
    budget_remaining: int
    board_depth: int
```

## 4. Interface

```python
class Controller:
    def __init__(self, session: Session, config: Config) -> None
    def validate(self, tool_name: str, raw_args: dict | str) -> Approval | Observation
    def execute(self, approval: Approval) -> Observation
    def handle(self, tool_name: str, raw_args: dict | str) -> Observation  # validate + execute
    def reject_extra_call(self, tool_name: str, raw_args: dict | str) -> Observation  # P10
    def record_no_action(self) -> None
    def record_model_error(self, error: Exception) -> None
    def check_terminal(self) -> TerminalStatus | None
    # read-only properties
    actions_used: int
    budget_remaining: int            # max_actions - actions_used, never below 0
    consecutive_rejections: int
    terminal_status: TerminalStatus | None
    terminal_reason: str | None
    trace: tuple[TraceEntry, ...]
```

## 5. Validation (`validate`)

`validate` mutates nothing except the counters and trace on rejection. The
checks run in this order, and the first failure produces a rejection
`Observation`:

| Policy | Condition | `reason` |
|---|---|---|
| **P1** | A terminal status is already set. | `TERMINAL` |
| **P2** | `tool_name` is not in `TOOL_SCHEMAS`. | `UNKNOWN_TOOL` |
| **P3** | `raw_args` is a string that is not a JSON object, or it fails the tool's schema. | `BAD_ARGS` (message includes the first schema error) |
| **P4** | `place_number` on a given cell. | `GIVEN_CELL` |
| **P5** | `place_number` on a cell that is already filled. | `CELL_FILLED` |
| **P6** | `place_number` with a digit already in the row, column or box. | `CONFLICT` |
| **P7** | `undo` with an empty undo stack. | `EMPTY_STACK` |
| **P9** | `submit` when `validate_solution` fails. | `INVALID_SOLUTION` (data as in tools §4.3) |

- P4–P7 and P9 are checked with **read-only** queries (`is_given`, `cell`,
  `candidates`/peers, `depth`, `validate_solution`). The board and KB enforce
  the same rules again defensively.
- P8 (KB formula problems and inconsistent tells) can only be decided by
  `logic` itself. It is detected during `execute`: a `kb_tell`, `kb_ask` or
  `kb_infer_cell` outcome rejected by `logic` is reported as a **P8** rejection. `logic`
  guarantees that such a rejection changes nothing.
- If every check passes, `validate` returns an `Approval` and changes nothing.

## 6. Execution (`execute`)

Calls `tools.execute(session, approval.tool, approval.args)` and turns the
`ToolOutcome` into an `Observation`. A logic rejection becomes policy P8. Any
other rejection at this stage would indicate a validation gap and must not
happen; tests check this.

## 7. Accounting (applies to every handled call)

- **Budget:** each call to `validate` that is not a P1 rejection, and each
  `reject_extra_call`, adds 1 to `actions_used`. This happens before the
  observation is built, so `budget_remaining` already reflects the call.
  - A validated call is charged once, in total, across `validate` and `execute`.
  - P1 rejections are not charged, because the run is already over.
- **Rejection streak:** `consecutive_rejections` resets to 0 on any accepted
  observation and increases by 1 on any rejected one (P2–P10).
- **Trace:** exactly one `TraceEntry` is appended per handled call. For a
  successful call, that is after `execute`; for a rejected call, at rejection
  time.
- **Solved:** an accepted `submit` records that the run is solved, for
  `check_terminal`.

## 8. Extra calls (P10)

If a model turn contains more than one tool call, the agent sends only the
first through `validate`/`execute`. Each further call goes to
`reject_extra_call`, which:

- returns `accepted=False, policy="P10", reason="ONE_CALL_PER_TURN"`;
- charges 1 action; and
- counts toward the rejection streak.

## 9. Terminal checks (`check_terminal`)

These are evaluated **in this order**. The first condition that holds sets
`terminal_status` and `terminal_reason`, permanently; later calls return the
same value.

1. **`SOLVED`** — an accepted `submit` has been recorded.
2. **`ACTION_LIMIT`** — `actions_used >= max_actions`.
3. **`REJECTION_LIMIT`** — `consecutive_rejections >= max_consecutive_rejections`.
4. **`NO_ACTION`** — `record_no_action()` was called since the last handled call.
5. **`MODEL_ERROR`** — `record_model_error()` was called.

`check_terminal` returns `None` if none of these holds.
`record_no_action` and `record_model_error` do not charge the budget.

## 10. Test obligations (black-box)

- **Each policy P1–P10** produces the specified `policy`/`reason`, leaves the
  board grid, depth and agent facts unchanged, charges the budget as specified,
  and appends one trace entry.
- **Priority:** a `place_number` with bad args on a given cell reports P3; a
  given cell that also conflicts reports P4; a call after the run is solved
  reports P1 and is not charged.
- **Budget:** after N calls, `budget_remaining == max_actions - N`. With
  `max_actions=3`, the third call's observation shows 0 and `check_terminal`
  then gives `ACTION_LIMIT`.
- **Streak:** 5 consecutive rejections give `REJECTION_LIMIT`; 4 rejections
  then an acceptance resets the count to 0.
- **Ordering:** a final accepted `submit` on the last budgeted action gives
  `SOLVED`, not `ACTION_LIMIT`.
- **Other terminal causes:** `record_no_action` gives `NO_ACTION`, and
  `record_model_error` gives `MODEL_ERROR`. Terminal status cannot be changed
  once set.
- **Trace contents:** steps are 1-based and contiguous, and each entry records
  the args, outcome and `board_depth`.
- `Observation.to_json()` is valid JSON containing `budget_remaining`.
