# Architecture Specification — ReAct Sudoku Agent

Status: **Approved v1 (orchestrator review 2026-10-17)**
Owner (design authority): Suzanne Szabo
Implementation: coding agent (Claude), working from this document and the per-module specs.

This document fixes the module boundaries, owned state, public interfaces,
dependencies, and allowed interactions of the system. Each module gets its own
detailed functional specification in `specs/` before its code is written.
Tests are derived from those specifications.

---

## 1. Goals and design principles

1. **The application owns all state.** The language model only *requests* typed
   tool calls. It never holds or mutates the board, the knowledge base, the
   trace, the action budget, or the terminal status.
2. **Validate before mutate.** Every request is validated before anything
   changes. A rejected request leaves the board and knowledge base exactly as
   they were.
3. **Success is established only by the application.** A puzzle counts as solved
   only when the `submit` tool's independent validator accepts the board. Model
   text cannot end the run or declare success.
4. **Efficiency by design.** Cheap observations carry the information the agent
   most often needs: the remaining budget, the candidate digits, and the cells
   that a placement has just forced. Expensive reasoning (SAT entailment) is
   reserved for cases where it is needed.
5. **Simple core, no auto-solving.** Helper observations *report* consequences.
   They never place digits on the agent's behalf.

## 2. Conventions shared by all modules

| Item | Convention |
|---|---|
| Coordinates | Rows and columns are numbered **1–9**. Row 1 is the top row and column 1 is the left column. |
| Boxes | Boxes are numbered **1–9** in row-major order: box 1 is the top-left, box 3 the top-right, box 9 the bottom-right. Box `b` covers rows `3*((b-1)//3)+1 …+2` and columns `3*((b-1)%3)+1 …+2`. |
| Digits | Integers 1–9. An empty cell is represented as `0` internally and shown as `.` in text views. |
| Puzzle input | An 81-character string in row-major order, using digits `1–9` for givens and `0` or `.` for empty cells. |
| Propositional variables | `v{r}{c}{d}` means "the cell at row r, column c holds digit d" (for example `v537` means r5c3 = 7). The `v` prefix plus three digits is reserved for this meaning. |
| Formula syntax | The syntax of the vendored `proplogic` package: `~ ! & \| -> <->`, the words `NOT AND OR IMPLIES IFF`, and parentheses. |

## 3. Module overview

```
sudoku_agent/
  board.py        Board: puzzle state, placement, undo, views, candidates
  validation.py   Independent solution validator (pure function)
  logic.py        SudokuKB: wraps proplogic for Sudoku; rule layer + agent facts
  tools.py        Typed tool schemas (Pydantic) + tool executors -> Observation
  controller.py   Policies, action budget, trace, ordered terminal checks
  session.py      Session: composition root holding one puzzle run's state
  agent.py        LangGraph StateGraph: llm -> controller -> tool -> continue?
  prompts.py      System prompt and initial user message construction
  llm.py          Chat-model factory (provider-agnostic, config-driven)
  puzzles.py      Puzzle-file loader (solution optional)
  cli.py          Command-line entry point: run one puzzle, print the trace
proplogic/        Vendored course package (unmodified): parser, CNF, KB, DPLL
                  (top-level so its own tests import it unchanged)
puzzles/          Bundled verified puzzles (easy / hard / expert) + sources
specs/            This document and one functional spec per module
tests/            Black-box spec-derived tests (+ marked white-box tests)
docs/             Diagram, process log, report source
```

## 4. Modules: responsibility, owned state, interface, dependencies

### 4.1 `board` — Sudoku board

- **Responsibility:** Hold one puzzle's grid, enforce Sudoku invariants on
  placement, keep the undo stack, and provide read views and candidates.
- **Owned state:** the immutable set of given cells; a 9×9 grid of current
  digits; a LIFO stack of accepted placements.
