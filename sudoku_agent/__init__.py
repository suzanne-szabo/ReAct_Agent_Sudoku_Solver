"""Bounded ReAct Sudoku agent built with LangGraph (see specs/architecture.md).

This package initializer deliberately imports nothing, so that importing one
module (for example ``sudoku_agent.validation``) never pulls in another
(architecture §4.2: the validator must stay independent of ``board``).
"""
