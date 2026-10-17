"""Tests and usage examples for the provided inference engine."""

import unittest

from proplogic import KnowledgeBase, Literal, atom, to_cnf


class KnowledgeBaseTests(unittest.TestCase):
    def test_overlap_style_inference_entails_remaining_literal(self) -> None:
        fragile_a = atom("fragile_a")
        fragile_b = atom("fragile_b")
        fragile_c = atom("fragile_c")
        kb = KnowledgeBase()
        kb.add_clause(fragile_a, fragile_b, fragile_c)
        kb.add_fact(~fragile_b)
        kb.add_fact(~fragile_c)

        self.assertTrue(kb.entails(fragile_a))
        self.assertFalse(kb.entails(~fragile_a))

    def test_unknown_literal_is_not_entailed_in_either_direction(self) -> None:
        kb = KnowledgeBase()
        known = atom("known")
        unknown = atom("unknown")
        kb.add_fact(known)

        self.assertFalse(kb.entails(unknown))
        self.assertFalse(kb.entails(~unknown))

    def test_literal_symbols_follow_formula_identifier_rules(self) -> None:
        self.assertEqual(atom("fragile_0_2").symbol, "fragile_0_2")
        with self.assertRaises(TypeError):
            Literal(7)  # type: ignore[arg-type]
        for invalid in ("", "2fragile", "fragile-tile", "AND", "α"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    atom(invalid)

    def test_inconsistent_facts_are_detected(self) -> None:
        tile = atom("stable_1_1")
        kb = KnowledgeBase()
        kb.add_fact(tile)
        kb.add_fact(~tile)

        self.assertFalse(kb.is_consistent())

    def test_tautological_clause_is_ignored(self) -> None:
        tile = atom("slippery_2_3")
        kb = KnowledgeBase()
        kb.add_clause(tile, ~tile)

        self.assertEqual(kb.clauses, ())
        self.assertTrue(kb.is_consistent())

    def test_formula_is_parsed_and_added_to_knowledge_base(self) -> None:
        kb = KnowledgeBase()
        kb.add_formula(
            "(fragile_a OR fragile_b OR fragile_c) "
            "AND NOT fragile_b AND NOT fragile_c"
        )

        self.assertTrue(kb.entails(atom("fragile_a")))

    def test_implication_is_converted_to_cnf(self) -> None:
        stable = atom("stable_0_0")
        fragile = atom("fragile_0_0")
        kb = KnowledgeBase()
        kb.add_formula("stable_0_0 -> ~fragile_0_0")
        kb.add_fact(stable)

        self.assertTrue(kb.entails(~fragile))

    def test_entails_accepts_formula_string(self) -> None:
        kb = KnowledgeBase()
        kb.add_formula("a -> b")
        kb.add_formula("a")

        self.assertTrue(kb.entails("b AND (a OR c)"))
        self.assertFalse(kb.entails("b AND c"))

    def test_entails_formula_supports_implication_and_tautology(self) -> None:
        kb = KnowledgeBase()
        kb.add_formula("safe")

        self.assertTrue(kb.entails("inspected -> safe"))
        self.assertTrue(kb.entails("fragile OR NOT fragile"))
        self.assertFalse(kb.entails("safe AND NOT safe"))

    def test_entails_accepts_preconverted_cnf(self) -> None:
        kb = KnowledgeBase()
        kb.add_formula("a AND b")

        self.assertTrue(kb.entails_cnf(to_cnf("a AND (b OR c)")))
        self.assertFalse(kb.entails_cnf(to_cnf("a AND c")))

    def test_empty_cnf_query_represents_true(self) -> None:
        kb = KnowledgeBase()

        self.assertTrue(kb.entails_cnf(()))

    def test_empty_clause_query_represents_false(self) -> None:
        consistent = KnowledgeBase()
        inconsistent = KnowledgeBase()
        inconsistent.add_formula("a AND NOT a")

        self.assertFalse(consistent.entails_cnf(((),)))
        self.assertTrue(inconsistent.entails_cnf(((),)))

    def test_inconsistent_knowledge_base_entails_every_query_form(self) -> None:
        kb = KnowledgeBase()
        kb.add_formula("a AND NOT a")

        self.assertTrue(kb.entails(atom("unknown")))
        self.assertTrue(kb.entails("unknown AND NOT unknown"))

    def test_tautological_cnf_clause_is_always_entailed(self) -> None:
        kb = KnowledgeBase()
        a = atom("a")

        self.assertTrue(kb.entails_cnf(((a, ~a),)))
        self.assertFalse(kb.entails_cnf(((a, ~a), (atom("b"),))))

    def test_entails_cnf_rejects_malformed_inputs(self) -> None:
        kb = KnowledgeBase()

        with self.assertRaisesRegex(TypeError, "iterable of clauses"):
            kb.entails_cnf(7)  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "each CNF clause"):
            kb.entails_cnf((7,))  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "only Literal"):
            kb.entails_cnf((([],),))  # type: ignore[list-item]

    def test_biconditional_propagates_in_both_directions(self) -> None:
        kb = KnowledgeBase()
        kb.add_formula("traction_enabled IFF traction_switch_on")
        kb.add_formula("traction_switch_on")

        self.assertTrue(kb.entails(atom("traction_enabled")))

    def test_converter_distributes_disjunction_over_conjunction(self) -> None:
        clauses = set(to_cnf("safe OR (stable AND inspected)"))

        self.assertEqual(
            clauses,
            {
                frozenset((Literal("safe"), Literal("stable"))),
                frozenset((Literal("safe"), Literal("inspected"))),
            },
        )

    def test_operator_precedence_matches_documented_order(self) -> None:
        kb = KnowledgeBase()
        kb.add_formula("a OR b AND c")
        kb.add_formula("NOT a")

        self.assertTrue(kb.entails(atom("b")))
        self.assertTrue(kb.entails(atom("c")))

    def test_implication_is_right_associative(self) -> None:
        kb = KnowledgeBase()
        kb.add_formula("a -> b -> c")
        kb.add_formula("NOT a AND b AND NOT c")

        self.assertTrue(kb.is_consistent())

    def test_symbolic_operators_and_repeated_negation(self) -> None:
        kb = KnowledgeBase()
        kb.add_formula("!!a & (a <-> b) & (b -> c)")

        self.assertTrue(kb.entails(atom("c")))

    def test_tautology_and_contradiction_conversion(self) -> None:
        self.assertEqual(to_cnf("a OR NOT a"), ())

        kb = KnowledgeBase()
        kb.add_formula("a AND NOT a")
        self.assertFalse(kb.is_consistent())

    def test_invalid_formula_reports_parse_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            to_cnf("")

        with self.assertRaisesRegex(ValueError, "Expected"):
            to_cnf("stable AND")

        with self.assertRaisesRegex(ValueError, "Unexpected character"):
            to_cnf("stable + slippery")

        with self.assertRaisesRegex(ValueError, "Unexpected character"):
            to_cnf("stable_α")


if __name__ == "__main__":
    unittest.main()
