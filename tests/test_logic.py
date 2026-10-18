"""Black-box tests for sudoku_agent.logic (SudokuKB), derived from specs/logic.md."""

from __future__ import annotations

import time

import pytest

from sudoku_agent.board import Board
from sudoku_agent.logic import Answer, AskResult, InferResult, SudokuKB, TellResult
from conftest import (
    EASY, EASY_SOLUTION, EXPERT, EXPERT_SOLUTION, HARD, HARD_SOLUTION,
    WRONG_LEGAL_NO_DEAD, empty_cells_of, sol_digit,
)


@pytest.fixture
def board():
    return Board.from_string(EASY)


@pytest.fixture
def kb(board):
    return SudokuKB(board)


def make_inconsistent(board, kb):
    """Wrong-but-legal placement: board can no longer be completed (R*)."""
    assert board.place(*WRONG_LEGAL_NO_DEAD).accepted
    kb.rebuild(board)


# ---------------------------------------------------------------- §3 rule layer, R*

class TestRuleLayer:
    def test_initially_consistent(self, kb):
        assert kb.is_consistent() is True

    def test_solution_digit_entailed(self, kb):
        res = kb.ask("v134")                  # r1c3 = 4 in the solution
        assert isinstance(res, AskResult)
        assert res.accepted is True and res.reason is None
        assert res.answer is Answer.ENTAILED

    def test_wrong_candidate_contradicted(self, kb):
        assert kb.ask("v131").answer is Answer.CONTRADICTED     # 1 is a candidate but wrong

    def test_eliminated_digit_contradicted(self, kb):
        # 5 is not a candidate for r1c3 (5 is in row 1); needs the §3.2 negative facts.
        assert kb.ask("v135").answer is Answer.CONTRADICTED

    def test_given_cell_own_digit_entailed_and_others_contradicted(self, kb):
        assert kb.ask("v115").answer is Answer.ENTAILED
        assert kb.ask("v116").answer is Answer.CONTRADICTED

    def test_compound_formula(self, kb):
        assert kb.ask("v134 & v115").answer is Answer.ENTAILED
        assert kb.ask("v131 | v132").answer is Answer.CONTRADICTED
        assert kb.ask("v131 -> v999").answer is Answer.ENTAILED   # false antecedent

    def test_every_cell_variable_decided_on_unique_puzzle(self, kb):
        # R*: with a unique solution and no wrong placements, never UNRESOLVED.
        for r, c in empty_cells_of(EASY)[:6]:
            d = sol_digit(EASY_SOLUTION, r, c)
            assert kb.ask(f"v{r}{c}{d}").answer is Answer.ENTAILED
            other = 1 if d != 1 else 2
            assert kb.ask(f"v{r}{c}{other}").answer is Answer.CONTRADICTED

    def test_wrong_placement_makes_kb_inconsistent(self, board, kb):
        make_inconsistent(board, kb)
        assert kb.is_consistent() is False
        res = kb.ask("v134")
        assert (res.accepted, res.answer, res.reason) == (False, None, "KB_INCONSISTENT")

    def test_undoing_wrong_placement_restores_consistency(self, board, kb):
        make_inconsistent(board, kb)
        board.undo()
        kb.rebuild(board)
        assert kb.is_consistent() is True
        assert kb.ask("v134").answer is Answer.ENTAILED

    def test_rebuild_after_correct_placement_keeps_answers(self, board, kb):
        board.place(1, 3, 4)
        kb.rebuild(board)
        assert kb.is_consistent() is True
        assert kb.ask("v134").answer is Answer.ENTAILED   # now a filled cell
        assert kb.ask("v132").answer is Answer.CONTRADICTED

    def test_kb_does_not_mutate_board(self, board, kb):
        before = (board.grid(), board.depth)
        kb.ask("v134"); kb.tell("p"); kb.infer_cell(1, 3); kb.is_consistent()
        assert (board.grid(), board.depth) == before


# ---------------------------------------------------------------- three-valued answers

class TestThreeValued:
    def test_helper_symbol_unresolved_then_entailed_then_negation_contradicted(self, kb):
        assert kb.ask("p").answer is Answer.UNRESOLVED
        assert kb.tell("p").accepted is True
        assert kb.ask("p").answer is Answer.ENTAILED
        assert kb.ask("~p").answer is Answer.CONTRADICTED

    def test_agent_rule_chains_with_rules(self, kb):
        assert kb.tell("v134 -> goal").accepted
        assert kb.ask("goal").answer is Answer.ENTAILED

    def test_word_operators(self, kb):
        assert kb.tell("a IMPLIES b").accepted
        assert kb.tell("a").accepted
        assert kb.ask("b AND NOT v131").answer is Answer.ENTAILED

    def test_ask_does_not_change_kb(self, kb):
        before = kb.agent_facts()
        kb.ask("q")
        kb.ask("v134")
        assert kb.agent_facts() == before


