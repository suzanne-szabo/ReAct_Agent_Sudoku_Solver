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
  Without these, the tests would have had to guess, and the guesses would have locked in implementation details.
