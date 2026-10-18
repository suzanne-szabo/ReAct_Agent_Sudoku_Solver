"""Measure Golem latency for the agent's real first turn, with and without model "thinking".

Sends the actual system prompt, initial board message and 13 bound tools, three
ways per model:
  default        - gateway defaults
  extra_body     - chat_template_kwargs.enable_thinking = False (vLLM/LiteLLM convention)
  /no_think      - Qwen's soft switch appended to the system prompt
and prints the time, the chosen tool call, and the size of any returned reasoning.

Usage (repo root, venv active, Tailscale on):
    python scripts/check_latency.py                    # all three models
    python scripts/check_latency.py Qwen3.8-27B        # one model
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import SystemMessage  # noqa: E402

from sudoku_agent import prompts  # noqa: E402
from sudoku_agent.controller import Config, Controller  # noqa: E402
from sudoku_agent.llm import make_model  # noqa: E402
from sudoku_agent.puzzles import load  # noqa: E402
from sudoku_agent.session import Session  # noqa: E402
from sudoku_agent.tools import tool_definitions  # noqa: E402

MODELS = ["Qwen3.8-27B", "Qwen3.8-Flash-Next", "Gemma-4-26B-A4B"]


def first_turn_messages(system_suffix: str = ""):
    puzzle = load(Path(__file__).resolve().parent.parent / "puzzles" / "easy.txt").puzzle
    config = Config()
    session = Session.new(puzzle, config)
    controller = Controller(session, config)
    return [SystemMessage(content=prompts.SYSTEM_PROMPT + system_suffix),
            prompts.initial_message(session, controller)]


def try_variant(model_name: str, label: str, extra_body=None, suffix: str = "") -> None:
    model = make_model(Config(model_name=model_name))
    if extra_body:
        model = model.model_copy(update={"extra_body": extra_body})   # ChatOpenAI.extra_body field
    bound = model.bind_tools(tool_definitions(), tool_choice="required")
    start = time.time()
    try:
        reply = bound.invoke(first_turn_messages(suffix))
    except Exception as error:  # report and keep going
        print(f"  {label:<11} ERROR after {time.time() - start:5.1f}s: {str(error)[:120]}")
        return
    seconds = time.time() - start
    reasoning = reply.additional_kwargs.get("reasoning_content") or ""
    calls = reply.tool_calls
    call = f"{calls[0]['name']}({calls[0]['args']})" if calls else f"NO TOOL CALL, text={reply.content[:60]!r}"
    usage = reply.response_metadata.get("token_usage", {}) or {}
    print(f"  {label:<11} {seconds:5.1f}s  out_tokens={usage.get('completion_tokens', '?'):>5}  "
          f"reasoning_chars={len(reasoning):>5}  -> {call}")


def main() -> None:
    for name in sys.argv[1:] or MODELS:
        print(f"== {name}")
        try_variant(name, "default")
        try_variant(name, "extra_body", extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        try_variant(name, "/no_think", suffix="\n/no_think")


if __name__ == "__main__":
    main()