- **Public interface (summary):**
  - `Board.from_string(puzzle: str) -> Board`
  - `cell(r, c) -> int`, `row(r) -> list[int]`, `col(c) -> list[int]`,
    `box(b) -> list[int]`, `grid() -> tuple[tuple[int, ...], ...]`, `render() -> str`
  - `is_given(r, c) -> bool`
  - `candidates(r, c) -> list[int]`: digits not used in the cell's row, column
    or box; `[]` for a filled cell
  - `place(r, c, d) -> PlaceResult(accepted, reason, forced_cells)`
  - `undo() -> UndoResult(accepted, reason, removed)`
  - `depth -> int`: the number of placements on the undo stack
  - `is_complete() -> bool`
- **Invariants:** given cells never change; a rejected `place` or `undo` mutates
  nothing; the grid never contains a duplicate digit in a row, column or box.
- **Depends on:** nothing.

### 4.2 `validation` — independent solution validator

- **Responsibility:** Decide whether a final grid solves the original puzzle.
  It is written separately from `board` so that success never relies on the
  board's own bookkeeping.
- **Owned state:** none (a pure function).
- **Interface:** `validate_solution(original_puzzle: str, grid) -> ValidationResult(valid, reasons)`.
  The checks: the grid is 9×9 with digits 1–9 only, every given is preserved,
  and every row, column and box is a permutation of 1–9.
- **Depends on:** nothing.

### 4.3 `proplogic` — vendored propositional logic package (repo root)

- **Responsibility:** Formula parsing, CNF conversion, a clause store, and DPLL
  entailment and consistency checks.
- **Origin:** Copied without modification from the course-provided U0-HW-07
  starter. Its own tests are kept and run as part of the suite.
- **Depends on:** the Python standard library only.

### 4.4 `logic` — Sudoku knowledge base (`SudokuKB`)

- **Responsibility:** Turn the current board into propositional rules, store
  facts and rules told by the agent, answer three-valued queries, and keep
  agent facts in sync with undo.
- **Owned state:**
  - **Rule layer:** clauses derived from a board snapshot. It covers only the
    empty cells and their candidate digits, plus explicit negative facts for
    eliminated candidates. It is rebuilt whenever the board changes and can
    never be removed by the agent.
  - **Agent layer:** an ordered list of `(depth, formula)` entries recording
    what the agent told the KB and the board depth at which it was told.
- **Public interface (summary):**
  - `rebuild(board)`: regenerate the rule layer from the board
  - `tell(formula) -> TellResult(accepted, reason)`: rejected if the formula
    does not parse or would make the KB inconsistent; on rejection nothing changes
  - `ask(formula) -> Answer` ∈ {`ENTAILED`, `CONTRADICTED`, `UNRESOLVED`}
    - `ENTAILED` when KB ⊨ q; `CONTRADICTED` when KB ⊨ ¬q; otherwise `UNRESOLVED`
  - `clear_agent_facts()`: empties the agent layer only
  - `rollback_to(depth)`: drops agent entries told at a depth greater than `depth`
- **Depends on:** `proplogic`, and reads `board` (read-only).

### 4.5 `tools` — typed tool interface

- **Responsibility:** Define the only actions the model may request, as Pydantic
  argument schemas, and execute an *already approved* request against the
  session, returning an `Observation`.
- **Owned state:** none.
- **Tools:**

| Tool | Arguments | Effect |
|---|---|---|
| `read_board` | — | Returns the rendered 9×9 board. Read-only. |
| `read_cell` | `row, col` | Returns the cell's digit, whether it is a given, and its candidates. Read-only. |
| `read_row` / `read_col` | `row` / `col` | Returns that row or column. Read-only. |
| `read_box` | `box` | Returns that box. Read-only. |
| `place_number` | `row, col, digit` | Places a digit; the observation lists newly forced cells. |
| `undo` | — | Undoes the last placement and rolls back agent KB facts told since it. |
| `kb_tell` | `formula` | Adds a fact or rule to the agent layer. |
| `kb_ask` | `formula` | Returns ENTAILED, CONTRADICTED or UNRESOLVED. Read-only. |
| `kb_infer_cell` | `row, col` | Per-cell sweep: the proven digit, or which candidates are ruled out. Read-only. |
| `kb_clear` | — | Clears the agent layer only. |
| `submit` | — | Runs `validation`; accepted means solved. |

