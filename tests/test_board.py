"""Black-box tests for sudoku_agent.board, derived from specs/board.md."""

from __future__ import annotations

import pytest

from sudoku_agent.board import Board, PlaceResult, UndoResult
from conftest import (
    CASCADE_FORCED, CASCADE_PLACEMENT, EASY, EASY_EMPTY_COUNT, EASY_SOLUTION,
    WRONG_WITH_DEAD, WRONG_WITH_DEAD_CELL, empty_cells_of, sol_digit, to_grid,
)

EXPECTED_RENDER = [
    "   123 456 789",
    "1  53. .7. ...",
    "2  6.. 195 ...",
    "3  .98 ... .6.",
    "   --- --- ---",
    "4  8.. .6. ..3",
    "5  4.. 8.3 ..1",
    "6  7.. .2. ..6",
    "   --- --- ---",
    "7  .6. ... 28.",
    "8  ... 419 ..5",
    "9  ... .8. .79",
]


def snapshot(board):
    return board.grid(), board.depth, board.placements()


# ---------------------------------------------------------------- §3 parsing

class TestFromString:
    def test_parses_zero_format(self):
        assert Board.from_string(EASY).grid() == to_grid(EASY)

    def test_parses_dot_format_identically(self):
        assert Board.from_string(EASY.replace("0", ".")).grid() == to_grid(EASY)

    def test_ignores_whitespace_and_newlines(self):
        nine_lines = "\n".join(EASY[i * 9:(i + 1) * 9] for i in range(9))
        spaced = "  " + nine_lines.replace("\n", " \n\t") + "\n"
        assert Board.from_string(spaced).grid() == to_grid(EASY)

    def test_new_board_has_depth_zero_and_no_placements(self):
        b = Board.from_string(EASY)
        assert b.depth == 0
        assert b.placements() == ()

    @pytest.mark.parametrize("bad", [EASY[:80], EASY + "0", ""])
    def test_wrong_length_raises_value_error(self, bad):
        with pytest.raises(ValueError):
            Board.from_string(bad)

    def test_bad_character_raises_value_error(self):
        with pytest.raises(ValueError):
            Board.from_string("x" + EASY[1:])

    def test_duplicate_givens_in_row_raise(self):
        # r1c3 is empty in EASY; put a second 5 in row 1.
        bad = EASY[:2] + "5" + EASY[3:]
        with pytest.raises(ValueError):
            Board.from_string(bad)

    def test_duplicate_givens_in_column_raise(self):
        # r3c1 is empty in EASY; column 1 already has 5 at r1c1.
        i = 2 * 9 + 0
        bad = EASY[:i] + "5" + EASY[i + 1:]
        with pytest.raises(ValueError):
            Board.from_string(bad)

    def test_duplicate_givens_in_box_raise(self):
        # r2c2 is empty; box 1 already has 9 at r3c2 ... use 8 (r3c3) instead.
        i = 1 * 9 + 1
        bad = EASY[:i] + "8" + EASY[i + 1:]
        with pytest.raises(ValueError):
            Board.from_string(bad)

    def test_non_string_raises_type_error(self):
        with pytest.raises(TypeError):
            Board.from_string(12345)  # type: ignore[arg-type]

    def test_unsolvable_but_well_formed_puzzle_is_accepted(self):
        # Uniqueness/solvability is explicitly not checked (§3).
        b = Board.from_string("0" * 81)
        assert b.is_complete() is False


# ---------------------------------------------------------------- §4.1 views

class TestViews:
    def test_cell(self, easy_board):
        assert easy_board.cell(1, 1) == 5
        assert easy_board.cell(1, 3) == 0
        assert easy_board.cell(9, 9) == 9

    def test_row(self, easy_board):
        assert easy_board.row(1) == [5, 3, 0, 0, 7, 0, 0, 0, 0]
        assert easy_board.row(9) == [0, 0, 0, 0, 8, 0, 0, 7, 9]

    def test_col(self, easy_board):
        assert easy_board.col(1) == [5, 6, 0, 8, 4, 7, 0, 0, 0]

    @pytest.mark.parametrize("box,expected", [
        (1, [5, 3, 0, 6, 0, 0, 0, 9, 8]),
        (5, [0, 6, 0, 8, 0, 3, 0, 2, 0]),
        (9, [2, 8, 0, 0, 0, 5, 0, 7, 9]),
    ])
    def test_box(self, easy_board, box, expected):
        assert easy_board.box(box) == expected

    def test_grid_is_immutable_snapshot(self, easy_board):
        g = easy_board.grid()
        assert isinstance(g, tuple) and all(isinstance(row, tuple) for row in g)
        easy_board.place(1, 3, 4)
        assert g == to_grid(EASY)
        assert easy_board.grid() != g

    def test_is_given(self, easy_board):
        assert easy_board.is_given(1, 1) is True
        assert easy_board.is_given(1, 3) is False
        easy_board.place(1, 3, 4)
        assert easy_board.is_given(1, 3) is False

    def test_empty_cells_row_major(self, easy_board):
        cells = easy_board.empty_cells()
        assert cells == empty_cells_of(EASY)
        assert len(cells) == EASY_EMPTY_COUNT

    def test_is_complete(self):
        assert Board.from_string(EASY_SOLUTION).is_complete() is True
        assert Board.from_string(EASY).is_complete() is False

    def test_render_exact_format(self, easy_board):
        out = easy_board.render()
        assert out.splitlines() == EXPECTED_RENDER
        assert not any(line.endswith(" ") for line in out.splitlines())

    def test_render_reflects_placement(self, easy_board):
        easy_board.place(1, 3, 4)
        assert easy_board.render().splitlines()[1] == "1  534 .7. ..."


