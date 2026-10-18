"""Command-line entry point: run one puzzle and print the trace.

Implements specs/agent.md §6:

    python -m sudoku_agent PUZZLE_FILE [--model NAME] [--max-actions N]
                           [--history N] [--quiet] [--trace-out FILE.jsonl]

The exit code is 0 if the puzzle was solved and 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from sudoku_agent.agent import RunResult, run
from sudoku_agent.board import Board
from sudoku_agent.controller import Config, TraceEntry
from sudoku_agent.llm import default_model_name
from sudoku_agent.puzzles import load


def _parser() -> argparse.ArgumentParser:
    defaults = Config()
    parser = argparse.ArgumentParser(
        prog="python -m sudoku_agent",
        description="Solve one Sudoku puzzle with the bounded ReAct agent.",
    )
    parser.add_argument("puzzle_file", type=Path, metavar="PUZZLE_FILE",
                        help="puzzle file (9 lines or one 81-character line; '.' or '0' = empty)")
    parser.add_argument("--model", metavar="NAME",
                        help=f"model name (default: $SUDOKU_MODEL, else {defaults.model_name})")
    parser.add_argument("--max-actions", type=int, metavar="N", default=defaults.max_actions,
                        help=f"action budget (default: {defaults.max_actions})")
    parser.add_argument("--history", type=int, metavar="N", default=defaults.history_window,
                        help=f"number of recent turns shown to the model (default: {defaults.history_window})")
    parser.add_argument("--quiet", action="store_true", help="do not print one line per step")
    parser.add_argument("--trace-out", type=Path, metavar="FILE.jsonl",
                        help="write the trace as JSON lines to this file")
    return parser


def format_step(entry: TraceEntry) -> str:
    """One trace line: step, tool, args, outcome, message and budget."""
    args = entry.args if isinstance(entry.args, str) else json.dumps(entry.args)
    outcome = "ok" if entry.accepted else f"REJECTED {entry.policy} {entry.reason}"
    return (f"[{entry.step:3d}] {entry.tool} {args} -> {outcome}: {entry.message} "
            f"(budget {entry.budget_remaining})")


def _render(grid: tuple[tuple[int, ...], ...]) -> str:
    """Render a final grid with the board's own text view."""
    return Board.from_string("".join(str(d) for row in grid for d in row)).render()


def _write_trace(path: Path, result: RunResult) -> None:
    with path.open("w") as out:
        for entry in result.trace:
            out.write(json.dumps(asdict(entry)) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; returns the process exit code."""
    options = _parser().parse_args(argv)
    try:
        puzzle = load(options.puzzle_file)
    except (OSError, ValueError) as error:
        print(f"error: cannot load puzzle: {error}", file=sys.stderr)
        return 1

    config = Config(
        max_actions=options.max_actions,
        model_name=options.model or default_model_name(),
        history_window=options.history,
    )
    on_step = None if options.quiet else (lambda entry: print(format_step(entry), flush=True))
    try:
        result = run(puzzle.puzzle, config, on_step=on_step)
    except ValueError as error:   # a well-formatted file whose givens conflict
        print(f"error: invalid puzzle: {error}", file=sys.stderr)
        return 1

    if options.trace_out is not None:
        _write_trace(options.trace_out, result)
    print(_render(result.final_grid))
    print(f"Status: {result.status.value}")
    print(f"Reason: {result.reason}")
    print(f"Actions used: {result.actions_used}")
    return 0 if result.solved else 1
