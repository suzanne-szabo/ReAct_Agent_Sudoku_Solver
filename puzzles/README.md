# Puzzles

## File format
- The puzzle is 9 lines (or one 81-character line), with `.` or `0` for empty cells.
- Optionally, a blank line follows, then the solution in the same format.
- Lines starting with `#` are comments.
- Puzzles without a solution (for example, instructor-provided boards) work as-is:
  the agent's success is decided only by the `submit` validator.

## Bundled puzzles
Each bundled puzzle was checked on 2026-10-17 by an exhaustive search. Each has
exactly one solution, and the stored solution was computed by code (not typed by
hand), is a valid Sudoku, and preserves every given.

| File | Source | Givens | Technique needed |
|---|---|---|---|
| `easy.txt` | Example puzzle from the Wikipedia article "Sudoku" | 30 | Single-candidate logic only |
| `hard.txt` | Peter Norvig, "Solving Every Sudoku Puzzle" (norvig.com/sudoku.html), puzzle *hard1* | 17 | Beyond single candidates |
| `expert.txt` | Arto Inkala (2012), widely reported as "the world's hardest Sudoku" | 21 | Beyond single candidates; worst case for the KB solver |