# ---------------------------------------------------------------- §2, §5.3 tell

LONG = "p" + " | p" * 200          # 801 characters, otherwise valid


class TestTell:
    def test_accepted_tell_records_depth(self, board, kb):
        res = kb.tell("p")
        assert isinstance(res, TellResult)
        assert (res.accepted, res.reason) == (True, None)
        assert kb.agent_facts() == ((0, "p"),)

    @pytest.mark.parametrize("formula,reason", [
        (LONG, "TOO_LONG"),
        ("p &", "PARSE_ERROR"),
        ("(p | q", "PARSE_ERROR"),
        ("AND", "PARSE_ERROR"),
        ("v105", "INVALID_SYMBOL"),
        ("v000 | p", "INVALID_SYMBOL"),
        ("v131", "INCONSISTENT"),            # r1c3 is 4, so rules entail ~v131
        ("v115 -> v116", "INCONSISTENT"),
    ])
    def test_rejections_leave_kb_unchanged(self, kb, formula, reason):
        kb.tell("keep")
        before_facts = kb.agent_facts()
        before_answer = kb.ask("keep").answer
        res = kb.tell(formula)
        assert (res.accepted, res.reason) == (False, reason)
        assert res.message
        assert kb.agent_facts() == before_facts
        assert kb.ask("keep").answer is before_answer
        assert kb.is_consistent() is True

    def test_exactly_500_characters_is_not_too_long(self, kb):
        f = "p" + " | p" * 124 + " "    # 1 + 496 + 1 = 498; pad to 500 with spaces
        f = f + " " * (500 - len(f))
        assert len(f) == 500
        assert kb.tell(f).reason != "TOO_LONG"

    def test_tell_while_kb_inconsistent(self, board, kb):
        make_inconsistent(board, kb)
        res = kb.tell("p")
        assert (res.accepted, res.reason) == (False, "KB_INCONSISTENT")
        assert kb.agent_facts() == ()

    def test_syntax_checks_precede_kb_inconsistent(self, board, kb):
        make_inconsistent(board, kb)
        assert kb.tell("p &").reason == "PARSE_ERROR"

    def test_duplicate_tell_stored_once(self, kb):
        assert kb.tell("p").accepted
        assert kb.tell("p").accepted
        assert kb.agent_facts() == ((0, "p"),)

    def test_ordinary_symbols_resembling_cell_vars(self, kb):
        assert kb.tell("v5370").accepted        # four digits: an ordinary symbol
        assert kb.ask("vx | v5370").answer is Answer.ENTAILED


class TestAskValidation:
    @pytest.mark.parametrize("formula,reason", [
        (LONG, "TOO_LONG"), ("p &", "PARSE_ERROR"), ("v105", "INVALID_SYMBOL"), ("v000", "INVALID_SYMBOL"),
    ])
    def test_ask_rejections(self, kb, formula, reason):
        res = kb.ask(formula)
        assert (res.accepted, res.answer, res.reason) == (False, None, reason)

    def test_ordinary_symbol_accepted(self, kb):
        res = kb.ask("v5370")
        assert res.accepted is True and res.answer is Answer.UNRESOLVED


# ---------------------------------------------------------------- §5.5, §5.6

class TestAgentLayerMaintenance:
    def test_clear_agent_facts_only_clears_agent_layer(self, kb):
        kb.tell("p"); kb.tell("q")
        assert kb.clear_agent_facts() == 2
        assert kb.agent_facts() == ()
        assert kb.ask("p").answer is Answer.UNRESOLVED
        assert kb.ask("v134").answer is Answer.ENTAILED
        assert kb.clear_agent_facts() == 0

    def test_rollback_to_keeps_facts_at_or_below_depth(self, board, kb):
        kb.tell("a")                              # depth 0
        board.place(1, 3, 4); kb.rebuild(board)
        kb.tell("b")                              # depth 1
        board.place(1, 4, 6); kb.rebuild(board)
        kb.tell("c")                              # depth 2
        assert kb.agent_facts() == ((0, "a"), (1, "b"), (2, "c"))
        assert kb.rollback_to(1) == 1
        assert kb.agent_facts() == ((0, "a"), (1, "b"))
        assert kb.ask("c").answer is Answer.UNRESOLVED
        assert kb.rollback_to(5) == 0
        assert kb.rollback_to(0) == 1
        assert kb.agent_facts() == ((0, "a"),)

    @pytest.mark.parametrize("bad,exc", [(-1, ValueError), ("1", TypeError), (1.0, TypeError)])
    def test_rollback_to_argument_errors(self, kb, bad, exc):
        with pytest.raises(exc):
            kb.rollback_to(bad)