# ---------------------------------------------------------------- §4.3, §4.4

class TestCandidatesAndPeers:
    def test_candidates_of_empty_cell(self, easy_board):
        assert easy_board.candidates(1, 3) == [1, 2, 4]

    def test_candidates_of_given_cell_is_empty(self, easy_board):
        assert easy_board.candidates(1, 1) == []

    def test_candidates_of_placed_cell_is_empty(self, easy_board):
        easy_board.place(1, 3, 4)
        assert easy_board.candidates(1, 3) == []

    def test_dead_cell_has_no_candidates(self, easy_board):
        r, c, d = WRONG_WITH_DEAD
        easy_board.place(r, c, d)
        assert easy_board.candidates(*WRONG_WITH_DEAD_CELL) == []
        assert easy_board.cell(*WRONG_WITH_DEAD_CELL) == 0

    def test_peers(self, easy_board):
        p = easy_board.peers(1, 1)
        assert len(p) == 20
        assert (1, 1) not in p
        assert {(1, 9), (9, 1), (3, 3)} <= p
        assert (4, 4) not in p


# ---------------------------------------------------------------- §4.6 place

class TestPlace:
    def test_accepts_legal_placement(self, easy_board):
        res = easy_board.place(1, 3, 4)
        assert isinstance(res, PlaceResult)
        assert res.accepted is True and res.reason is None
        assert easy_board.cell(1, 3) == 4
        assert easy_board.depth == 1
        assert easy_board.placements() == ((1, 3, 4),)

    def test_given_cell_rejected(self, easy_board):
        before = snapshot(easy_board)
        res = easy_board.place(1, 1, 5)
        assert (res.accepted, res.reason) == (False, "GIVEN_CELL")
        assert res.forced_cells == () and res.dead_cells == ()
        assert snapshot(easy_board) == before

    def test_given_cell_takes_priority_over_conflict(self, easy_board):
        # r1c1 is a given and 3 already appears in row 1.
        res = easy_board.place(1, 1, 3)
        assert res.reason == "GIVEN_CELL"

    def test_filled_cell_rejected(self, easy_board):
        easy_board.place(1, 3, 4)
        before = snapshot(easy_board)
        res = easy_board.place(1, 3, 2)
        assert (res.accepted, res.reason) == (False, "CELL_FILLED")
        assert snapshot(easy_board) == before

    def test_filled_cell_takes_priority_over_conflict(self, easy_board):
        easy_board.place(1, 3, 4)
        res = easy_board.place(1, 3, 5)      # 5 is also in row 1
        assert res.reason == "CELL_FILLED"

    @pytest.mark.parametrize("r,c,d", [
        (1, 3, 5),    # 5 already in row 1 (r1c1)
        (1, 3, 8),    # 8 already in column 3 / box 1 (r3c3)
        (2, 2, 9),    # 9 already in column 2 / box 1 (r3c2)
    ])
    def test_conflict_rejected(self, easy_board, r, c, d):
        before = snapshot(easy_board)
        res = easy_board.place(r, c, d)
        assert (res.accepted, res.reason) == (False, "CONFLICT")
        assert res.message
        assert snapshot(easy_board) == before

    def test_conflict_message_names_unit(self, easy_board):
        res = easy_board.place(1, 3, 5)
        assert "row 1" in res.message

    def test_wrong_but_legal_placement_accepted(self, easy_board):
        res = easy_board.place(1, 3, 1)       # solution is 4, but 1 is legal
        assert res.accepted is True

    def test_forced_cells_cascade(self, easy_board):
        res = easy_board.place(*CASCADE_PLACEMENT)
        assert res.accepted is True
        assert list(res.forced_cells) == CASCADE_FORCED

    def test_forced_cells_are_newly_forced_only(self, easy_board):
        # Every reported forced cell is an empty peer whose single candidate is as reported.
        res = easy_board.place(*CASCADE_PLACEMENT)
        peers = easy_board.peers(CASCADE_PLACEMENT[0], CASCADE_PLACEMENT[1])
        for r, c, d in res.forced_cells:
            assert (r, c) in peers
            assert easy_board.candidates(r, c) == [d]

    def test_dead_cells_after_wrong_placement(self, easy_board):
        res = easy_board.place(*WRONG_WITH_DEAD)
        assert res.accepted is True
        assert list(res.dead_cells) == [WRONG_WITH_DEAD_CELL]

    def test_correct_placement_has_no_dead_cells(self, easy_board):
        res = easy_board.place(1, 3, sol_digit(EASY_SOLUTION, 1, 3))
        assert res.dead_cells == ()

    @pytest.mark.parametrize("args", [(0, 3, 4), (10, 3, 4), (1, 0, 4), (1, 10, 4), (1, 3, 0), (1, 3, 10)])
    def test_out_of_range_raises_value_error(self, easy_board, args):
        before = snapshot(easy_board)
        with pytest.raises(ValueError):
            easy_board.place(*args)
        assert snapshot(easy_board) == before

    @pytest.mark.parametrize("args", [("1", 3, 4), (1, 3.0, 4), (1, 3, True), (True, 3, 4)])
    def test_wrong_type_raises_type_error(self, easy_board, args):
        before = snapshot(easy_board)
        with pytest.raises(TypeError):
            easy_board.place(*args)
        assert snapshot(easy_board) == before

    @pytest.mark.parametrize("method,args", [
        ("cell", (0, 1)), ("row", (10,)), ("col", (0,)), ("box", (10,)),
        ("candidates", (1, 10)), ("is_given", (0, 0)), ("peers", (10, 1)),
    ])
    def test_view_range_errors(self, easy_board, method, args):
        with pytest.raises(ValueError):
            getattr(easy_board, method)(*args)