- **Observation shape:** `{tool, accepted, message, data, budget_remaining}`,
  serialized to JSON for the model.
- **Depends on:** `board`, `logic`, `validation`, `session`.

### 4.6 `controller` — policies, budget, trace, terminal status

- **Responsibility:** The single gatekeeper between the model and the tools.
- **Owned state:** `actions_used`, `consecutive_rejections`, the append-only
  `trace`, and `terminal_status` with its reason.
- **Public interface (summary):**
  - `validate(tool_name, raw_args) -> Approval | Observation`: applies the
    policies using read-only checks; returns an approval or a rejection
  - `execute(approval) -> Observation`: runs the approved call through `tools`
  - `handle(tool_name, raw_args)`: `validate` followed by `execute`
  - `reject_extra_call(...)`: the P10 rejection for extra calls in one turn
  - Every handled call updates the counters and appends one trace entry
  - (Full detail: `specs/controller.md`)
  - `record_no_action()`: marks a model response that contained no tool call
  - `check_terminal() -> TerminalStatus | None`: applies the ordered checks in §6
- **Policies (each producing a rejection without any mutation):**
  1. **P1** — Reject any call once a terminal status is set.
  2. **P2** — Reject unknown tool names.
  3. **P3** — Reject arguments that fail the schema (wrong type, out of range,
     missing or extra fields).
  4. **P4** — Reject a placement in a given cell (clue protection).
  5. **P5** — Reject a placement in a filled cell (the agent must undo first).
  6. **P6** — Reject a placement that duplicates a digit in the row, column or box.
  7. **P7** — Reject `undo` when the undo stack is empty.
  8. **P8** — Reject a KB request (`kb_tell`/`kb_ask`) whose formula is malformed,
     too long or uses an invalid cell variable; a `kb_tell` that would make the KB
     inconsistent; or any KB request while the KB is inconsistent.
  9. **P9** — Reject a `submit` that fails validation (an incomplete or invalid board).
  10. **P10** — One tool call per model turn. If a response contains several,
      only the first is executed; each extra call gets a rejection observation.
- **Budget:** Every tool call the model makes, accepted or rejected, read or
  write, costs 1 action. The default limit is **500**, and it is configurable.
- **Depends on:** `tools`, `session`.

### 4.7 `session` — composition root for one run

- **Responsibility:** Create and hold one run's `Board`, `SudokuKB`, original
  puzzle string, configuration, and controller state.
- **Interface:** `Session.new(puzzle: str, config: Config) -> Session`, with
  read-only attributes `board: Board`, `kb: SudokuKB` (built from that board),
  `original_puzzle: str` (exactly as passed in) and `config: Config`. Controller
  state lives in the `Controller` (§4.6), which is constructed with the session.
  A malformed puzzle raises `ValueError`.
- **Depends on:** `board`, `logic`.

### 4.8 `agent` — LangGraph ReAct loop

- **Responsibility:** Run the bounded loop shown in the design diagram.
- **Graph state (LangGraph):** `messages` (the conversation) and `pending`
  (the approved call for the current turn). The `Session` and `Controller` are
  passed to the nodes through LangGraph's run config, never through graph
  state, so model output cannot reach them except through controller methods.
  (Full detail: `specs/agent.md`)
- **Nodes and edges:**

```
START -> llm -> controller --(terminal already set)--> END
                    |
                    v
                  tool -> continue? --(terminal)--> END
                              |
                              +--(otherwise)--> llm
```

  - `llm`: calls the chat model with the tools bound and **tool choice forced**
    (the model must answer with a tool call). Model errors are caught and
    recorded.
  - `controller`: applies the policies to the requested call. A model response
    with no tool call is recorded as `NO_ACTION`.
  - `tool`: executes the approved call and appends the observation as a
    `ToolMessage`.
  - `continue?`: runs `check_terminal()` and routes to END or back to `llm`.
