# Propositional Logic Package

`proplogic` is a standard-library-only Python package for parsing propositional
formulas, converting formulas to conjunctive normal form (CNF), storing a
knowledge base, and checking entailment with DPLL refutation.

The package supports two uses:

- import `proplogic` from a Python program;
- run `python3 -m proplogic` to test formulas interactively or in batch mode.

## Public Python API

Import these public names from the package. `proplogic.core` is an internal
implementation module.

```python
from proplogic import Clause, KnowledgeBase, Literal, atom, to_cnf
```

The public API contains:

| Name | Purpose |
|---|---|
| `Literal(symbol, positive=True)` | Construct an immutable propositional symbol with a positive or negative polarity. |
| `Clause` | Type alias for `frozenset[Literal]`, representing an immutable disjunction. |
| `atom(symbol)` | Construct a positive literal. |
| `to_cnf(formula)` | Parse a formula string and return equivalent CNF clauses. |
| `KnowledgeBase` | Store clauses and answer consistency and entailment queries. |

## Literals And Clauses

Create a positive literal with `atom` or `Literal`. Pass `False` as the second
`Literal` argument to construct a negative literal. The `~` operator and
`negated()` return a new literal with the opposite polarity.

```python
from proplogic import Clause, Literal, atom

enabled = atom("enabled")
also_enabled = Literal("enabled")
disabled = Literal("enabled", False)

assert enabled == also_enabled
assert ~enabled == disabled
assert enabled.negated() == disabled

choice: Clause = frozenset((atom("option_a"), atom("option_b")))
```

`Literal` values are immutable, hashable, and orderable. Equality includes both
the symbol and polarity.

## Formula Syntax

Symbols begin with an ASCII letter or underscore. Remaining characters may be
ASCII letters, digits, or underscores. Examples include `ready`, `item_0_2`,
and `_temporary`.

The words `NOT`, `AND`, `OR`, `IMPLIES`, and `IFF` are reserved in every
capitalization and cannot be used as symbols.

| Operation | Symbolic syntax | Word syntax | Example |
|---|---|---|---|
| Negation | `~p` or `!p` | `NOT p` | `NOT unavailable` |
| Conjunction | `p & q` | `p AND q` | `ready AND authorized` |
| Disjunction | `p \| q` | `p OR q` | `option_a OR option_b` |
| Implication | `p -> q` | `p IMPLIES q` | `enabled -> ready` |
| Biconditional | `p <-> q` | `p IFF q` | `active IFF switch_on` |

Word operators are case-insensitive. Parentheses may be used at any level.

Operator precedence, from highest to lowest, is:

1. negation;
2. conjunction;
3. disjunction;
4. implication; and
5. biconditional.

Implication is right-associative. Other binary operators are left-associative.
For example, `a -> b -> c` means `a -> (b -> c)`, and `a OR b AND c` means
`a OR (b AND c)`. Use parentheses whenever grouping should be explicit.

## Building A Knowledge Base

Create an empty knowledge base or initialize one from iterables of literals:

```python
from proplogic import KnowledgeBase, atom

a = atom("a")
b = atom("b")
empty = KnowledgeBase()
initialized = KnowledgeBase(((a,), (~a, b)))
```

Each inner iterable is one disjunctive clause. The outer iterable is their
conjunction.

Add complete formulas with `add_formula`:

```python
from proplogic import KnowledgeBase

kb = KnowledgeBase()
kb.add_formula("enabled -> ready")
kb.add_formula("enabled")
```

Each formula is parsed and converted to CNF when it is added. Separate calls
are conjoined.

Add facts and clauses directly when the information is already in CNF:

```python
from proplogic import KnowledgeBase, atom

option_a = atom("option_a")
option_b = atom("option_b")
option_c = atom("option_c")

kb = KnowledgeBase()
kb.add_clause(option_a, option_b, option_c)
kb.add_fact(~option_b)
kb.add_fact(~option_c)
```

`add_clause(a, b, c)` means `a OR b OR c`. Separate clauses are joined by
`AND`. The `~` operator negates a `Literal`; it does not mutate the original.

`add_clause` rejects an empty clause and values other than `Literal`. It ignores
tautological clauses containing both a literal and its negation. Adding an
existing clause again has no effect. The read-only `clauses` property returns
the current clauses as a tuple:

```python
stored = kb.clauses
```

Use `clear()` to remove every stored clause:

```python
kb.clear()
```

## Asking Questions

