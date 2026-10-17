"""Smoke-test the Golem LLM gateway for the tool-calling features the agent needs.

Standard library only. Reads GOLEM_API_KEY (and optionally GOLEM_BASE_URL)
from the environment or from a .env file in the repository root.

Usage (from the repo root, with Tailscale connected):
    python3 scripts/check_golem.py                 # test all three models
    python3 scripts/check_golem.py Qwen3.8-27B     # test one model
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

MODELS = ["Gemma-4-26B-A4B", "Qwen3.8-27B", "Qwen3.8-Flash-Next"]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "place_number",
            "description": "Place a digit in an empty Sudoku cell.",
            "parameters": {
                "type": "object",
                "properties": {
                    "row": {"type": "integer", "minimum": 1, "maximum": 9},
                    "col": {"type": "integer", "minimum": 1, "maximum": 9},
                    "digit": {"type": "integer", "minimum": 1, "maximum": 9},
                },
                "required": ["row", "col", "digit"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_board",
            "description": "Return the current 9x9 board.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

PROMPT = (
    "Row 1 of a Sudoku is 5 3 . . 7 . . . . and the only digit that fits "
    "row 1, column 3 is 4. Make the placement."
)


def load_env() -> tuple[str, str]:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    key = os.environ.get("GOLEM_API_KEY")
    if not key:
        sys.exit("GOLEM_API_KEY is not set (put it in .env or export it).")
    base = os.environ.get("GOLEM_BASE_URL", "http://golem:4000/v1").rstrip("/")
    return base, key


def post(base: str, key: str, body: dict) -> tuple[int, dict | str, float]:
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    start = time.time()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.load(response), time.time() - start
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")[:300], time.time() - start
    except (urllib.error.URLError, TimeoutError) as error:
        return 0, str(error), time.time() - start


def check(base: str, key: str, model: str, tool_choice) -> str:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "tools": TOOLS,
        "tool_choice": tool_choice,
        "temperature": 0,
    }
    status, data, seconds = post(base, key, body)
    if status != 200:
        return f"FAIL  HTTP {status} ({seconds:.1f}s): {data}"
    message = data["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    if not calls:
        text = (message.get("content") or "").strip().replace("\n", " ")[:120]
        return f"FAIL  no tool call ({seconds:.1f}s); text: {text!r}"
    call = calls[0]["function"]
    return (
        f"OK    {len(calls)} call(s) ({seconds:.1f}s): "
        f"{call['name']}({call.get('arguments')})"
    )


def main() -> None:
    base, key = load_env()
    models = sys.argv[1:] or MODELS
    print(f"Gateway: {base}")
    for model in models:
        print(f"\n== {model}")
        print("  tool_choice=auto      ", check(base, key, model, "auto"))
        print("  tool_choice=required  ", check(base, key, model, "required"))
        named = {"type": "function", "function": {"name": "place_number"}}
        print("  tool_choice=<named>   ", check(base, key, model, named))


if __name__ == "__main__":
    main()