- **Interface:** `run(puzzle: str, config: Config, model=None) -> RunResult(status, reason, trace, final_grid, actions_used)`.
  Passing a scripted fake `model` makes the loop deterministic for tests.
- **Backstop:** the LangGraph `recursion_limit` is set above the worst-case
  number of node steps for the action budget, so the controller's limit always
  triggers first.
- **Depends on:** `controller`, `session`, `tools` (schemas only), `prompts`, `llm`.

### 4.9 `prompts`, `llm`, `cli`

- `prompts`: builds the system prompt (the rules, the tool strategy, and the
  coordinate conventions) and the first user message containing the initial
  board. Each turn the model also receives a regenerated status message (the
  current board, budget, undo depth and KB fact count) together with only the
  last 12 complete turns of history (D13). The status message costs no action.
- `llm`: `make_model(config)` returns a LangChain `ChatOpenAI` pointed at the school's
  OpenAI-compatible Golem gateway (`GOLEM_BASE_URL`, default `http://golem:4000/v1`,
  reachable over Tailscale). The model name comes from `SUDOKU_MODEL`. The key
  (`GOLEM_API_KEY`) is read from the environment or an ignored `.env` file and never
  committed; `.env.example` documents the variables.
- `cli`: `python -m sudoku_agent puzzles/easy1.txt [--max-actions N] [--verbose]`.

## 5. Allowed interactions

| From → To | Allowed? | Notes |
|---|---|---|
| model → anything | ✖ | The model only produces messages; the `agent` node interprets them. |
| `agent` → `controller` | ✔ | The only route by which a request reaches state. |
| `agent` → `board` / `logic` | ✖ | The graph never touches state directly. |
| `controller` → `tools` | ✔ | Only after the policy checks pass. |
| `tools` → `board`, `logic`, `validation` | ✔ | The only code that calls mutating methods. |
| `logic` → `board` | read-only | Builds the rule layer from a snapshot. |
| `board`, `validation`, `proplogic` → anything | ✖ | Leaf modules. |
| tests → any public interface | ✔ | Black-box tests use only the public interfaces in the specs. |

**What the model sees:** the system prompt, the initial board message, its own
earlier tool calls, and the observations returned for them. Nothing else.

## 6. Terminal conditions (checked in this order)

`check_terminal()` runs after every step. The first condition that holds sets
the terminal status:

1. **`SOLVED`** — the last action was a `submit` accepted by `validation`.
2. **`ACTION_LIMIT`** — `actions_used >= max_actions` (default 500).
3. **`REJECTION_LIMIT`** — `consecutive_rejections >= max_consecutive_rejections` (default 5).
4. **`NO_ACTION`** — the model's last response contained no tool call.
5. **`MODEL_ERROR`** — the model call raised an exception.

Once a terminal status is set it is final (policy P1). It is reported with a
human-readable reason in `RunResult.reason`. (v3: the earlier "and in the final trace
 entry" was dropped. `TraceEntry` records tool calls only, and `NO_ACTION`/`MODEL_ERROR`
 have no call to attach a reason to. The coding agent found this.)

## 7. Undo and knowledge-base synchronisation

- `undo` removes the most recent accepted placement (LIFO). Earlier placements
  can only be undone by undoing everything placed after them.
- After an accepted placement or undo, `tools` calls `SudokuKB.rebuild(board)`.
  After an undo it also calls `SudokuKB.rollback_to(board.depth)`, which drops
  agent facts told after the undone placement. Agent facts told earlier are
  kept, so correct reasoning survives the undo.
- Because the rule layer comes from the board, the KB never contradicts the
  board's accepted state. An inconsistent KB can arise only from the agent's
  own facts, and `tell` rejects those (P8).

## 8. Trace