`entails` accepts either a `Literal` or a formula string:

```python
kb = KnowledgeBase()
kb.add_formula("a -> b")
kb.add_formula("a")

assert kb.entails("b")
assert kb.entails("a AND b")
assert kb.entails(atom("b"))
assert not kb.entails("c")
```

Entailment uses classical refutation. `KB` entails query `q` exactly when
`KB AND NOT q` is unsatisfiable. In a consistent knowledge base, an unknown
formula `p` and `NOT p` both produce `False` entailment results.

If a query has already been converted, use `entails_cnf`:

```python
query = to_cnf("a AND (b OR c)")
result = kb.entails_cnf(query)
```

An empty CNF sequence represents `True`. An empty clause represents `False`.
Every knowledge base entails `True`; only an inconsistent knowledge base
entails `False`.

Check consistency directly:

```python
if not kb.is_consistent():
    print("The knowledge base contains a contradiction.")
```

Under classical logic, an inconsistent knowledge base entails every formula.
Check consistency while developing an encoding and before relying on query
results.

## Inspecting CNF

`to_cnf` returns a tuple of immutable clauses:

```python
clauses = to_cnf("approved OR (ready AND verified)")
```

This formula becomes the equivalent CNF:

```text
(approved OR ready) AND (approved OR verified)
```

CNF distribution can produce an exponential number of clauses. Use short
formulas when possible. Constraints already expressed as clauses should use
`add_clause` to avoid unnecessary parsing and conversion.

`to_cnf` removes duplicate clauses and tautological clauses. It represents
logical `True` as an empty tuple and logical `False` as a tuple containing one
empty clause. Formula syntax does not include `TRUE` or `FALSE` constants; these
representations can arise during conversion or direct CNF queries.

## Errors And Input Validation

The public API raises `TypeError` when a value has the wrong Python type and
`ValueError` when a string, symbol, clause, or formula has invalid content.
Formula errors include a character position when one is available. Examples of
invalid input include an empty formula, an unmatched parenthesis, a reserved
word used as a symbol, and an empty clause passed to `add_clause`.

`entails_cnf` accepts any iterable of clause iterables. Every clause member must
be a `Literal`. It permits an empty outer iterable to represent `True` and an
empty inner iterable to represent `False`.

## Inference And Performance

Entailment uses DPLL satisfiability checking by refutation. The implementation
does not expose models, proofs, incremental solving, or clause removal. Each
entailment and consistency call solves from the current stored clauses.

Propositional satisfiability is exponential in the worst case. Keep formulas
and symbol sets focused on the current problem, add constraints already in CNF
with `add_clause`, and avoid repeating a query when its result can be retained
by the calling program.

## Interactive CLI

From the directory containing the `proplogic` folder, run:

```sh
python3 -m proplogic
```

Available commands:

| Command | Effect |
|---|---|
| `tell FORMULA` | Add a formula to the current knowledge base. |
| `ask FORMULA` | Test whether the current knowledge base entails a formula. |
| `cnf FORMULA` | Display the formula's converted CNF. |
| `clauses` | Display all stored clauses. |
| `consistent` | Report whether the knowledge base is consistent. |
| `clear` | Remove all stored clauses. |
| `help` | Display command help. |
| `quit` or `exit` | Exit the tool. |

Example session:

```text
Propositional Logic Tester. Type 'help' for commands.
logic> tell a -> b
added
logic> tell a
added
logic> ask b
entailed
logic> ask c
not entailed
logic> cnf a OR (b AND c)
(a | b) & (a | c)
logic> consistent
consistent
```

## Batch CLI

Quote formulas so the shell does not interpret their operators:

```sh
python3 -m proplogic \
  --tell "a -> b" \
  --tell "a" \
  --ask "b" \
  --ask "c" \
  --check-consistency
```

Output:

```text
ENTAILED: b
NOT ENTAILED: c
CONSISTENT
```

Convert a formula without building a knowledge base:

```sh
python3 -m proplogic --cnf "a OR (b AND c)"
```

Options `--tell`, `--ask`, and `--cnf` may be repeated. Batch processing adds
all `--tell` formulas first, displays all `--cnf` results, answers all `--ask`
queries, and then performs the consistency check. Add `--interactive` to enter
the interactive tester with the batch knowledge base still loaded.

## Running Package Tests

From the directory containing `proplogic`, run:

```sh
python3 -m unittest discover -v -s proplogic/tests -t .
```
