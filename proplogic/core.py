"""Propositional formula conversion and inference implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True, order=True)
class Literal:
    symbol: str
    positive: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str):
            raise TypeError("literal symbol must be a string")
        if not _valid_symbol(self.symbol):
            raise ValueError(f"invalid literal symbol: {self.symbol!r}")

    def negated(self) -> Literal:
        return Literal(self.symbol, not self.positive)

    def __invert__(self) -> Literal:
        return self.negated()


Clause = frozenset[Literal]


_RESERVED_WORDS = frozenset(("NOT", "AND", "OR", "IMPLIES", "IFF"))


def _valid_symbol(symbol: str) -> bool:
    if not symbol or symbol.upper() in _RESERVED_WORDS:
        return False
    first = symbol[0]
    if not ((first.isascii() and first.isalpha()) or first == "_"):
        return False
    return all(
        (character.isascii() and character.isalnum()) or character == "_"
        for character in symbol[1:]
    )


def atom(symbol: str) -> Literal:
    return Literal(symbol)


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    position: int


@dataclass(frozen=True)
class _Formula:
    operator: str
    value: str | None = None
    operands: tuple[_Formula, ...] = ()


def to_cnf(formula: str) -> tuple[Clause, ...]:
    """Parse a propositional formula and return equivalent CNF clauses."""
    parsed = _parse_formula(formula)
    nnf = _to_nnf(_without_implications(parsed))
    return _cnf_clauses(nnf)


class KnowledgeBase:
    """A CNF knowledge base with entailment implemented by DPLL refutation."""

    def __init__(self, clauses: Iterable[Iterable[Literal]] = ()) -> None:
        self._clauses: list[Clause] = []
        for clause in clauses:
            self.add_clause(*clause)

    @property
    def clauses(self) -> tuple[Clause, ...]:
        return tuple(self._clauses)

    def add_clause(self, *literals: Literal) -> None:
        if not literals:
            raise ValueError("a clause must contain at least one literal")
        if not all(isinstance(literal, Literal) for literal in literals):
            raise TypeError("clauses may contain only Literal values")
        clause = frozenset(literals)
        if any(literal.negated() in clause for literal in clause):
            return
        if clause not in self._clauses:
            self._clauses.append(clause)

    def add_fact(self, literal: Literal) -> None:
        self.add_clause(literal)

    def clear(self) -> None:
        """Remove every clause from the knowledge base."""
        self._clauses.clear()

    def add_formula(self, formula: str) -> None:
        """Parse a propositional formula and add its CNF clauses."""
        for clause in to_cnf(formula):
            self.add_clause(*clause)

    def entails(self, query: Literal | str) -> bool:
        """Return whether the knowledge base entails a literal or formula."""
        if isinstance(query, Literal):
            negated_query = (frozenset((query.negated(),)),)
        elif isinstance(query, str):
            parsed = _parse_formula(query)
            negated = _Formula("not", operands=(parsed,))
            negated_query = _cnf_clauses(
                _to_nnf(_without_implications(negated))
            )
        else:
            raise TypeError("query must be a Literal or formula string")
        return not _satisfiable((*self._clauses, *negated_query))

    def entails_cnf(self, clauses: Iterable[Iterable[Literal]]) -> bool:
        """Return whether the knowledge base entails every supplied CNF clause."""
        normalized: list[Clause] = []
        try:
            iterator = iter(clauses)
        except TypeError as error:
            raise TypeError("CNF query must be an iterable of clauses") from error
        for literals in iterator:
            try:
                items = tuple(literals)
            except TypeError as error:
                raise TypeError("each CNF clause must be an iterable") from error
            if not all(isinstance(literal, Literal) for literal in items):
                raise TypeError("clauses may contain only Literal values")
            normalized.append(frozenset(items))

        for clause in normalized:
            negated_clause = tuple(
                frozenset((literal.negated(),)) for literal in clause
            )
            if _satisfiable((*self._clauses, *negated_clause)):
                return False
        return True

    def is_consistent(self) -> bool:
        return _satisfiable(tuple(self._clauses))


def _parse_formula(formula: str) -> _Formula:
    if not isinstance(formula, str):
        raise TypeError("formula must be a string")
    return _FormulaParser(_tokenize(formula)).parse()


def _tokenize(formula: str) -> tuple[_Token, ...]:
    tokens: list[_Token] = []
    index = 0
    symbolic = {
        "(": "LPAREN",
        ")": "RPAREN",
        "~": "NOT",
        "!": "NOT",
        "&": "AND",
        "|": "OR",
    }
    keywords = {word: word for word in _RESERVED_WORDS}

    while index < len(formula):
        if formula[index].isspace():
            index += 1
            continue
        if formula.startswith("<->", index):
            tokens.append(_Token("IFF", "<->", index))
            index += 3
            continue
        if formula.startswith("->", index):
            tokens.append(_Token("IMPLIES", "->", index))
            index += 2
            continue
        if formula[index] in symbolic:
            value = formula[index]
            tokens.append(_Token(symbolic[value], value, index))
            index += 1
            continue
        if (
            formula[index].isascii() and formula[index].isalpha()
        ) or formula[index] == "_":
            end = index + 1
            while end < len(formula) and (
                (formula[end].isascii() and formula[end].isalnum())
                or formula[end] == "_"
            ):
                end += 1
            value = formula[index:end]
            tokens.append(_Token(keywords.get(value.upper(), "SYMBOL"), value, index))
            index = end
            continue
        raise ValueError(
            f"Unexpected character {formula[index]!r} at position {index}"
        )

    tokens.append(_Token("EOF", "", len(formula)))
    return tuple(tokens)


class _FormulaParser:
    def __init__(self, tokens: tuple[_Token, ...]) -> None:
        self._tokens = tokens
        self._index = 0

    def parse(self) -> _Formula:
        if self._current.kind == "EOF":
            raise ValueError("Formula cannot be empty")
        formula = self._parse_iff()
        self._expect("EOF")
        return formula

    @property
    def _current(self) -> _Token:
        return self._tokens[self._index]

    def _accept(self, kind: str) -> _Token | None:
        if self._current.kind != kind:
            return None
        token = self._current
        self._index += 1
        return token

    def _expect(self, kind: str) -> _Token:
        token = self._accept(kind)
        if token is None:
            current = self._current
            raise ValueError(
                f"Expected {kind} at position {current.position}; "
                f"found {current.value or 'end of formula'!r}"
            )
        return token

    def _parse_iff(self) -> _Formula:
        left = self._parse_implication()
        while self._accept("IFF") is not None:
            left = _Formula("iff", operands=(left, self._parse_implication()))
        return left

    def _parse_implication(self) -> _Formula:
        left = self._parse_or()
        if self._accept("IMPLIES") is not None:
            return _Formula("implies", operands=(left, self._parse_implication()))
        return left

    def _parse_or(self) -> _Formula:
        left = self._parse_and()
        while self._accept("OR") is not None:
            left = _Formula("or", operands=(left, self._parse_and()))
        return left

    def _parse_and(self) -> _Formula:
        left = self._parse_unary()
        while self._accept("AND") is not None:
            left = _Formula("and", operands=(left, self._parse_unary()))
        return left

    def _parse_unary(self) -> _Formula:
        if self._accept("NOT") is not None:
            return _Formula("not", operands=(self._parse_unary(),))
        return self._parse_primary()

    def _parse_primary(self) -> _Formula:
        symbol = self._accept("SYMBOL")
        if symbol is not None:
            return _Formula("symbol", value=symbol.value)
        if self._accept("LPAREN") is not None:
            formula = self._parse_iff()
            self._expect("RPAREN")
            return formula
        current = self._current
        raise ValueError(
            f"Expected a symbol or '(' at position {current.position}; "
            f"found {current.value or 'end of formula'!r}"
        )


def _without_implications(formula: _Formula) -> _Formula:
    if formula.operator == "symbol":
        return formula
    operands = tuple(_without_implications(item) for item in formula.operands)
    if formula.operator == "not":
        return _Formula("not", operands=operands)
    if formula.operator in ("and", "or"):
        return _Formula(formula.operator, operands=operands)
    left, right = operands
    if formula.operator == "implies":
        return _Formula(
            "or", operands=(_Formula("not", operands=(left,)), right)
        )
    if formula.operator == "iff":
        left_to_right = _Formula(
            "or", operands=(_Formula("not", operands=(left,)), right)
        )
        right_to_left = _Formula(
            "or", operands=(_Formula("not", operands=(right,)), left)
        )
        return _Formula("and", operands=(left_to_right, right_to_left))
    raise AssertionError(f"Unknown formula operator: {formula.operator}")


def _to_nnf(formula: _Formula, negated: bool = False) -> _Formula:
    if formula.operator == "symbol":
        if negated:
            return _Formula("not", operands=(formula,))
        return formula
    if formula.operator == "not":
        return _to_nnf(formula.operands[0], not negated)
    operator = formula.operator
    if negated:
        operator = "or" if operator == "and" else "and"
    return _Formula(
        operator,
        operands=tuple(_to_nnf(item, negated) for item in formula.operands),
    )


def _cnf_clauses(formula: _Formula) -> tuple[Clause, ...]:
    if formula.operator == "symbol":
        assert formula.value is not None
        return (frozenset((Literal(formula.value),)),)
    if formula.operator == "not":
        symbol = formula.operands[0]
        assert symbol.operator == "symbol" and symbol.value is not None
        return (frozenset((Literal(symbol.value, False),)),)

    left = _cnf_clauses(formula.operands[0])
    right = _cnf_clauses(formula.operands[1])
    if formula.operator == "and":
        return _unique_clauses((*left, *right))
    if formula.operator == "or":
        distributed: list[Clause] = []
        for left_clause in left:
            for right_clause in right:
                clause = left_clause | right_clause
                if not any(literal.negated() in clause for literal in clause):
                    distributed.append(clause)
        return _unique_clauses(distributed)
    raise AssertionError(f"Unexpected NNF operator: {formula.operator}")


def _unique_clauses(clauses: Iterable[Clause]) -> tuple[Clause, ...]:
    unique: list[Clause] = []
    for clause in clauses:
        if clause not in unique:
            unique.append(clause)
    return tuple(unique)


def _satisfiable(clauses: tuple[Clause, ...]) -> bool:
    symbols = {literal.symbol for clause in clauses for literal in clause}
    return _dpll(clauses, symbols, {})


def _dpll(
    clauses: tuple[Clause, ...],
    symbols: set[str],
    model: Mapping[str, bool],
) -> bool:
    unresolved: list[Clause] = []
    for clause in clauses:
        value = _clause_value(clause, model)
        if value is False:
            return False
        if value is None:
            unresolved.append(clause)
    if not unresolved:
        return True

    unit = _unit_literal(unresolved, model)
    if unit is not None:
        next_model = dict(model)
        next_model[unit.symbol] = unit.positive
        return _dpll(clauses, symbols - {unit.symbol}, next_model)

    pure = _pure_literal(unresolved, symbols)
    if pure is not None:
        next_model = dict(model)
        next_model[pure.symbol] = pure.positive
        return _dpll(clauses, symbols - {pure.symbol}, next_model)

    symbol = min(symbols)
    remaining = symbols - {symbol}
    for value in (True, False):
        next_model = dict(model)
        next_model[symbol] = value
        if _dpll(clauses, remaining, next_model):
            return True
    return False


def _clause_value(clause: Clause, model: Mapping[str, bool]) -> bool | None:
    unresolved = False
    for literal in clause:
        value = model.get(literal.symbol)
        if value is None:
            unresolved = True
        elif value is literal.positive:
            return True
    return None if unresolved else False


def _unit_literal(
    clauses: Iterable[Clause], model: Mapping[str, bool]
) -> Literal | None:
    for clause in clauses:
        unknown = [literal for literal in clause if literal.symbol not in model]
        if len(unknown) == 1 and all(
            model[literal.symbol] is not literal.positive
            for literal in clause
            if literal.symbol in model
        ):
            return unknown[0]
    return None


def _pure_literal(clauses: Iterable[Clause], symbols: set[str]) -> Literal | None:
    polarities: dict[str, set[bool]] = {symbol: set() for symbol in symbols}
    for clause in clauses:
        for literal in clause:
            if literal.symbol in polarities:
                polarities[literal.symbol].add(literal.positive)
    for symbol in sorted(symbols):
        if len(polarities[symbol]) == 1:
            return Literal(symbol, polarities[symbol].pop())
    return None
