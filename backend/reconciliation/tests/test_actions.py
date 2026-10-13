"""Action tests: required case 7 of Section 9, plus reject and ignore."""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import BankTransaction, LineItem, Match
from reconciliation.services import actions
from reconciliation.services.importer import import_statement
from reconciliation.tests.factories import (
    NORTHWIND_HEADERS,
    csv_bytes,
    make_capital_call,
    make_line_item,
    make_organization,
    make_transaction,
)


class ActionTestCase(TestCase):
    def setUp(self):
        self.organization = make_organization("northwind", "Northwind Ventures")
        self.call = make_capital_call(self.organization, sequence=1)
        self.patel = make_line_item(
            self.organization, self.call, "Patel Family Trust", "CC-1003", "12500.00"
        )

    def import_rows(self, *rows: str):
        import_statement(self.organization, csv_bytes(*rows))

    def approve(self, match_id):
        return self.client.post(
            reverse("match-approve", args=[match_id]), headers=NORTHWIND_HEADERS
        )

    def reject(self, match_id):
        return self.client.post(
            reverse("match-reject", args=[match_id]), headers=NORTHWIND_HEADERS
        )

    def ignore(self, transaction_id):
        return self.client.post(
            reverse("transaction-ignore", args=[transaction_id]), headers=NORTHWIND_HEADERS
        )