# ---------------------------------------------------------------- §4.7 undo

class TestUndo:
    def test_empty_stack(self, easy_board):
        before = snapshot(easy_board)
        res = easy_board.undo()
        assert isinstance(res, UndoResult)
        assert (res.accepted, res.reason, res.removed) == (False, "EMPTY_STACK", None)
        assert snapshot(easy_board) == before

    def test_lifo_order(self, easy_board):
        moves = [(1, 3, 4), (1, 4, 6), (1, 6, 8)]
        for m in moves:
            assert easy_board.place(*m).accepted
        for expected in reversed(moves):
            res = easy_board.undo()
            assert res.accepted and res.reason is None
            assert res.removed == expected
            assert easy_board.cell(expected[0], expected[1]) == 0
        assert easy_board.depth == 0
        assert easy_board.undo().reason == "EMPTY_STACK"

    def test_place_then_undo_restores_grid(self, easy_board):
        before = easy_board.grid()
        easy_board.place(*CASCADE_PLACEMENT)
        easy_board.undo()
        assert easy_board.grid() == before

    def test_rejected_place_does_not_push(self, easy_board):
        easy_board.place(1, 3, 4)
        easy_board.place(1, 1, 5)          # rejected
        easy_board.place(1, 3, 2)          # rejected
        assert easy_board.depth == 1
        assert easy_board.undo().removed == (1, 3, 4)

    def test_undo_never_removes_givens(self, easy_board):
        easy_board.place(1, 3, 4)
        easy_board.undo()
        easy_board.undo()
        assert easy_board.cell(1, 1) == 5
        assert easy_board.grid() == to_grid(EASY)


# ---------------------------------------------------------------- §5 invariants

def _check_invariants(board, original):
    g = board.grid()
    orig = to_grid(original)
    # I1: givens preserved
    for r in range(9):
        for c in range(9):
            if orig[r][c]:
                assert g[r][c] == orig[r][c]
    # I2: no duplicate non-zero digit in any unit
    units = [[(r, c) for c in range(9)] for r in range(9)]
    units += [[(r, c) for r in range(9)] for c in range(9)]
    units += [[(br * 3 + i, bc * 3 + j) for i in range(3) for j in range(3)] for br in range(3) for bc in range(3)]
    for u in units:
        vals = [g[r][c] for r, c in u if g[r][c]]
        assert len(vals) == len(set(vals))
    # I3: depth/placements agree and placed cells are exactly the non-given filled cells
    assert board.depth == len(board.placements())
    placed = {(r, c) for r, c, _ in board.placements()}
    filled_non_given = {(r + 1, c + 1) for r in range(9) for c in range(9) if g[r][c] and not orig[r][c]}
    assert placed == filled_non_given
    for r, c, d in board.placements():
        assert g[r - 1][c - 1] == d


def test_invariants_hold_through_mixed_sequence(easy_board):
    ops = [
        ("place", (1, 3, 4)), ("place", (1, 1, 5)), ("place", (1, 3, 9)),
        ("place", (2, 2, 9)), ("place", (*CASCADE_PLACEMENT,)), ("undo", ()),
        ("place", (*WRONG_WITH_DEAD,)), ("place", (1, 4, 6)), ("undo", ()),
        ("undo", ()), ("undo", ()), ("undo", ()),
    ]
    for name, args in ops:
        getattr(easy_board, name)(*args)
        _check_invariants(easy_board, EASY)
