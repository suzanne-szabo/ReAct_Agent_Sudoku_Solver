"""Black-box tests for session, puzzles, prompts and llm, derived from
specs/architecture.md §4.7, §4.9 and specs/agent.md §5, §6, §8."""

from __future__ import annotations

from pathlib import Path

import pytest

from sudoku_agent.controller import Config, Controller
from sudoku_agent.session import Session
from conftest import EASY, EASY_SOLUTION, EXPERT, EXPERT_SOLUTION, HARD, HARD_SOLUTION, to_grid

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- session

def test_session_new_attributes():
    cfg = Config(max_actions=50)
    s = Session.new(EASY, cfg)
    assert s.board.grid() == to_grid(EASY)
    assert s.original_puzzle == EASY
    assert s.config is cfg
    assert s.kb.is_consistent() is True


def test_session_keeps_original_string_exactly():
    dotted = EASY.replace("0", ".")
    assert Session.new(dotted, Config()).original_puzzle == dotted


def test_session_malformed_puzzle():
    with pytest.raises(ValueError):
        Session.new("12", Config())


# ---------------------------------------------------------------- puzzles

@pytest.mark.parametrize("name,puzzle,solution", [
    ("easy", EASY, EASY_SOLUTION), ("hard", HARD, HARD_SOLUTION), ("expert", EXPERT, EXPERT_SOLUTION),
])
def test_bundled_puzzles_load(name, puzzle, solution):
    from sudoku_agent.puzzles import load
    p = load(REPO / "puzzles" / f"{name}.txt")
    assert (p.name, p.puzzle, p.solution) == (name, puzzle, solution)


def test_bundled_solutions_validate():
    from sudoku_agent.puzzles import load
    from sudoku_agent.validation import validate_solution
    for name in ("easy", "hard", "expert"):
        p = load(REPO / "puzzles" / f"{name}.txt")
        assert validate_solution(p.puzzle, to_grid(p.solution)).valid


def test_puzzle_without_solution_one_line(tmp_path):
    from sudoku_agent.puzzles import load
    f = tmp_path / "board7.txt"
    f.write_text("# from the instructor\n" + EASY.replace("0", ".") + "\n")
    p = load(f)
    assert (p.name, p.puzzle, p.solution) == ("board7", EASY, None)


def test_puzzle_nine_lines_with_zeros(tmp_path):
    from sudoku_agent.puzzles import load
    f = tmp_path / "x.txt"
    f.write_text("\n".join(EASY[i * 9:(i + 1) * 9] for i in range(9)) + "\n")
    assert load(f).puzzle == EASY


@pytest.mark.parametrize("content", [
    EASY[:80] + "\n",                                   # too short
    "x" + EASY[1:] + "\n",                              # bad character
    EASY + "\n\n" + EASY_SOLUTION + "\n\n" + EASY + "\n",   # extra section
    "",
])
def test_malformed_puzzle_files(tmp_path, content):
    from sudoku_agent.puzzles import load
    f = tmp_path / "bad.txt"
    f.write_text(content)
    with pytest.raises(ValueError):
        load(f)


# ---------------------------------------------------------------- prompts

def test_system_prompt_covers_required_points():
    from sudoku_agent.prompts import SYSTEM_PROMPT
    text = SYSTEM_PROMPT.lower()
    for word in ("submit", "undo", "kb_infer_cell", "get_candidates", "kb_ask", "forced", "one tool call"):
        assert word in text, word
    assert "v" in SYSTEM_PROMPT and "1" in SYSTEM_PROMPT


def test_status_message_format():
    from langchain_core.messages import HumanMessage
    from sudoku_agent.prompts import status_message
    cfg = Config()
    s = Session.new(EASY, cfg)
    ctl = Controller(s, cfg)
    ctl.handle("place_number", {"row": 1, "col": 3, "digit": 4})
    ctl.handle("kb_tell", {"formula": "p"})
    msg = status_message(s, ctl)
    assert isinstance(msg, HumanMessage)
    assert "Current board (empty: 50, budget remaining: 498, undo depth: 1, KB facts: 1):" in msg.content
    assert s.board.render() in msg.content


# ---------------------------------------------------------------- llm

def test_make_model_requires_api_key(monkeypatch, tmp_path):
    from sudoku_agent.llm import make_model
    monkeypatch.chdir(tmp_path)                 # no .env here
    monkeypatch.delenv("GOLEM_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        make_model(Config())


def test_make_model_configures_chat_openai(monkeypatch, tmp_path):
    from langchain_openai import ChatOpenAI
    from sudoku_agent.llm import make_model
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOLEM_API_KEY", "test-key-not-real")
    monkeypatch.setenv("GOLEM_BASE_URL", "http://example.invalid:4000/v1")
    m = make_model(Config(model_name="Gemma-4-26B-A4B"))
    assert isinstance(m, ChatOpenAI)
    assert m.model_name == "Gemma-4-26B-A4B"
    assert m.temperature == 0
    assert m.max_retries == 0          # agent §6 (v3): no hidden library retries
    assert str(m.openai_api_base).startswith("http://example.invalid:4000/v1")


def test_make_model_reads_dotenv_from_cwd(monkeypatch, tmp_path):
    from sudoku_agent.llm import make_model
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOLEM_API_KEY", "placeholder")   # registers restore-on-teardown
    monkeypatch.delenv("GOLEM_API_KEY")                  # so the dotenv value cannot leak
    (tmp_path / ".env").write_text("GOLEM_API_KEY=from-dotenv\n")
    m = make_model(Config())
    assert m.openai_api_key.get_secret_value() == "from-dotenv"