# ---------------------------------------------------------------- §5.7 infer_cell

class TestInferCell:
    def test_empty_cell_returns_proven_digit(self, kb):
        res = kb.infer_cell(1, 3)
        assert isinstance(res, InferResult)
        assert res.accepted is True and res.reason is None
        assert res.digit == 4
        assert tuple(res.possible) == (4,)
        assert tuple(res.ruled_out) == (1, 2)

    def test_filled_cell_returns_its_digit(self, kb):
        res = kb.infer_cell(1, 1)
        assert (res.accepted, res.digit, tuple(res.possible), tuple(res.ruled_out)) == (True, 5, (5,), ())

    def test_inconsistent_kb(self, board, kb):
        make_inconsistent(board, kb)
        res = kb.infer_cell(2, 2)
        assert (res.accepted, res.reason) == (False, "KB_INCONSISTENT")

    @pytest.mark.parametrize("args,exc", [((0, 3), ValueError), ((1, 10), ValueError), (("1", 3), TypeError)])
    def test_argument_errors(self, kb, args, exc):
        with pytest.raises(exc):
            kb.infer_cell(*args)

    def test_infer_does_not_change_agent_layer(self, kb):
        kb.tell("p")
        before = kb.agent_facts()
        kb.infer_cell(1, 3)
        assert kb.agent_facts() == before


# ---------------------------------------------------------------- §5.8 cache transparency

class TestCache:
    def test_repeated_ask_same_answer(self, kb):
        first = kb.ask("v134")
        second = kb.ask("v134")
        assert first.answer is second.answer is Answer.ENTAILED

    def test_tell_invalidates_cached_answer(self, kb):
        assert kb.ask("p").answer is Answer.UNRESOLVED
        kb.tell("p")
        assert kb.ask("p").answer is Answer.ENTAILED

    def test_clear_invalidates_cached_answer(self, kb):
        kb.tell("p")
        assert kb.ask("p").answer is Answer.ENTAILED
        kb.clear_agent_facts()
        assert kb.ask("p").answer is Answer.UNRESOLVED

    def test_rollback_invalidates_cached_answer(self, board, kb):
        board.place(1, 3, 4); kb.rebuild(board)
        kb.tell("p")
        assert kb.ask("p").answer is Answer.ENTAILED
        kb.rollback_to(0)
        assert kb.ask("p").answer is Answer.UNRESOLVED

    def test_rebuild_invalidates_cached_consistency(self, board, kb):
        assert kb.is_consistent() is True
        make_inconsistent(board, kb)
        assert kb.is_consistent() is False

    def test_repeated_ask_is_fast(self):
        b = Board.from_string(HARD)
        k = SudokuKB(b)
        k.ask("v121")
        t = time.perf_counter()
        k.ask("v121")
        assert time.perf_counter() - t < 0.05


# ---------------------------------------------------------------- §6 performance targets (slow)

PERF = [
    ("easy", EASY, EASY_SOLUTION, 10, 30),
    ("hard", HARD, HARD_SOLUTION, 10, 30),
    ("expert", EXPERT, EXPERT_SOLUTION, 60, 180),
]


@pytest.mark.slow
@pytest.mark.parametrize("name,puzzle,solution,ask_limit,infer_limit", PERF)
def test_performance_targets(name, puzzle, solution, ask_limit, infer_limit):
    r, c = empty_cells_of(puzzle)[0]
    d = sol_digit(solution, r, c)

    t = time.perf_counter()
    res = SudokuKB(Board.from_string(puzzle)).ask(f"v{r}{c}{d}")
    ask_seconds = time.perf_counter() - t
    assert res.answer is Answer.ENTAILED
    assert ask_seconds <= ask_limit, f"{name}: ask took {ask_seconds:.1f}s"

    t = time.perf_counter()
    inf = SudokuKB(Board.from_string(puzzle)).infer_cell(r, c)   # fresh KB: no cache help
    infer_seconds = time.perf_counter() - t
    assert inf.digit == d
    assert infer_seconds <= infer_limit, f"{name}: infer_cell took {infer_seconds:.1f}s"
