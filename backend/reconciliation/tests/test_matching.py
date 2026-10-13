"""Matching tests: required cases 4, 5 and 6 of Section 9."""

from decimal import Decimal

from django.test import TestCase

from reconciliation.models import BankTransaction, Match
from reconciliation.services.importer import import_statement
from reconciliation.tests.factories import (
    csv_bytes,
    make_capital_call,
    make_line_item,
    make_organization,
)


class MatchingTestCase(TestCase):
    """Builds the seed shape of Northwind's first two capital calls."""

    def setUp(self):
        self.organization = make_organization("northwind", "Northwind Ventures")
        self.call_one = make_capital_call(
            self.organization, sequence=1, call_date="2026-03-25", due_date="2026-04-10"
        )
        self.call_two = make_capital_call(
            self.organization, sequence=2, call_date="2026-04-01", due_date="2026-04-20"
        )
        self.haller = make_line_item(
            self.organization, self.call_one, "Haller Capital LLC", "CC-1001", "27500.00"
        )
        self.shah = make_line_item(
            self.organization, self.call_one, "Rahul Shah Trust", "CC-1002", "25000.00"
        )
        self.patel = make_line_item(
            self.organization, self.call_one, "Patel Family Trust", "CC-1003", "12500.00"
        )
        self.meridian = make_line_item(
            self.organization, self.call_one, "Meridian Partners LP", "CC-1004", "15000.00"
        )
        self.oakridge_one = make_line_item(
            self.organization, self.call_one, "Oakridge Holdings LLC", "CC-1005", "15000.00"
        )
        self.oakridge_two = make_line_item(
            self.organization, self.call_two, "Oakridge Holdings LLC", "CC-1006", "15000.00"
        )

    def import_rows(self, *rows: str):
        return import_statement(self.organization, csv_bytes(*rows))

    def import_one(self, *rows: str) -> BankTransaction:
        self.import_rows(*rows)
        return BankTransaction.objects.latest("id")


class ReferenceMatchTests(MatchingTestCase):
    """Case 4: reference matching, including cc1001 and a partial payment."""

    def test_reference_in_the_description_suggests_one_match(self):
        record = self.import_one(
            '2026-04-03,WIRE INCOMING RAHUL SHAH TRUST REF CC-1002,"25,000.00",credit,FT1'
        )
        self.assertEqual(record.status, BankTransaction.Status.SUGGESTED)
        match = record.matches.get()
        self.assertEqual(match.line_item, self.shah)
        self.assertEqual(match.status, Match.Status.PROPOSED)
        self.assertIn("CC-1002", match.reason)
        self.assertIn("equals remaining 25,000.00", match.reason)

    def test_lowercase_unpunctuated_reference_still_matches(self):
        record = self.import_one("2026-04-03,INBOUND WIRE cc1001 THANKS,27500.00,credit,FT1")
        self.assertEqual(record.status, BankTransaction.Status.SUGGESTED)
        self.assertEqual(record.matches.get().line_item, self.haller)

    def test_a_partial_payment_is_suggested_and_the_reason_says_so(self):
        record = self.import_one("2026-04-03,INBOUND WIRE REF CC-1001,10000.00,credit,FT1")
        self.assertEqual(record.status, BankTransaction.Status.SUGGESTED)
        match = record.matches.get()
        self.assertEqual(match.line_item, self.haller)
        self.assertEqual(match.amount, Decimal("10000.00"))
        self.assertIn("partial payment of remaining 27,500.00", match.reason)

    def test_reference_in_the_bank_reference_is_enough(self):
        record = self.import_one("2026-04-03,INBOUND WIRE NO NAME,12500.00,credit,CC1003-X")
        self.assertEqual(record.status, BankTransaction.Status.SUGGESTED)
        self.assertEqual(record.matches.get().line_item, self.patel)
        self.assertIn("bank reference", record.matches.get().reason)

    def test_two_references_propose_both_and_need_review(self):
        record = self.import_one(
            "2026-04-03,WIRE FOR CC-1002 AND CC-1003,37500.00,credit,FT1"
        )
        self.assertEqual(record.status, BankTransaction.Status.NEEDS_REVIEW)
        self.assertEqual(
            sorted(match.line_item.expected_wire_reference for match in record.matches.all()),
            ["CC-1002", "CC-1003"],
        )
        self.assertIn("2 references", record.status_reason)

    def test_a_found_reference_stops_the_name_check(self):
        """CC-1004 is found, so the exact-amount name match on CC-1005 is not tried."""
        record = self.import_one(
            "2026-04-03,WIRE OAKRIDGE HOLDINGS LLC REF CC-1004,15000.00,credit,FT1"
        )
        self.assertEqual(record.matches.get().line_item, self.meridian)

    def test_partially_funded_line_item_matches_against_the_remaining_amount(self):
        self.haller.amount_funded = Decimal("20000.00")
        self.haller.status = self.haller.status_for_funded(self.haller.amount_funded)
        self.haller.save()

        record = self.import_one("2026-04-03,WIRE REF CC-1001,7500.00,credit,FT1")
        self.assertEqual(record.status, BankTransaction.Status.SUGGESTED)
        self.assertIn("equals remaining 7,500.00", record.matches.get().reason)