Each trace entry records: `step`, `tool`, `args`, `accepted`, `policy`
(the rejecting policy id, if any), `message`, `budget_remaining`, and
`board_depth`. The trace is append-only, owned by the controller, and returned
in `RunResult`.

## 9. Testing strategy (summary)

- **Black-box tests are written from the specs before implementation**, one
  file per module (`tests/test_board.py`, `test_validation.py`, `test_logic.py`,
  `test_tools.py`, `test_controller.py`, `test_agent_loop.py`).
- Loop tests use a **scripted fake chat model**, so no network or API key is needed.
- White-box tests are marked `@pytest.mark.whitebox` and only supplement the
  black-box tests.
- The vendored `proplogic` tests run unchanged.

## 10. Decision log

| # | Decision | Rationale |
|---|---|---|
| D1 | Reuse the course `proplogic` package unmodified, wrapped by `logic` | It is tested, matches the tell/ask/clear design, and keeps new code small. |
| D2 | The rule layer covers only empty cells and their candidates, rebuilt from the board | Benchmark: ~0.04–0.7 s per query versus ~2–22 s for the full 729-variable encoding. |
| D3 | Negative facts for eliminated candidates | Without them, queries about eliminated digits would wrongly return UNRESOLVED. |
| D4 | Three-valued `ask` (entailed, contradicted, unresolved) | Required by the assignment's sensor description. |
| D5 | `get_candidates` tool, and `place_number` reports newly forced cells | Exposes cascades cheaply without auto-placing digits. |
| D6 | Undo rolls back agent facts by checkpoint | Keeps the KB in sync with the board without discarding valid earlier work. |
| D7 | `kb_clear` clears agent facts only | The Sudoku rules are application-owned and protected. |
| D8 | Every tool call costs 1 action; limit 500 (raised from 200 by orchestrator review, 2026-10-17); 5 consecutive rejections end the run | Generous safety bound; efficiency is measured by actions used, not by the cap. |
| D9 | Placements that conflict with the row, column or box are rejected; non-conflicting wrong placements are allowed | Keeps undo and recovery meaningful while blocking obvious errors. |
| D10 | Rows, columns and boxes are numbered 1–9 | Matches how people read Sudoku and suits the `v{r}{c}{d}` names. |
| D11 | One tool call per turn | Matches the assignment's agent-environment loop. |
| D12 | The LLM is the school Golem gateway (OpenAI-compatible) via `ChatOpenAI`; model chosen by `SUDOKU_MODEL` | Provided by the course. `scripts/check_golem.py` verifies forced tool calling for each model before we rely on it. |
| D13 | The model sees a sliding window of the last 12 turns plus a per-turn status message with the current board | With 500 actions the full history would slow every call and strain the context window; the full trace is still kept by the application. |
| D14 | Cache proven KB answers, cleared on any KB change (from the Rover `LogicAgent`'s `proven_safe_tiles`) | Repeated questions cost no solver time. |
| D15 | `kb_infer_cell` tool: a per-cell sweep of all candidates (from Rover's `inferred_safe_tiles`), one cell per call | One action instead of up to 9 `kb_ask` calls; stops short of a whole-board sweep that would solve the puzzle for the model. |
| D16 | No timeouts on KB operations; generous performance targets (≤ 10 s per ask on easy/hard, ≤ 60 s on expert) | Orchestrator decision: let the model get every answer it needs. Keeps the vendored solver unchanged (option A over writing our own solver or using `pycosat`). |
| D17 | Bundled puzzles easy / hard / expert, each verified to have a unique solution; solutions optional in other puzzle files | Instructor boards can be dropped in without solutions. |
| D18 | *(v4)* The application hands the model ready-made board logic every turn: forced placements (single candidates and only-place-in-unit cells) and the candidates of every empty cell, fewest first. `get_candidates` is removed (12 tools), and the tool descriptions say when to use each tool | First live run: the model miscounted grid columns and wasted actions on `read_board`. Orchestrator decision: cheapest tools first, then the logic engine (`kb_infer_cell`) when nothing is forced. |
