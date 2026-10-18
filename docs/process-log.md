# Development Process Log

A running record of process events: spec revisions, findings from tests, and coding-agent handoffs.

## 2026-10-17 — Specification phase
- Architecture spec written from the orchestrator's hand-drawn diagram and the assignment text.
- Logic design reuses the course `proplogic` package (from U0-HW-07). A benchmark showed the full 729-variable
  encoding takes 2–22 s per query, so the rule layer was limited to remaining candidates (D2).
- Golem gateway tool-calling verified for all three models (`docs/golem-check-2026-10-17.txt`).
- Orchestrator review: action limit raised 200 → 500; `kb_infer_cell` and an answer cache adopted from the Rover
  `LogicAgent`; a benchmark found the expert puzzle exceeds the 3 s query target, so option A was chosen: keep `proplogic`,
  use no timeouts, and relax the targets (D16).

## 2026-10-18 — Test-derivation phase
- Writing black-box tests from the specs exposed three underspecified interfaces. The specs were amended
  before the tests were committed:
  1. `Session` attribute names (`board`, `kb`, `original_puzzle`, `config`) — architecture §4.7.
  2. `puzzles.load` output: `name` is the file stem, and the puzzle and solution are normalized to 81 characters with `0` for empty cells — agent §8.
  3. `.env` lookup location: the current working directory, never overriding existing variables — agent §6.
  4. The forced-cell format in `place_number` messages (`r{R}c{C}={D}`) — tools §4.1 — was only an example; it is now required.
  Without these, the tests would have had to guess, and the guesses would have locked in implementation details.

## 2026-10-18 — Coding-agent implementation
- A fresh coding agent (no access to the design conversation) received only `specs/`, `tests/`, `proplogic/` and
  `puzzles/`, and was instructed not to edit them. It implemented `sudoku_agent/` (13 modules, ~1,900 lines).
- Its result was **320 passed, 1 failed**. It left the failure in place and reported two spec defects:
  1. `test_extra_calls_rejected_and_every_call_answered` expects trace order `[first call, P10]`, but
     agent §2.2 as written rejected extra calls *before* the first call executed, giving `[P10, first call]`.
     **Resolution (reviewer):** the spec was wrong. Trace order should follow call order. agent §2.2–2.3 were
     amended so extra calls are rejected after the first call executes; `agent.py` was changed to match, and the
     test was not changed.
  2. Architecture §6 promised the terminal reason "in the final trace entry", which the trace model cannot
     represent. **Resolution:** the spec was amended; the reason is reported in `RunResult.reason`.
- The reviewer checked the module boundaries by searching the code: only `tools` calls state-changing methods; the graph reaches state only
  through `Controller`; `validation` does not import `board`; `proplogic` is unmodified; no other solver is used.
