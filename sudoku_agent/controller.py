"""Controller: policies, action budget, trace and ordered terminal checks.

Implements specs/controller.md (architecture §4.6, §6, §8). The controller is
the single gatekeeper between the model's requests and the application state,
and the only code that sets the terminal status.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum

from pydantic import BaseModel, ValidationError

from sudoku_agent.board import box_of
from sudoku_agent.session import Session
from sudoku_agent.tools import TOOL_SCHEMAS, execute as execute_tool, invalid_solution_data
from sudoku_agent.validation import validate_solution


@dataclass(frozen=True)
class Config:
    """Run configuration (controller §2)."""

    max_actions: int = 500
    max_consecutive_rejections: int = 5
    model_name: str = "Qwen3.8-27B"
    history_window: int = 12        # used by agent (specs/agent.md §3)


class TerminalStatus(Enum):
    """Why a run ended (architecture §6)."""

    SOLVED = "SOLVED"
    ACTION_LIMIT = "ACTION_LIMIT"
    REJECTION_LIMIT = "REJECTION_LIMIT"
    NO_ACTION = "NO_ACTION"
    MODEL_ERROR = "MODEL_ERROR"


@dataclass(frozen=True)
class Observation:
    """What the model sees after one tool call (controller §3)."""

    tool: str
    accepted: bool
    policy: str | None
    reason: str | None
    message: str
    data: dict
    budget_remaining: int

    def to_json(self) -> str:
        """Compact JSON of the observation; this is what the model sees."""
        return json.dumps(asdict(self), separators=(",", ":"))


@dataclass(frozen=True)
class Approval:
    """A request that passed validation and may be executed (controller §3)."""

    tool: str
    args: BaseModel


@dataclass(frozen=True)
class TraceEntry:
    """One handled call in the append-only trace (architecture §8)."""

    step: int
    tool: str
    args: dict | str
    accepted: bool
    policy: str | None
    reason: str | None
    message: str
    budget_remaining: int
    board_depth: int


# Domain rejection codes from tools and the policy that covers each one
# (controller §5). The KB codes can only be detected during execution (P8).
_POLICY_FOR_REASON = {
    "GIVEN_CELL": "P4",
    "CELL_FILLED": "P5",
    "CONFLICT": "P6",
    "EMPTY_STACK": "P7",
    "PARSE_ERROR": "P8",
    "INVALID_SYMBOL": "P8",
    "TOO_LONG": "P8",
    "INCONSISTENT": "P8",
    "KB_INCONSISTENT": "P8",
    "INVALID_SOLUTION": "P9",
}


class Controller:
    """Validates, dispatches, charges, traces and ends runs (controller §4)."""

    def __init__(self, session: Session, config: Config) -> None:
        self._session = session
        self._config = config
        self._actions_used = 0
        self._consecutive_rejections = 0
        self._trace: list[TraceEntry] = []
        self._solved = False
        self._no_action = False
        self._model_error: Exception | None = None
        self._terminal_status: TerminalStatus | None = None
        self._terminal_reason: str | None = None
        # The most recent approval and the raw args it was validated from, so
        # the trace can record the args exactly as received (architecture §8).
        self._last_approval: Approval | None = None
        self._last_raw_args: dict | str | None = None

    # ------------------------------------------------------------ read-only properties

    @property
    def actions_used(self) -> int:
        return self._actions_used

    @property
    def budget_remaining(self) -> int:
        return max(0, self._config.max_actions - self._actions_used)

    @property
    def consecutive_rejections(self) -> int:
        return self._consecutive_rejections

    @property
    def terminal_status(self) -> TerminalStatus | None:
        return self._terminal_status

    @property
    def terminal_reason(self) -> str | None:
        return self._terminal_reason

    @property
    def trace(self) -> tuple[TraceEntry, ...]:
        return tuple(self._trace)

    # ------------------------------------------------------------ §5 validation

    def validate(self, tool_name: str, raw_args: dict | str) -> Approval | Observation:
        """Apply policies P1-P7 and P9 with read-only checks (controller §5).

        Returns an ``Approval`` (changing nothing but the budget) or a rejection
        ``Observation`` (also recorded in the trace).
        """
        if self._terminal_status is not None:
            return self._reject(tool_name, raw_args, "P1", "TERMINAL",
                                f"The run has already ended ({self._terminal_status.value}).")
        self._actions_used += 1   # charged once per call, before any other check (§7)

        if tool_name not in TOOL_SCHEMAS:
            return self._reject(tool_name, raw_args, "P2", "UNKNOWN_TOOL",
                                f"Unknown tool {tool_name!r}.")
        args, error = _parse_args(tool_name, raw_args)
        if args is None:
            return self._reject(tool_name, raw_args, "P3", "BAD_ARGS", f"Invalid arguments: {error}")

        rejection = self._domain_rejection(tool_name, args)
        if rejection is not None:
            reason, message, data = rejection
            return self._reject(tool_name, raw_args, _POLICY_FOR_REASON[reason], reason, message, data)
        approval = Approval(tool_name, args)
        self._last_approval, self._last_raw_args = approval, raw_args
        return approval

    def _domain_rejection(self, tool_name: str, args: BaseModel) -> tuple[str, str, dict] | None:
        """P4-P7 and P9 using read-only board queries; ``(reason, message, data)`` or None."""
        board = self._session.board
        if tool_name == "place_number":
            r, c, d = args.row, args.col, args.digit
            if board.is_given(r, c):
                return "GIVEN_CELL", f"r{r}c{c} is a given and cannot be changed.", {"reason": "GIVEN_CELL"}
            if board.cell(r, c) != 0:
                return ("CELL_FILLED", f"r{r}c{c} already holds {board.cell(r, c)}; undo it first.",
                        {"reason": "CELL_FILLED"})
            if d not in board.candidates(r, c):
                return "CONFLICT", f"{d} already in {_conflicting_unit(board, r, c, d)}", {"reason": "CONFLICT"}
        elif tool_name == "undo" and board.depth == 0:
            return "EMPTY_STACK", "There is no placement to undo.", {"reason": "EMPTY_STACK"}
        elif tool_name == "submit":
            result = validate_solution(self._session.original_puzzle, board.grid())
            if not result.valid:
                return ("INVALID_SOLUTION", f"Not a valid solution ({len(result.reasons)} problems).",
                        invalid_solution_data(result))
        return None

    # ------------------------------------------------------------ §6 execution

    def execute(self, approval: Approval) -> Observation:
        """Run an approved call through ``tools`` and record it (controller §6).

        A rejection by ``logic`` becomes policy P8. Any other domain rejection
        here would mean a validation gap; it is still reported under the
        policy that covers its reason, and the tools guarantee nothing changed.
        """
        if approval is self._last_approval:
            raw_args = self._last_raw_args
        else:
            raw_args = approval.args.model_dump()
        self._last_approval = self._last_raw_args = None

        outcome = execute_tool(self._session, approval.tool, approval.args)
        if not outcome.accepted:
            policy = _POLICY_FOR_REASON[outcome.reason]
            return self._reject(approval.tool, raw_args, policy, outcome.reason, outcome.message,
                                outcome.data)
        if approval.tool == "submit":
            self._solved = True
        return self._record(approval.tool, raw_args, True, None, None, outcome.message, outcome.data)

    def handle(self, tool_name: str, raw_args: dict | str) -> Observation:
        """``validate`` followed, on approval, by ``execute``."""
        result = self.validate(tool_name, raw_args)
        if isinstance(result, Approval):
            return self.execute(result)
        return result

    # ------------------------------------------------------------ §8 extra calls

    def reject_extra_call(self, tool_name: str, raw_args: dict | str) -> Observation:
        """Reject a second or later call in one model turn (P10); it is charged."""
        self._actions_used += 1
        return self._reject(tool_name, raw_args, "P10", "ONE_CALL_PER_TURN",
                            "Only the first tool call in a reply is executed; make one call per reply.")

    # ------------------------------------------------------------ §9 terminal checks

    def record_no_action(self) -> None:
        """Mark that the model's last response contained no tool call (not charged)."""
        self._no_action = True

    def record_model_error(self, error: Exception) -> None:
        """Mark that the model call raised (not charged)."""
        self._model_error = error

    def check_terminal(self) -> TerminalStatus | None:
        """Apply the ordered terminal checks of controller §9; the first one is final."""
        if self._terminal_status is not None:
            return self._terminal_status
        config = self._config
        if self._solved:
            status, reason = TerminalStatus.SOLVED, "The submitted board was validated as a correct solution."
        elif self._actions_used >= config.max_actions:
            status, reason = TerminalStatus.ACTION_LIMIT, f"The action budget of {config.max_actions} was used up."
        elif self._consecutive_rejections >= config.max_consecutive_rejections:
            status, reason = (TerminalStatus.REJECTION_LIMIT,
                              f"{self._consecutive_rejections} consecutive tool calls were rejected.")
        elif self._no_action:
            status, reason = TerminalStatus.NO_ACTION, "The model replied without a tool call."
        elif self._model_error is not None:
            status, reason = TerminalStatus.MODEL_ERROR, f"The model call failed: {self._model_error}"
        else:
            return None
        self._terminal_status, self._terminal_reason = status, reason
        return status

    # ------------------------------------------------------------ accounting (§7)

    def _reject(self, tool: str, raw_args: dict | str, policy: str, reason: str, message: str,
                data: dict | None = None) -> Observation:
        """Record a rejection; ``data`` defaults to ``{"reason": reason}``."""
        return self._record(tool, raw_args, False, policy, reason, message,
                            data if data is not None else {"reason": reason})

    def _record(self, tool: str, raw_args: dict | str, accepted: bool, policy: str | None,
                reason: str | None, message: str, data: dict) -> Observation:
        """Update the streak, append one trace entry and build the observation (§7)."""
        if policy != "P1":   # P1 calls happen after the run ended and do not count
            self._consecutive_rejections = 0 if accepted else self._consecutive_rejections + 1
        self._no_action = False   # NO_ACTION refers to the model's latest response only
        self._trace.append(TraceEntry(
            step=len(self._trace) + 1,
            tool=tool,
            args=raw_args,
            accepted=accepted,
            policy=policy,
            reason=reason,
            message=message,
            budget_remaining=self.budget_remaining,
            board_depth=self._session.board.depth,
        ))
        return Observation(tool, accepted, policy, reason, message, data, self.budget_remaining)


def _parse_args(tool_name: str, raw_args: dict | str) -> tuple[BaseModel | None, str]:
    """Validate raw args against the tool schema (P3); return ``(args, error)``."""
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except json.JSONDecodeError as error:
            return None, f"arguments are not valid JSON ({error.msg})"
    if not isinstance(raw_args, dict):
        return None, "arguments must be a JSON object"
    try:
        return TOOL_SCHEMAS[tool_name].model_validate(raw_args), ""
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "arguments"
        return None, f"{location}: {first['msg']}"


def _conflicting_unit(board, r: int, c: int, d: int) -> str:
    """Name the unit of (r, c) that already holds ``d`` (read-only views)."""
    if d in board.row(r):
        return f"row {r}"
    if d in board.col(c):
        return f"column {c}"
    return f"box {box_of(r, c)}"
