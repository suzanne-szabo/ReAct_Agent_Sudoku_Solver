"""Chat-model factory for the school's OpenAI-compatible Golem gateway.

Implements specs/agent.md §6 (architecture §4.9, D12). Settings come from the
environment or from a ``.env`` file in the current working directory; values
already in the environment take precedence. The key is never committed
(see ``.env.example``).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values
from langchain_openai import ChatOpenAI

from sudoku_agent.controller import Config

DEFAULT_BASE_URL = "http://golem:4000/v1"
REQUEST_TIMEOUT_SECONDS = 120


def _setting(name: str) -> str | None:
    """Read a setting from the environment, falling back to ``./.env``."""
    if name in os.environ:
        return os.environ[name]
    env_file = Path.cwd() / ".env"
    if env_file.is_file():
        return dotenv_values(env_file).get(name)
    return None


def default_model_name() -> str:
    """The model name from ``SUDOKU_MODEL``, or the ``Config`` default."""
    return _setting("SUDOKU_MODEL") or Config().model_name


def make_model(config: Config) -> ChatOpenAI:
    """A ``ChatOpenAI`` client for ``config.model_name`` on the Golem gateway.

    Raises ``RuntimeError`` if ``GOLEM_API_KEY`` is not set.
    """
    api_key = _setting("GOLEM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOLEM_API_KEY is not set. Put it in the environment or in a .env file "
            "in the current directory (see .env.example)."
        )
    return ChatOpenAI(
        base_url=_setting("GOLEM_BASE_URL") or DEFAULT_BASE_URL,
        api_key=api_key,
        model=config.model_name,
        temperature=0,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,   # agent §2.1: the loop's single retry is the only retry
    )
