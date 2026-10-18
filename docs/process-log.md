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

## 2026-10-18 — First live runs against Golem
- First run (Qwen3.8-27B, easy): step 1 `read_board` was wasted (the board is already in the status message); step 2 took
  over a minute and tried to place in a given cell, r1c5 (the model miscounted columns). The controller rejected it (P4) with no
  state change.
- `scripts/check_latency.py` (the agent's real first turn, three models, thinking on/off): Gemma-4-26B-A4B took 0.6–1.9 s and
  chose `get_candidates(1,3)`; Qwen3.8-27B took 7–10 s and chose `read_board`; Qwen3.8-Flash-Next was erratic (10 s to 371 s).
  No model returned hidden reasoning, so the minute-long step was most likely gateway load.
- Defect found: a call waited 371 s despite the 120 s timeout because LangChain's client added 2 hidden retries.
  Fixed (`max_retries=0`); spec agent §6 amended and the test updated first.

## 2026-10-18 — Revision v4: the application hands the model ready-made board logic
- Motivation: the first live run showed coordinate miscounting and wasted `read_board` calls. A review of the tool surface
  found `get_candidates` duplicated `read_cell`, `read_board` duplicated the status message, and the tool descriptions
  never said *when* to use each tool.
- Orchestrator decision: cheapest tools first, then the logic engine. The status message now lists forced placements
  (single candidates and only-place-in-unit cells) and every empty cell's candidates; the KB is used via `kb_infer_cell`
  when nothing is forced. `get_candidates` is removed (12 tools). Specs: board §4.3a, tools §2, agent §3 and §5, architecture D18.
- The specs and tests were updated first; 14 tests failed against the v3 code, as expected, before implementation.

## 2026-10-18 — First v4 live run
- Easy puzzle, Gemma-4-26B-A4B: **SOLVED in 52 actions** (the minimum: 51 placements plus submit), with 0 rejections and 0 reads
  (`docs/runs/2026-10-18_easy_gemma_v4.txt`). The model followed the `Forced:` cascade in each observation.
  Compared with the first v3 run (Qwen): a wasted `read_board`, then a P4 rejection by step 2.
- Default model changed to Gemma (D19); the test was updated before the code.
- Hard puzzle (Norvig hard1, 17 givens), Gemma: **SOLVED in 72 actions**: 64 placements, 7 `kb_infer_cell`, 1 submit,
  with 0 rejections, 0 reads and 0 undos (`docs/runs/2026-10-18_hard_gemma_v4.txt` and `.jsonl`). Whenever forced placements ran
  out, the model called `kb_infer_cell` as the v4 prompt directs; all 7 calls proved a digit and started new cascades.
- Expert puzzle (Inkala 2012), Gemma: **SOLVED in 71 actions**: 60 placements, 10 `kb_infer_cell`, 1 submit, with 0 rejections
  (`docs/runs/2026-10-18_expert_gemma_v4.txt` and `.jsonl`). Nothing was forced at the start, so the run opened with the logic engine;
  all 10 proofs were correct and each started a new cascade of forced placements.
- Summary for v4 + Gemma: 3/3 bundled puzzles solved, 0 rejections and 0 undos overall; actions above the minimum equal the number of
  logic-engine proofs (easy +0, hard +7, expert +10).
