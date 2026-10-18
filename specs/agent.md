# Functional Specification — `sudoku_agent.agent` (ReAct loop), `prompts`, `llm`, `cli`

Status: **Approved v2 (orchestrator review 2026-10-17; v2 amends §5 strategy and §8 puzzles)**
Parent: `specs/architecture.md` §4.8–4.9, §5, §6. Uses `controller`
(`specs/controller.md`) and `tools` (`specs/tools.md`).

## 1. Purpose

This module runs one bounded ReAct episode as a LangGraph `StateGraph` that
mirrors the design diagram. In each turn:

1. the model selects one typed tool call;
2. the controller validates it;
3. the tool executes it;
4. the observation returns to the model; and
5. the "continue?" node decides whether to loop or end.

## 2. Graph

```
START → llm → controller ──(terminal already set)──→ END
                  │
                  ▼
                tool → continue? ──(terminal)──→ END
                           │
                           └──(otherwise)──→ llm
```

**Graph state** (a `TypedDict`; this is all LangGraph checkpoints):

| Field | Meaning |
|---|---|
| `messages` | The full conversation (system prompt excluded), with the `add_messages` reducer. |
| `pending` | The current turn's `Approval`, or `None`. |

The `Session` and `Controller` are **not** in graph state. They are passed to the
nodes through `config["configurable"]["session"]` and `["controller"]`, so
nothing the model produces can reach them except through `Controller` methods.

### 2.1 Node `llm`

1. Build the model input (§3) and call `model.invoke(input)`. The model is bound
   with `tool_definitions()` and `tool_choice="required"`, at temperature 0.
2. If the call raises, retry **once** after 2 s. If the retry also fails, call
   `controller.record_model_error(e)` and route to `continue?`, which then ends
   with `MODEL_ERROR`.
3. Append the returned `AIMessage` to `messages`.

### 2.2 Node `controller`

Let `calls = ai.tool_calls + ai.invalid_tool_calls`, in the order received.
(`invalid_tool_calls` are calls whose arguments could not be parsed as JSON.)

1. If `calls` is empty: call `controller.record_no_action()`, then go to `continue?`.
2. For the **first** call: `controller.validate(name, args)`. For an invalid
   call, the raw argument string is passed and fails P3.
   - If the result is an `Approval`, store it in `pending`.
   - If it is a rejection `Observation`, append a `ToolMessage` for it.
3. For each **further** call: `controller.reject_extra_call(...)` and append its
   `ToolMessage` (P10).
4. If a terminal status is already set at this point, route to END. Otherwise
   route to `tool`.

Every tool call id in the `AIMessage` receives exactly one `ToolMessage`. This
keeps the conversation valid for the chat API.

### 2.3 Node `tool`

If `pending` is set: `obs = controller.execute(pending)`, append
`ToolMessage(content=obs.to_json(), tool_call_id=…)`, then clear `pending`.
If `pending` is not set (the first call was rejected), do nothing.

### 2.4 Node `continue?`

Calls `controller.check_terminal()`. Routes to END if a terminal status is set,
otherwise back to `llm`.

### 2.5 Backstop

The graph is compiled and run with
`recursion_limit = 4 * config.max_actions + 10`. The controller's limits
therefore always fire first; a `GraphRecursionError` would indicate a bug.

## 3. Model input and context window

The model input for each `llm` call is built fresh, in this order:

1. **`SystemMessage`**: the system prompt (§5).
2. **Recent history**: the last `config.history_window` (default 12) complete
   turns from `messages`. A turn is one `AIMessage` together with all of its
   `ToolMessage`s; the window never splits a turn.
3. **`HumanMessage` status**, regenerated every turn:
   ```
   Current board (empty: N, budget remaining: B, undo depth: D, KB facts: F):
   <board.render()>
   ```
   On the first turn this message is the whole task statement, preceded by
   `"Solve this Sudoku."`

Rationale (decision A1): with a 500-action budget, the full history would grow
to tens of thousands of tokens, making each call slower and pushing against the
model's context window. The status message gives the model the current board
each turn **without charging an action**. The complete history is still kept in
`messages` and in the controller trace. Read tools remain available for
targeted views.

## 4. Public interface

```python
@dataclass(frozen=True)
class RunResult:
    status: TerminalStatus
    reason: str
    actions_used: int
    trace: tuple[TraceEntry, ...]
    final_grid: tuple[tuple[int, ...], ...]
    solved: bool                       # status is SOLVED

def build_graph() -> CompiledGraph
def run(puzzle: str, config: Config = Config(), model=None,
        on_step: Callable[[TraceEntry], None] | None = None) -> RunResult
```

- `model=None` means `llm.make_model(config)` is used. Tests pass a scripted fake
  model instead (§7).
- `on_step` is called after each trace entry is appended, for live CLI output.
- `run` never raises for model or tool problems; they become terminal statuses.
  It raises `ValueError` only for a malformed puzzle.

## 5. `prompts`

`prompts.SYSTEM_PROMPT` is a constant string, reviewed by the orchestrator, that
must state:

1. the Sudoku rules, and that givens cannot be changed;
2. the coordinate conventions (rows, columns and boxes 1–9; `v{r}{c}{d}`
   variables; formula syntax with one example);
3. that every reply must be exactly **one** tool call, that each costs 1 action,
   and that the budget is shown in every observation;
4. the recommended strategy, in this order:
   - place any `forced` cells reported by the last placement;
   - use `get_candidates` and place cells that have a single candidate;
   - when no single-candidate cell remains, pick the empty cell with the fewest
     candidates and call `kb_infer_cell` on it; place the proven digit if one is
     returned; use `kb_ask` for specific questions, and `kb_tell` to record
     helper facts;
   - logic calls on the hardest puzzles can take a while, so prefer cheap tools first;
   - if a placement reports `dead` cells or `kb_consistent: false`, `undo`
     immediately;
   - when `empty` is 0, `submit`;
5. that only the application decides success, through `submit`.

`prompts.status_message(session, controller) -> HumanMessage` builds the §3
status message.

## 6. `llm` and `cli`

- `llm.make_model(config)` returns
  `ChatOpenAI(base_url=GOLEM_BASE_URL, api_key=GOLEM_API_KEY, model=config.model_name, temperature=0, timeout=120)`.
  - It reads `.env` from the current working directory if present (via
    `python-dotenv`), without overriding variables already set.
  - It raises a clear `RuntimeError` if `GOLEM_API_KEY` is missing.
- `python -m sudoku_agent PUZZLE_FILE [--model NAME] [--max-actions N] [--history N] [--quiet] [--trace-out FILE.jsonl]`
  - It prints one line per step (step, tool, args, accepted/policy, message,
    budget) unless `--quiet` is given, then prints the final board, status,
    reason and actions used.
  - `--trace-out` writes the trace as JSON lines.
  - The exit code is 0 if solved and 1 otherwise.

## 7. Scripted fake model (test support, `tests/fakes.py`)

`ScriptedModel(responses: list[AIMessage | Exception])`:

- `bind_tools(...)` returns itself and records the tools and `tool_choice` it was given.
- Each `invoke(messages)` records the input and returns (or raises) the next
  scripted item.
- When the script is exhausted, it returns an `AIMessage` with no tool calls.

## 8. Puzzles

- **Puzzle files** (`*.txt`) contain the puzzle as 9 lines, or 1 line of 81
  characters, using `0` or `.` for empty cells.
  - They may **optionally** contain a blank line followed by the solution, in the
    same format.
  - Lines starting with `#` are comments.
  - Puzzles from elsewhere, such as instructor-provided boards, can be used
    as-is without a solution. Success is always decided by `submit`'s validator.
- **Bundled puzzles** used by the tests, with sources cited in `puzzles/README.md`.
  Each one is verified, by an exhaustive search, to have exactly one solution,
  and stores that solution:

  | File | Source | Givens | Technique needed |
  |---|---|---|---|
  | `puzzles/easy.txt` | Wikipedia "Sudoku" example | 30 | single-candidate logic only |
  | `puzzles/hard.txt` | Peter Norvig, "Solving Every Sudoku Puzzle" (hard1) | 17 | beyond single candidates |
  | `puzzles/expert.txt` | Arto Inkala (2012) | 21 | beyond single candidates; KB worst case |

- `puzzles.load(path) -> Puzzle(name, puzzle: str, solution: str | None)`
  parses this format. `name` is the file's stem (`"easy"` for `easy.txt`).
  `puzzle` and `solution` are normalized to exactly 81 characters, using `0` for
  empty cells. It raises `ValueError` on malformed content (a wrong length, a bad
  character, or more than one blank-line-separated section after the puzzle).

## 9. Test obligations (black-box, fake model, no network)

- **Happy path:** a scripted sequence that places every missing digit of the
  easy puzzle and then submits ends `SOLVED` with `actions_used == empties + 1`.
- **Observations reach the model:** the second `invoke` input contains a
  `ToolMessage` with the first call's observation JSON, and a status message
  with the updated board.
- **Text cannot win:** an `AIMessage` with no tool calls whose content says
  "SOLVED" ends `NO_ACTION`, not solved.
- **Rejection limit:** 5 scripted invalid placements end `REJECTION_LIMIT`, with
  the board unchanged.
- **Action limit:** with `max_actions=3` and only reads, the run ends `ACTION_LIMIT` after 3 actions.
- **Extra calls:** a turn with two tool calls executes only the first; the second
  gets P10; both are charged; every tool call id gets one `ToolMessage`.
- **Invalid JSON arguments** become a P3 rejection, not a crash.
- **Model errors:** one exception followed by a valid response recovers (retry);
  two consecutive exceptions end `MODEL_ERROR`.
- **Binding:** `tool_choice="required"` and all 13 tools are bound.
- **History window:** with `history_window=2`, the model input holds the system
  message, at most 2 complete turns, and the status message, and never an
  orphaned `ToolMessage`.
- **Trace:** `RunResult.trace` matches `controller.trace` and has one entry per tool call.
