"""System prompt and per-turn status messages.

Implements specs/agent.md §3 and §5 (architecture §4.9, D13, D18). The status
message is regenerated every turn and costs no action.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from sudoku_agent.controller import Controller
from sudoku_agent.session import Session

SYSTEM_PROMPT = """\
You are solving a 9x9 Sudoku puzzle by calling tools, one tool call per reply.

RULES
- Fill every empty cell with a digit 1-9 so that each row, each column and each
  3x3 box contains every digit exactly once. Given digits never change.

WHAT YOU RECEIVE EVERY TURN (free, no action needed)
A status message with:
- the board ('.' = empty), the number of empty cells and your remaining budget;
- "Forced placements": cells whose digit is already certain, written r{row}c{col}={digit};
- "Empty cells": every empty cell with its possible digits, fewest first,
  written r{row}c{col}:{digits} (for example r1c4:26 means row 1, column 4 can be 2 or 6);
- a "Contradiction" line if some empty cell has no possible digit left.
Use these lists for coordinates; do not count positions in the board text.

EACH TURN, DO THE FIRST THING THAT APPLIES
1. If there is a Contradiction line, or your last placement reported "dead" cells
   or "kb_consistent": false, call undo.
2. If the board has no empty cells, call submit.
3. If a forced placement is listed, place one of them with place_number.
4. Otherwise call kb_infer_cell on the first cell of the Empty cells list. If it
   returns a digit, place it. If it does not, call kb_infer_cell on the next cell.

RULES OF THE GAME LOOP
- Every reply must be exactly one tool call; extra calls are rejected.
- Every tool call costs 1 action, accepted or rejected (see budget_remaining).
- Five rejected calls in a row end the run, so read each observation.
- Rows, columns and boxes are numbered 1-9 (box 1 top-left, box 9 bottom-right).
- kb_ask and kb_tell let you reason with your own formulas over variables
  v{row}{col}{digit} (v537 means row 5, column 3 holds 7), using ~ & | -> <->
  and parentheses, for example: (v111 | v112) -> ~v121. The read_* tools are
  rarely needed.

SUCCESS
Only the application decides whether the puzzle is solved, through submit.
Saying that the puzzle is solved does not count.
"""

_TASK_PREFIX = "Solve this Sudoku."


def status_message(session: Session, controller: Controller) -> HumanMessage:
    """The per-turn status message (agent §3, item 3; v4 adds the last lines).

    The board, forced placements and every empty cell's candidates, so the
    model never counts grid columns or asks for candidates cell by cell.
    """
    board = session.board
    header = (
        f"Current board (empty: {len(board.empty_cells())}, "
        f"budget remaining: {controller.budget_remaining}, "
        f"undo depth: {board.depth}, "
        f"KB facts: {len(session.kb.agent_facts())}):"
    )
    forced = " ".join(f"r{r}c{c}={d}" for r, c, d in board.forced_placements()) or "none"
    empties = sorted(
        ((r, c, board.candidates(r, c)) for r, c in board.empty_cells()),
        key=lambda item: (len(item[2]), item[0], item[1]),
    )
    cells = " ".join(f"r{r}c{c}:{''.join(map(str, digits)) or '-'}" for r, c, digits in empties) or "none"
    lines = [header, board.render(), f"Forced placements: {forced}",
             f"Empty cells (fewest candidates first): {cells}"]
    lines += [f"Contradiction: r{r}c{c} has no candidates; undo your last placement."
              for r, c, digits in empties if not digits]
    return HumanMessage(content="\n".join(lines))


def initial_message(session: Session, controller: Controller) -> HumanMessage:
    """The first turn's task statement: the status message preceded by the task."""
    return HumanMessage(content=f"{_TASK_PREFIX}\n{status_message(session, controller).content}")
