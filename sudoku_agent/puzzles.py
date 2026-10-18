"""Puzzle-file loader; the solution section is optional.

Implements specs/agent.md §8. A file holds the puzzle as 9 lines or one line of
81 characters (``0`` or ``.`` for empty cells), optionally followed by a blank
line and the solution in the same format. Lines starting with ``#`` are comments.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Puzzle:
    """A loaded puzzle; ``puzzle`` and ``solution`` are 81 characters, ``0`` = empty."""

    name: str
    puzzle: str
    solution: str | None


def _sections(text: str) -> list[list[str]]:
    """Group the non-comment lines into blank-line-separated sections."""
    sections: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped:
            current.append(stripped)
        elif current:
            sections.append(current)
            current = []
    if current:
        sections.append(current)
    return sections


def _normalize(lines: list[str], what: str) -> str:
    """Join a section into 81 characters with ``0`` for empty cells."""
    text = "".join("".join(lines).split())
    if len(text) != 81:
        raise ValueError(f"{what} must have 81 cells, got {len(text)}")
    bad = sorted(set(text) - set("0123456789."))
    if bad:
        raise ValueError(f"{what} contains invalid characters: {''.join(bad)!r}")
    return text.replace(".", "0")


def load(path: str | Path) -> Puzzle:
    """Load a puzzle file (agent §8); raises ``ValueError`` on malformed content."""
    path = Path(path)
    sections = _sections(path.read_text())
    if not sections:
        raise ValueError(f"{path}: no puzzle found")
    if len(sections) > 2:
        raise ValueError(f"{path}: expected a puzzle and at most one solution section, "
                         f"found {len(sections)} sections")
    puzzle = _normalize(sections[0], "puzzle")
    solution = _normalize(sections[1], "solution") if len(sections) == 2 else None
    return Puzzle(name=path.stem, puzzle=puzzle, solution=solution)
