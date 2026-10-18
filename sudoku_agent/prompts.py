"""System prompt and per-turn status messages.

Implements specs/agent.md §3 and §5 (architecture §4.9, D13). The status
message is regenerated every turn and costs no action.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from sudoku_agent.controller import Controller
from sudoku_agent.session import Session

SYSTEM_PROMPT = """\
You are solving a 9x9 Sudoku puzzle by calling tools.

RULES
- Fill every empty cell with a digit 1-9 so that each row, each column and each
  3x3 box contains every digit exactly once.
- The given digits of the puzzle can never be changed.

COORDINATES
- Rows are numbered 1-9 from top to bottom; columns 1-9 from left to right.
- Boxes are numbered 1-9 row by row: box 1 is top-left, box 3 top-right,
  box 9 bottom-right.
- In the board view, '.' is an empty cell.
- Knowledge-base variables are v{row}{col}{digit}: v537 means "row 5, column 3
  holds 7". Formulas use ~ (not), & (and), | (or), -> (implies), <-> (iff) and
  parentheses, for example: (v111 | v112) -> ~v121

HOW TO ACT
- Every reply must be exactly one tool call. Only the first call in a reply is
  executed; extra calls are rejected.
- Every tool call costs 1 action, whether it is accepted or rejected. The
  remaining budget is shown in every observation as budget_remaining.
- Several rejected calls in a row end the run, so read each observation.

STRATEGY (in this order)
1. If your last placement reported "forced" cells, place those digits next.
2. Use get_candidates and place any cell that has a single candidate.
3. When no single-candidate cell remains, pick the empty cell with the fewest
   candidates and call kb_infer_cell on it. If it returns a proven digit,
   place it. Use kb_ask for specific questions and kb_tell to record helper
   facts you have worked out.
4. Logic calls can take a while on the hardest puzzles, so prefer the cheap
   tools first.
5. If a placement reports "dead" cells or "kb_consistent": false, call undo
   immediately.
6. When "empty" is 0, call submit.

SUCCESS
Only the application decides whether the puzzle is solved, through submit.
Saying that the puzzle is solved does not count.
"""

_TASK_PREFIX = "Solve this Sudoku."


def status_message(session: Session, controller: Controller) -> HumanMessage:
    """The per-turn status message with the current board (agent §3, item 3)."""
    board = session.board
    header = (
        f"Current board (empty: {len(board.empty_cells())}, "
        f"budget remaining: {controller.budget_remaining}, "
        f"undo depth: {board.depth}, "
        f"KB facts: {len(session.kb.agent_facts())}):"
    )
    return HumanMessage(content=f"{header}\n{board.render()}")


def initial_message(session: Session, controller: Controller) -> HumanMessage:
    """The first turn's task statement: the status message preceded by the task."""
    return HumanMessage(content=f"{_TASK_PREFIX}\n{status_message(session, controller).content}")
