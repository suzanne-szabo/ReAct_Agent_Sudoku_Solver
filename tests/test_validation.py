"""Black-box tests for sudoku_agent.validation, derived from specs/validation.md."""

from __future__ import annotations

import copy

import pytest

from sudoku_agent.validation import ValidationResult, validate_solution
from conftest import EASY, EASY_SOLUTION, to_grid


def as_lists(s):
    return [list(row) for row in to_grid(s)]


def test_correct_solution_is_valid():
    res = validate_solution(EASY, to_grid(EASY_SOLUTION))
    assert isinstance(res, ValidationResult)
    assert res.valid is True
    assert res.reasons == ()


def test_accepts_list_of_lists():
    assert validate_solution(EASY, as_lists(EASY_SOLUTION)).valid is True


def test_accepts_dot_format_original():
    assert validate_solution(EASY.replace("0", "."), to_grid(EASY_SOLUTION)).valid is True


def test_swapped_non_given_digits_in_row_invalid():
    # Row 1 of the solution is 534678912; givens in row 1 are r1c1=5, r1c2=3, r1c5=7.
    # Swap r1c3 (4) and r1c4 (6): row 1 stays a permutation, columns 3/4 and boxes 1/2 break.
    g = as_lists(EASY_SOLUTION)
    g[0][2], g[0][3] = g[0][3], g[0][2]
    res = validate_solution(EASY, g)
    assert res.valid is False
    assert "ROW_INVALID 1" not in res.reasons
    assert {"COL_INVALID 3", "COL_INVALID 4", "BOX_INVALID 1", "BOX_INVALID 2"} <= set(res.reasons)
    assert not any(r.startswith("GIVEN_CHANGED") for r in res.reasons)


def test_incomplete_grid_reports_each_empty_cell():
    g = as_lists(EASY_SOLUTION)
    g[0][2] = 0
    g[8][0] = 0
    res = validate_solution(EASY, g)
    assert res.valid is False
    empties = [r for r in res.reasons if r.startswith("EMPTY")]
    assert empties == ["EMPTY r1c3", "EMPTY r9c1"]
    assert {"ROW_INVALID 1", "ROW_INVALID 9", "COL_INVALID 3", "COL_INVALID 1",
            "BOX_INVALID 1", "BOX_INVALID 7"} <= set(res.reasons)


def test_unfilled_puzzle_counts():
    res = validate_solution(EASY, to_grid(EASY))
    assert res.valid is False
    assert len([r for r in res.reasons if r.startswith("EMPTY")]) == 51
    # every unit contains an empty cell in EASY, so all 27 unit checks fail too
    assert len(res.reasons) == 51 + 27


def test_changed_given_reported_even_if_grid_is_valid_sudoku():
    # Relabel digits 1<->2 everywhere: still a valid Sudoku, but givens change.
    swapped = EASY_SOLUTION.translate(str.maketrans("12", "21"))
    res = validate_solution(EASY, to_grid(swapped))
    assert res.valid is False
    changed = [r for r in res.reasons if r.startswith("GIVEN_CHANGED")]
    assert changed  # some given 1 or 2 changed
    assert "GIVEN_CHANGED r2c4" in changed       # r2c4 is a given 1
    assert not any(r.startswith(("ROW_INVALID", "COL_INVALID", "BOX_INVALID")) for r in res.reasons)


def test_reason_order_and_row_major_within_code():
    g = as_lists(EASY_SOLUTION)
    g[8][8] = 0          # EMPTY r9c9 (also a given: 9)
    g[0][0] = 6          # GIVEN_CHANGED r1c1 (given 5)
    g[4][4] = "x"        # BAD_VALUE r5c5
    res = validate_solution(EASY, g)
    codes = [r.split()[0] for r in res.reasons]
    order = ["BAD_VALUE", "EMPTY", "GIVEN_CHANGED", "ROW_INVALID", "COL_INVALID", "BOX_INVALID"]
    assert codes == sorted(codes, key=order.index)
    assert "BAD_VALUE r5c5" in res.reasons
    assert "EMPTY r9c9" in res.reasons
    assert "GIVEN_CHANGED r1c1" in res.reasons
    rows = [r for r in res.reasons if r.startswith("ROW_INVALID")]
    assert rows == sorted(rows, key=lambda r: int(r.split()[1]))


@pytest.mark.parametrize("grid", [
    [[1] * 9 for _ in range(8)],                       # 8 rows
    [[1] * 9 for _ in range(8)] + [[1] * 10],          # a row of 10
    [[1] * 9 for _ in range(10)],                      # 10 rows
    [],
])
def test_bad_shape_only(grid):
    res = validate_solution(EASY, grid)
    assert res.valid is False
    assert res.reasons == ("BAD_SHAPE",)


@pytest.mark.parametrize("bad", [10, -1, "5", 5.0, True, None])
def test_bad_value(bad):
    g = as_lists(EASY_SOLUTION)
    g[1][2] = bad        # r2c3, not a given
    res = validate_solution(EASY, g)
    assert res.valid is False
    assert "BAD_VALUE r2c3" in res.reasons


@pytest.mark.parametrize("original", [EASY[:80], "x" + EASY[1:]])
def test_malformed_original_raises_value_error(original):
    with pytest.raises(ValueError):
        validate_solution(original, to_grid(EASY_SOLUTION))


def test_non_string_original_raises_type_error():
    with pytest.raises(TypeError):
        validate_solution(None, to_grid(EASY_SOLUTION))  # type: ignore[arg-type]


def test_grid_not_mutated():
    g = as_lists(EASY_SOLUTION)
    g[0][2] = 0
    before = copy.deepcopy(g)
    validate_solution(EASY, g)
    assert g == before


def test_validation_does_not_import_board():
    # Independence requirement (§1). Checked in a fresh interpreter so this test
    # cannot disturb module state for the rest of the suite.
    import subprocess
    import sys
    from pathlib import Path
    code = "import sys, sudoku_agent.validation; print('sudoku_agent.board' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parent.parent, check=True)
    assert out.stdout.strip() == "False"
