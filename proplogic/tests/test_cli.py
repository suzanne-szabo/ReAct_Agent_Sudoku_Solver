"""Tests for the provided propositional-logic command-line tool."""

import unittest
import subprocess
import sys
from io import StringIO
from pathlib import Path

from proplogic import KnowledgeBase, to_cnf
from proplogic.cli import format_cnf, main, run_repl


class LogicCliTests(unittest.TestCase):
    def test_batch_mode_adds_formulas_and_answers_queries(self) -> None:
        output = StringIO()
        status = main(
            [
                "--tell",
                "a -> b",
                "--tell",
                "a",
                "--ask",
                "b",
                "--ask",
                "c",
                "--check-consistency",
            ],
            output_stream=output,
        )

        self.assertEqual(status, 0)
        self.assertEqual(
            output.getvalue(),
            "ENTAILED: b\nNOT ENTAILED: c\nCONSISTENT\n",
        )

    def test_batch_mode_displays_converted_cnf(self) -> None:
        output = StringIO()

        status = main(["--cnf", "a OR (b AND c)"], output_stream=output)

        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue(), "CNF: (a | b) & (a | c)\n")

    def test_batch_mode_reports_formula_errors(self) -> None:
        errors = StringIO()

        status = main(["--tell", "a AND"], error_stream=errors)

        self.assertEqual(status, 2)
        self.assertIn("error:", errors.getvalue())

    def test_package_module_invocation(self) -> None:
        starter_root = Path(__file__).resolve().parents[2]
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "proplogic",
                "--tell",
                "a -> b",
                "--tell",
                "a",
                "--ask",
                "b",
            ],
            cwd=starter_root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "ENTAILED: b\n")

    def test_repl_supports_kb_lifecycle(self) -> None:
        commands = StringIO(
            "tell a -> b\n"
            "tell a\n"
            "ask b\n"
            "consistent\n"
            "clauses\n"
            "clear\n"
            "ask b\n"
            "quit\n"
        )
        output = StringIO()
        kb = KnowledgeBase()

        status = run_repl(kb, commands, output)

        self.assertEqual(status, 0)
        text = output.getvalue()
        self.assertIn("entailed", text)
        self.assertIn("consistent", text)
        self.assertIn("(~a | b) & (a)", text)
        self.assertIn("cleared", text)
        self.assertIn("not entailed", text)
        self.assertEqual(kb.clauses, ())

    def test_repl_recovers_after_error_and_accepts_general_whitespace(self) -> None:
        commands = StringIO("tell\naSk\tunknown\ntell\ta\nask a\nquit\n")
        output = StringIO()

        status = run_repl(KnowledgeBase(), commands, output)

        self.assertEqual(status, 0)
        text = output.getvalue()
        self.assertIn("error: tell requires a formula", text)
        self.assertIn("not entailed", text)
        self.assertTrue(text.rstrip().endswith("entailed\nlogic>"))

    def test_batch_then_interactive_retains_told_formulas(self) -> None:
        output = StringIO()

        status = main(
            ["--tell", "a -> b", "--tell", "a", "--interactive"],
            input_stream=StringIO("ask b\nquit\n"),
            output_stream=output,
        )

        self.assertEqual(status, 0)
        self.assertIn("entailed", output.getvalue())

    def test_format_cnf_handles_true_and_false(self) -> None:
        self.assertEqual(format_cnf(to_cnf("a OR NOT a")), "TRUE")
        self.assertEqual(format_cnf((frozenset(),)), "FALSE")


if __name__ == "__main__":
    unittest.main()
