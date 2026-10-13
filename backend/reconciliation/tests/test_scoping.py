"""Tenant safety: required case 8 of Section 9, plus the header contract."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import BankTransaction, Match
from reconciliation.services.importer import import_statement
from reconciliation.tests.factories import (
    BLUEBIRD_HEADERS,
    NORTHWIND_HEADERS,
    csv_bytes,
    make_capital_call,
    make_line_item,
    make_organization,
)


class ScopingTestCase(TestCase):
    def setUp(self):
        self.northwind = make_organization("northwind", "Northwind Ventures")
        self.bluebird = make_organization("bluebird", "Bluebird Capital")

        self.patel = make_line_item(
            self.northwind,
            make_capital_call(self.northwind),
            "Patel Family Trust",
            "CC-1003",
            "12500.00",
        )
        self.cedar = make_line_item(
            self.bluebird,
            make_capital_call(self.bluebird, call_date="2026-04-01", due_date="2026-04-15"),
            "Cedar Grove Fund LP",
            "CC-2001",
            "40000.00",
        )
        import_statement(
            self.northwind, csv_bytes("2026-04-03,WIRE REF CC-1003,12500.00,credit,FT1")
        )
        self.northwind_transaction = BankTransaction.objects.get(organization=self.northwind)
        self.northwind_match = Match.objects.get(organization=self.northwind)


class HeaderContractTests(ScopingTestCase):
    def test_a_missing_header_is_a_400_everywhere(self):
        for name, args in [
            ("transaction-list", []),
            ("line-item-list", []),
            ("import-create", []),
            ("match-approve", [self.northwind_match.pk]),
            ("match-reject", [self.northwind_match.pk]),
            ("transaction-ignore", [self.northwind_transaction.pk]),
        ]:
            with self.subTest(endpoint=name):
                url = reverse(name, args=args)
                response = (
                    self.client.get(url) if not args and "list" in name else self.client.post(url)
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("X-Organization", response.json()["detail"])

    def test_an_unknown_organization_is_a_404(self):
        response = self.client.get(
            reverse("transaction-list"), headers={"X-Organization": "nosuchfirm"}
        )
        self.assertEqual(response.status_code, 404)

    def test_a_blank_header_is_a_400(self):
        response = self.client.get(reverse("transaction-list"), headers={"X-Organization": "  "})
        self.assertEqual(response.status_code, 400)

    def test_the_slug_is_matched_case_insensitively(self):
        response = self.client.get(
            reverse("transaction-list"), headers={"X-Organization": "NorthWind"}
        )
        self.assertEqual(response.status_code, 200)

    def test_the_organization_list_needs_no_header(self):
        response = self.client.get(reverse("organization-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(item["slug"] for item in response.json()), ["bluebird", "northwind"]
        )


class IsolationTests(ScopingTestCase):
    def test_listing_only_shows_the_headers_organization(self):
        response = self.client.get(reverse("transaction-list"), headers=BLUEBIRD_HEADERS)
        self.assertEqual(response.json(), [])

        response = self.client.get(reverse("transaction-list"), headers=NORTHWIND_HEADERS)
        self.assertEqual([item["bank_reference"] for item in response.json()], ["FT1"])

    def test_line_items_are_scoped(self):
        response = self.client.get(reverse("line-item-list"), headers=BLUEBIRD_HEADERS)
        self.assertEqual(
            [item["expected_wire_reference"] for item in response.json()], ["CC-2001"]
        )

    def test_approving_another_organizations_match_is_a_404(self):
        response = self.client.post(
            reverse("match-approve", args=[self.northwind_match.pk]), headers=BLUEBIRD_HEADERS
        )
        self.assertEqual(response.status_code, 404)

        self.patel.refresh_from_db()
        self.assertEqual(str(self.patel.amount_funded), "0.00")
        self.northwind_match.refresh_from_db()
        self.assertEqual(self.northwind_match.status, Match.Status.PROPOSED)

    def test_rejecting_another_organizations_match_is_a_404(self):
        response = self.client.post(
            reverse("match-reject", args=[self.northwind_match.pk]), headers=BLUEBIRD_HEADERS
        )
        self.assertEqual(response.status_code, 404)
        self.northwind_match.refresh_from_db()
        self.assertEqual(self.northwind_match.status, Match.Status.PROPOSED)

    def test_ignoring_another_organizations_transaction_is_a_404(self):
        response = self.client.post(
            reverse("transaction-ignore", args=[self.northwind_transaction.pk]),
            headers=BLUEBIRD_HEADERS,
        )
        self.assertEqual(response.status_code, 404)
        self.northwind_transaction.refresh_from_db()
        self.assertEqual(self.northwind_transaction.status, BankTransaction.Status.SUGGESTED)

    def test_an_import_lands_only_in_the_headers_organization(self):
        self.client.post(
            reverse("import-create"),
            {
                "file": SimpleUploadedFile(
                    "statement.csv",
                    csv_bytes("2026-04-02,INCOMING WIRE REF cc2001,40000.00,credit,FT9"),
                    content_type="text/csv",
                )
            },
            headers=BLUEBIRD_HEADERS,
        )
        self.assertEqual(BankTransaction.objects.filter(organization=self.northwind).count(), 1)
        bluebird_rows = BankTransaction.objects.filter(organization=self.bluebird)
        self.assertEqual([row.bank_reference for row in bluebird_rows], ["FT9"])
        self.assertEqual(bluebird_rows.get().matches.get().line_item, self.cedar)


class ListingTests(ScopingTestCase):
    def test_transactions_come_back_newest_first_with_matches_and_reasons(self):
        import_statement(
            self.northwind,
            csv_bytes(
                "2026-04-01,OLDER WIRE,100.00,credit,FT2",
                "2026-04-09,NEWER WIRE,200.00,credit,FT3",
            ),
        )
        response = self.client.get(reverse("transaction-list"), headers=NORTHWIND_HEADERS)
        body = response.json()
        self.assertEqual([item["bank_reference"] for item in body], ["FT3", "FT1", "FT2"])

        suggested = next(item for item in body if item["bank_reference"] == "FT1")
        self.assertEqual(suggested["status"], "suggested")
        self.assertEqual(suggested["amount"], "12500.00")
        self.assertEqual(suggested["matches"][0]["line_item"]["investor_name"], "Patel Family Trust")
        self.assertIn("CC-1003", suggested["matches"][0]["reason"])
        self.assertEqual(
            suggested["available_actions"], ["approve_match", "reject_match", "ignore"]
        )

    def test_line_item_panel_reports_called_funded_remaining_and_status(self):
        response = self.client.get(reverse("line-item-list"), headers=NORTHWIND_HEADERS)
        item = response.json()[0]
        self.assertEqual(item["amount_called"], "12500.00")
        self.assertEqual(item["amount_funded"], "0.00")
        self.assertEqual(item["amount_remaining"], "12500.00")
        self.assertEqual(item["status"], "open")
        self.assertEqual(item["capital_call"]["label"], "Capital Call #1")

    def test_transactions_can_be_filtered_by_status(self):
        response = self.client.get(
            reverse("transaction-list"), {"status": "needs_review"}, headers=NORTHWIND_HEADERS
        )
        self.assertEqual(response.json(), [])
