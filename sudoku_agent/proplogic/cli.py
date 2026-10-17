"""Command-line formula tester for the provided propositional logic engine."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import TextIO

from .core import Clause, KnowledgeBase, Literal, to_cnf


HELP = """Commands:
  tell FORMULA       Add a formula to the knowledge base.
  ask FORMULA        Test whether the knowledge base entails a formula.
  cnf FORMULA        Display a formula in conjunctive normal form.
  clauses            Display all clauses in the knowledge base.
  consistent         Test whether the knowledge base is consistent.
  clear              Remove all formulas from the knowledge base.
  help               Display this command list.
  quit               Exit the tool.
"""


def format_literal(literal: Literal) -> str:
    return literal.symbol if literal.positive else f"~{literal.symbol}"


def format_clause(clause: Clause) -> str:
    if not clause:
        return "FALSE"
    literals = [format_literal(literal) for literal in sorted(clause)]
    return f"({' | '.join(literals)})"


def format_cnf(clauses: Sequence[Clause]) -> str:
    if not clauses:
        return "TRUE"
    return " & ".join(format_clause(clause) for clause in clauses)


def run_repl(
    kb: KnowledgeBase,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    print("Propositional Logic Tester. Type 'help' for commands.", file=output_stream)
    while True:
        output_stream.write("logic> ")
        output_stream.flush()
        line = input_stream.readline()
        if line == "":
            output_stream.write("\n")
            return 0
        line = line.strip()
        if not line:
            continue

        parts = line.split(maxsplit=1)
        command = parts[0].lower()
        argument = parts[1] if len(parts) == 2 else ""
        try:
            if command in ("quit", "exit"):
                return 0
            if command == "help":
                print(HELP, end="", file=output_stream)
            elif command == "tell":
                _require_formula(command, argument)
                kb.add_formula(argument)
                print("added", file=output_stream)
            elif command == "ask":
                _require_formula(command, argument)
                result = "entailed" if kb.entails(argument) else "not entailed"
                print(result, file=output_stream)
            elif command == "cnf":
                _require_formula(command, argument)
                print(format_cnf(to_cnf(argument)), file=output_stream)
            elif command == "clauses":
                _reject_argument(command, argument)
                print(format_cnf(kb.clauses), file=output_stream)
            elif command == "consistent":
                _reject_argument(command, argument)
                result = "consistent" if kb.is_consistent() else "inconsistent"
                print(result, file=output_stream)
            elif command == "clear":
                _reject_argument(command, argument)
                kb.clear()
                print("cleared", file=output_stream)
            else:
                print(f"error: unknown command {command!r}", file=output_stream)
        except (TypeError, ValueError) as error:
            print(f"error: {error}", file=output_stream)


def _require_formula(command: str, argument: str) -> None:
    if not argument:
        raise ValueError(f"{command} requires a formula")


def _reject_argument(command: str, argument: str) -> None:
    if argument:
        raise ValueError(f"{command} does not accept an argument")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Add and query propositional formulas."
    )
    parser.add_argument(
        "--tell",
        action="append",
        default=[],
        metavar="FORMULA",
        help="add a formula; may be repeated",
    )
    parser.add_argument(
        "--ask",
        action="append",
        default=[],
        metavar="FORMULA",
        help="test entailment of a formula; may be repeated",
    )
    parser.add_argument(
        "--cnf",
        action="append",
        default=[],
        metavar="FORMULA",
        help="convert a formula to CNF; may be repeated",
    )
    parser.add_argument(
        "--check-consistency",
        action="store_true",
        help="report whether the formulas supplied with --tell are consistent",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="enter the interactive tester after processing other options",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    error_stream: TextIO = sys.stderr,
) -> int:
    args = _parser().parse_args(argv)
    kb = KnowledgeBase()
    try:
        for formula in args.tell:
            kb.add_formula(formula)
        for formula in args.cnf:
            print(f"CNF: {format_cnf(to_cnf(formula))}", file=output_stream)
        for formula in args.ask:
            result = "ENTAILED" if kb.entails(formula) else "NOT ENTAILED"
            print(f"{result}: {formula}", file=output_stream)
        if args.check_consistency:
            result = "CONSISTENT" if kb.is_consistent() else "INCONSISTENT"
            print(result, file=output_stream)
    except (TypeError, ValueError) as error:
        print(f"error: {error}", file=error_stream)
        return 2

    no_batch_options = not (
        args.tell or args.ask or args.cnf or args.check_consistency
    )
    if args.interactive or no_batch_options:
        return run_repl(kb, input_stream, output_stream)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