class ApproveTests(ActionTestCase):
    """Case 7: approving updates the funded amount; a second approval is a 409."""

    def test_approving_funds_the_line_item_and_reconciles_the_transaction(self):
        self.import_rows("2026-04-03,WIRE REF CC-1003,12500.00,credit,FT1")
        match = Match.objects.get()

        response = self.approve(match.pk)
        self.assertEqual(response.status_code, 200)

        self.patel.refresh_from_db()
        self.assertEqual(self.patel.amount_funded, Decimal("12500.00"))
        self.assertEqual(self.patel.amount_remaining, Decimal("0.00"))
        self.assertEqual(self.patel.status, LineItem.Status.FUNDED)

        match.refresh_from_db()
        self.assertEqual(match.status, Match.Status.APPROVED)
        self.assertIsNotNone(match.decided_at)
        self.assertEqual(
            match.transaction.__class__.objects.get(pk=match.transaction_id).status,
            BankTransaction.Status.RECONCILED,
        )
        self.assertEqual(response.json()["line_item"]["amount_remaining"], "0.00")

    def test_two_partial_approvals_fund_the_line_item_in_steps(self):
        self.import_rows(
            "2026-04-03,WIRE REF CC-1003 PART ONE,2500.00,credit,FT1",
            "2026-04-04,WIRE REF CC-1003 PART TWO,10000.00,credit,FT2",
        )
        first, second = Match.objects.order_by("id")

        self.assertEqual(self.approve(first.pk).status_code, 200)
        self.patel.refresh_from_db()
        self.assertEqual(self.patel.amount_funded, Decimal("2500.00"))
        self.assertEqual(self.patel.status, LineItem.Status.PARTIALLY_FUNDED)

        self.assertEqual(self.approve(second.pk).status_code, 200)
        self.patel.refresh_from_db()
        self.assertEqual(self.patel.amount_funded, Decimal("12500.00"))
        self.assertEqual(self.patel.status, LineItem.Status.FUNDED)

    def test_a_second_approval_of_the_same_match_is_a_409_and_funds_nothing(self):
        self.import_rows("2026-04-03,WIRE REF CC-1003,12500.00,credit,FT1")
        match = Match.objects.get()

        self.assertEqual(self.approve(match.pk).status_code, 200)
        response = self.approve(match.pk)

        self.assertEqual(response.status_code, 409)
        self.patel.refresh_from_db()
        self.assertEqual(self.patel.amount_funded, Decimal("12500.00"))

    def test_two_requests_holding_the_same_match_fund_it_only_once(self):
        """Models two in-flight approvals: each read the match while it was proposed.

        The service claims the match with a conditional UPDATE, so the loser of
        the race finds nothing to claim and raises instead of funding again.
        """
        self.import_rows("2026-04-03,WIRE REF CC-1003,12500.00,credit,FT1")
        first = Match.objects.get()
        second = Match.objects.select_related("transaction", "line_item").get(pk=first.pk)

        actions.approve_match(first)
        with self.assertRaises(actions.ActionConflict):
            actions.approve_match(second)

        self.patel.refresh_from_db()
        self.assertEqual(self.patel.amount_funded, Decimal("12500.00"))

    def test_approval_rechecks_the_amount_against_the_live_remaining(self):
        """Two payments each suggested for the full amount: the second is a 409."""
        self.import_rows(
            "2026-04-03,WIRE REF CC-1003 ONE,12500.00,credit,FT1",
            "2026-04-04,WIRE REF CC-1003 TWO,12500.00,credit,FT2",
        )
        first, second = Match.objects.order_by("id")

        self.assertEqual(self.approve(first.pk).status_code, 200)
        response = self.approve(second.pk)

        self.assertEqual(response.status_code, 409)
        self.assertIn("more than the remaining", response.json()["detail"])
        self.patel.refresh_from_db()
        self.assertEqual(self.patel.amount_funded, Decimal("12500.00"))
        second.refresh_from_db()
        self.assertEqual(second.status, Match.Status.PROPOSED)

    def test_approving_one_of_several_suggestions_rejects_the_others(self):
        second_call = make_capital_call(
            self.organization, sequence=2, call_date="2026-04-01", due_date="2026-04-20"
        )
        make_line_item(
            self.organization, self.call, "Oakridge Holdings LLC", "CC-1005", "15000.00"
        )
        make_line_item(
            self.organization, second_call, "Oakridge Holdings LLC", "CC-1006", "15000.00"
        )
        self.import_rows("2026-04-03,WIRE FROM OAKRIDGE HOLDINGS LLC,15000.00,credit,FT1")

        chosen, other = Match.objects.order_by("id")
        self.assertEqual(self.approve(chosen.pk).status_code, 200)

        other.refresh_from_db()
        self.assertEqual(other.status, Match.Status.REJECTED)
        record = BankTransaction.objects.get()
        self.assertEqual(record.status, BankTransaction.Status.RECONCILED)
        self.assertEqual(record.matches.filter(status=Match.Status.APPROVED).count(), 1)

    def test_the_database_refuses_an_overfunded_line_item(self):
        """Belt and braces: the check constraint catches any write that skips the service."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            LineItem.objects.filter(pk=self.patel.pk).update(amount_funded=Decimal("12500.01"))


class RejectTests(ActionTestCase):
    def test_rejecting_the_only_suggestion_sends_the_transaction_back_to_review(self):
        self.import_rows("2026-04-03,WIRE REF CC-1003,12500.00,credit,FT1")
        match = Match.objects.get()

        response = self.reject(match.pk)
        self.assertEqual(response.status_code, 200)

        match.refresh_from_db()
        self.assertEqual(match.status, Match.Status.REJECTED)
        record = BankTransaction.objects.get()
        self.assertEqual(record.status, BankTransaction.Status.NEEDS_REVIEW)
        self.patel.refresh_from_db()
        self.assertEqual(self.patel.amount_funded, Decimal("0.00"))

    def test_rejecting_one_of_two_suggestions_leaves_the_other_approvable(self):
        make_line_item(
            self.organization, self.call, "Patel Family Office", "CC-1007", "12500.00"
        )
        self.import_rows("2026-04-03,WIRE FOR CC-1003 AND CC-1007,12500.00,credit,FT1")
        first, second = Match.objects.order_by("id")

        self.assertEqual(self.reject(first.pk).status_code, 200)
        self.assertEqual(
            BankTransaction.objects.get().status, BankTransaction.Status.NEEDS_REVIEW
        )
        self.assertEqual(self.approve(second.pk).status_code, 200)
        self.assertEqual(BankTransaction.objects.get().status, BankTransaction.Status.RECONCILED)

    def test_rejecting_twice_is_a_409(self):
        self.import_rows("2026-04-03,WIRE REF CC-1003,12500.00,credit,FT1")
        match = Match.objects.get()
        self.assertEqual(self.reject(match.pk).status_code, 200)
        self.assertEqual(self.reject(match.pk).status_code, 409)

    def test_an_approved_match_cannot_be_rejected(self):
        self.import_rows("2026-04-03,WIRE REF CC-1003,12500.00,credit,FT1")
        match = Match.objects.get()
        self.assertEqual(self.approve(match.pk).status_code, 200)
        self.assertEqual(self.reject(match.pk).status_code, 409)


class IgnoreTests(ActionTestCase):
    def test_ignoring_a_suggested_credit_rejects_its_matches(self):
        self.import_rows("2026-04-03,WIRE REF CC-1003,12500.00,credit,FT1")
        record = BankTransaction.objects.get()

        response = self.ignore(record.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], BankTransaction.Status.IGNORED)
        self.assertEqual(Match.objects.get().status, Match.Status.REJECTED)
        self.patel.refresh_from_db()
        self.assertEqual(self.patel.amount_funded, Decimal("0.00"))

    def test_ignoring_a_needs_review_credit_works(self):
        self.import_rows("2026-04-03,UNKNOWN INCOMING WIRE,9999.99,credit,FT1")
        record = BankTransaction.objects.get()
        self.assertEqual(self.ignore(record.pk).status_code, 200)

    def test_ignoring_a_reconciled_transaction_is_a_409(self):
        self.import_rows("2026-04-03,WIRE REF CC-1003,12500.00,credit,FT1")
        self.approve(Match.objects.get().pk)
        record = BankTransaction.objects.get()
        self.assertEqual(self.ignore(record.pk).status_code, 409)

    def test_ignoring_a_debit_is_a_409(self):
        self.import_rows("2026-04-03,OUTGOING FEE,-250.00,debit,FT1")
        record = BankTransaction.objects.get()
        self.assertEqual(self.ignore(record.pk).status_code, 409)

    def test_ignoring_twice_is_a_409(self):
        record = make_transaction(self.organization, status=BankTransaction.Status.NEEDS_REVIEW)
        self.assertEqual(self.ignore(record.pk).status_code, 200)
        self.assertEqual(self.ignore(record.pk).status_code, 409)
