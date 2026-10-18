# ReAct Sudoku Agent

A bounded ReAct agent, built as a LangGraph loop, that solves 9×9 Sudoku puzzles. A language model chooses one
typed tool call per turn. The application owns the puzzle, a propositional knowledge base, the
action-observation trace, the controller policies, the action budget and the terminal status. Model text
can never change state or declare success; only the `submit` validator can.

**Author:** Suzanne Szabo — Utah Tech University, AI (U0-HW-08), Fall 2026

## How it works

```
START → llm → controller ──(terminal)──→ END
                  │
                  ▼
                tool → continue? ──(terminal)──→ END
                           │
                           └──(otherwise)──→ llm
```

- **`llm`** — The model sees the system prompt, its last 12 turns and a status message rebuilt every turn. The status
  message holds the board, the forced placements and every empty cell's candidates. Tool calls are forced
  (`tool_choice="required"`).
- **`controller`** — Validates the request with read-only checks (policies P1–P10) and charges the budget.
- **`tool`** — Runs the approved call. Only tools change the board or the knowledge base.
- **`continue?`** — Applies the ordered terminal checks: `SOLVED`, `ACTION_LIMIT`, `REJECTION_LIMIT`, `NO_ACTION`, `MODEL_ERROR`.

The model's strategy is cheapest tools first: place forced cells, and only when none remain, ask the logic
engine (`kb_infer_cell`). The engine is the course's `proplogic` package, used unmodified, which proves digits by
DPLL refutation.

## Repository layout

| Path | Contents |
|---|---|
| `specs/` | Architecture and per-module functional specifications, written before the code; revision notes are inline |
| `sudoku_agent/` | Implementation: `board`, `validation`, `logic`, `tools`, `controller`, `session`, `agent`, `prompts`, `llm`, `puzzles`, `cli` |
| `proplogic/` | Vendored course propositional-logic package (unmodified; see `proplogic/VENDORED.md`) |
| `tests/` | Black-box tests derived from the specs; `test_whitebox.py` holds white-box tests written afterward |
| `puzzles/` | Verified easy, hard and expert puzzles, with sources in `puzzles/README.md` |
| `docs/` | Process log, live-run logs and traces (`docs/runs/`), Golem tool-calling check |
| `scripts/` | Diagnostics: `check_golem.py` (tool-calling support), `check_latency.py` (model latency) |

## Setup

Requires Python 3.10 or newer.

```sh
python3 -m venv .venv
source .venv/bin/activate          # run this in every new terminal
pip install -r requirements.txt
```

### Model access (needed only for live runs, not for the tests)

The agent uses the school's OpenAI-compatible Golem gateway, which is reachable over Tailscale.

```sh
cp .env.example .env               # then put your key after GOLEM_API_KEY=
```

`.env` is git-ignored and must never be committed. The variables are `GOLEM_API_KEY`, `GOLEM_BASE_URL` (default
`http://golem:4000/v1`) and `SUDOKU_MODEL` (default `Gemma-4-26B-A4B`).

## Running the agent

```sh
python -m sudoku_agent puzzles/easy.txt
python -m sudoku_agent puzzles/expert.txt --trace-out run.jsonl
python -m sudoku_agent my_board.txt --model Qwen3.8-27B --max-actions 200 --quiet
```

Options: `--model NAME`, `--max-actions N` (default 500), `--history N` (turns shown to the model, default 12),
`--quiet`, `--trace-out FILE.jsonl`. The run prints one line per step, then the final board, status and reason.
The exit code is 0 only when the puzzle is solved.

A puzzle file is 9 lines, or one 81-character line, with `.` or `0` for empty cells. A blank line followed by a
solution is optional, and `#` starts a comment.

## Running the tests

No network or API key is needed. The agent-loop tests use a scripted fake model.

```sh
python -m pytest -q                       # everything (about 3 minutes, includes slow performance tests)
python -m pytest -q -m "not slow"         # skip the timing tests (about 2 minutes)
python -m pytest -q -m whitebox           # only the white-box tests
python -m pytest -q -m "not whitebox"     # only the spec-derived black-box tests (plus proplogic's own)
python -m pytest -q -m "not slow" --cov=sudoku_agent --cov-branch --cov-report=term-missing
```

## Results (live runs, Gemma-4-26B-A4B, 2026-10-18)

| Puzzle | Status | Actions | Minimum | Logic-engine proofs | Rejections |
|---|---|---|---|---|---|
| easy (Wikipedia) | SOLVED | 52 | 52 | 0 | 0 |
| hard (Norvig, 17 givens) | SOLVED | 72 | 65 | 7 | 0 |
| expert (Inkala 2012) | SOLVED | 71 | 61 | 10 | 0 |

The full logs and traces are in `docs/runs/`. How the design evolved, including the coding-agent handoff and the
defects found by testing, is recorded in `docs/process-log.md`.