class OverpaymentTests(MatchingTestCase):
    """Case 6: an overpayment becomes needs_review with no match."""

    def test_overpayment_on_a_referenced_line_item_creates_no_match(self):
        record = self.import_one("2026-04-03,WIRE MERIDIAN REF CC-1004,20000.00,credit,FT1")
        self.assertEqual(record.status, BankTransaction.Status.NEEDS_REVIEW)
        self.assertEqual(record.matches.count(), 0)
        self.assertIn("overpayment", record.status_reason)
        self.assertIn("more than the remaining 15,000.00", record.status_reason)


class NameAndAmountMatchTests(MatchingTestCase):
    """Case 5: name and amount matching, including several candidates."""

    def test_name_and_exact_amount_suggests_one_match(self):
        record = self.import_one("2026-04-03,WIRE INCOMING PATEL FAMILY TRUST,12500.00,credit,FT1")
        self.assertEqual(record.status, BankTransaction.Status.SUGGESTED)
        match = record.matches.get()
        self.assertEqual(match.line_item, self.patel)
        self.assertIn("Patel Family Trust", match.reason)

    def test_entity_suffix_is_ignored_when_looking_for_the_name(self):
        record = self.import_one("2026-04-03,WIRE FROM HALLER CAPITAL,27500.00,credit,FT1")
        self.assertEqual(record.matches.get().line_item, self.haller)

    def test_two_candidates_with_the_same_amount_need_review(self):
        record = self.import_one("2026-04-04,WIRE FROM OAKRIDGE HOLDINGS LLC,15000.00,credit,FT1")
        self.assertEqual(record.status, BankTransaction.Status.NEEDS_REVIEW)
        self.assertEqual(
            sorted(match.line_item.expected_wire_reference for match in record.matches.all()),
            ["CC-1005", "CC-1006"],
        )
        for match in record.matches.all():
            self.assertEqual(match.status, Match.Status.PROPOSED)
            self.assertIn("One of 2 candidates", match.reason)

    def test_a_name_without_the_exact_amount_is_not_a_match(self):
        record = self.import_one("2026-04-03,WIRE INCOMING PATEL FAMILY TRUST,12499.99,credit,FT1")
        self.assertEqual(record.status, BankTransaction.Status.NEEDS_REVIEW)
        self.assertEqual(record.matches.count(), 0)

    def test_an_unknown_wire_needs_review_with_no_matches(self):
        record = self.import_one("2026-04-03,UNKNOWN INCOMING WIRE,9999.99,credit,FT1")
        self.assertEqual(record.status, BankTransaction.Status.NEEDS_REVIEW)
        self.assertEqual(record.matches.count(), 0)
        self.assertIn("No expected wire reference was found", record.status_reason)


class EligibilityTests(MatchingTestCase):
    """Step 1 of the rule: remaining above zero and a call date on or before the payment."""

    def test_a_call_dated_after_the_payment_is_not_eligible(self):
        record = self.import_one("2026-03-31,WIRE REF CC-1006,15000.00,credit,FT1")
        self.assertEqual(record.status, BankTransaction.Status.NEEDS_REVIEW)
        self.assertEqual(record.matches.count(), 0)

    def test_a_call_dated_on_the_payment_day_is_eligible(self):
        record = self.import_one("2026-04-01,WIRE REF CC-1006,15000.00,credit,FT1")
        self.assertEqual(record.status, BankTransaction.Status.SUGGESTED)

    def test_a_fully_funded_line_item_is_not_eligible(self):
        self.patel.amount_funded = self.patel.amount_called
        self.patel.status = self.patel.Status.FUNDED
        self.patel.save()

        record = self.import_one("2026-04-03,WIRE REF CC-1003,12500.00,credit,FT1")
        self.assertEqual(record.status, BankTransaction.Status.NEEDS_REVIEW)
        self.assertEqual(record.matches.count(), 0)

    def test_an_organization_with_no_line_items_needs_review(self):
        other = make_organization("bluebird", "Bluebird Capital")
        import_statement(other, csv_bytes("2026-04-03,WIRE REF CC-1003,12500.00,credit,FT1"))
        record = BankTransaction.objects.get(organization=other)
        self.assertEqual(record.status, BankTransaction.Status.NEEDS_REVIEW)
        self.assertIn("No line item was eligible", record.status_reason)

    def test_matching_never_reaches_another_organizations_line_items(self):
        other = make_organization("bluebird", "Bluebird Capital")
        import_statement(
            other,
            csv_bytes("2026-04-03,WIRE INCOMING PATEL FAMILY TRUST REF CC-1003,12500.00,credit,FT1"),
        )
        record = BankTransaction.objects.get(organization=other)
        self.assertEqual(record.matches.count(), 0)
        self.assertEqual(record.status, BankTransaction.Status.NEEDS_REVIEW)
