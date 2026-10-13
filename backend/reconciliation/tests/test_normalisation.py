"""Unit tests for the normalisation rules in Section 6."""

from django.test import SimpleTestCase

from reconciliation.domain.money import AmountError, parse_amount
from reconciliation.domain.normalisation import (
    contains_name,
    contains_reference,
    normalise_name,
    normalise_reference,
)


class NormaliseReferenceTests(SimpleTestCase):
    def test_uppercases_and_strips_everything_but_letters_and_digits(self):
        self.assertEqual(normalise_reference("cc-1003"), "CC1003")
        self.assertEqual(normalise_reference(" cc 1003 / "), "CC1003")
        self.assertEqual(normalise_reference(None), "")

    def test_reference_is_found_as_a_substring_of_the_normalised_haystack(self):
        self.assertTrue(contains_reference("WIRE REF CC-1003 THANKS", "CC1003"))
        self.assertTrue(contains_reference("wire/refcc1003", "CC1003"))
        self.assertFalse(contains_reference("WIRE REF CC-1004", "CC1003"))
        self.assertFalse(contains_reference("WIRE REF CC-1003", ""))


class NormaliseNameTests(SimpleTestCase):
    def test_collapses_punctuation_and_drops_one_trailing_entity_suffix(self):
        self.assertEqual(normalise_name("Haller  Capital, LLC."), "HALLER CAPITAL")
        self.assertEqual(normalise_name("Meridian Partners LP"), "MERIDIAN PARTNERS")
        self.assertEqual(normalise_name("Acme Ltd"), "ACME")
        self.assertEqual(normalise_name("Globex Inc"), "GLOBEX")

    def test_keeps_trust(self):
        self.assertEqual(normalise_name("Patel Family Trust"), "PATEL FAMILY TRUST")

    def test_keeps_a_suffix_that_is_the_whole_name(self):
        self.assertEqual(normalise_name("LLC"), "LLC")

    def test_name_must_appear_as_whole_words(self):
        self.assertTrue(contains_name("WIRE INCOMING PATEL FAMILY TRUST REF X", "PATEL FAMILY TRUST"))
        self.assertTrue(contains_name("wire-patel.family.trust/in", "PATEL FAMILY TRUST"))
        self.assertFalse(contains_name("WIRE PATEL FAMILY TRUSTEES", "PATEL FAMILY TRUST"))
        self.assertFalse(contains_name("WIRE PATEL TRUST FAMILY", "PATEL FAMILY TRUST"))


class ParseAmountTests(SimpleTestCase):
    def test_accepts_thousands_separators_and_returns_decimal(self):
        from decimal import Decimal

        value = parse_amount(" 25,000.00 ")
        self.assertIsInstance(value, Decimal)
        self.assertEqual(value, Decimal("25000.00"))
        self.assertEqual(parse_amount("-1,250.50"), Decimal("-1250.50"))
        self.assertEqual(parse_amount("(500.00)"), Decimal("-500.00"))
        self.assertEqual(parse_amount("+90"), Decimal("90.00"))

    def test_rejects_zero_blank_and_non_numbers(self):
        for raw in ["0", "0.00", "", "   ", "abc", "12.5.6", "NaN", "-"]:
            with self.subTest(raw=raw), self.assertRaises(AmountError):
                parse_amount(raw)
