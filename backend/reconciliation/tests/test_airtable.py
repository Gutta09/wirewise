"""Optional Airtable sync (Section 10): only needs_review, and never fatal."""

from django.test import TestCase

from reconciliation.integrations.airtable import FakeAirtableClient, NullAirtableClient, get_client
from reconciliation.models import BankTransaction
from reconciliation.services.importer import import_statement
from reconciliation.tests.factories import (
    csv_bytes,
    make_capital_call,
    make_line_item,
    make_organization,
)

ROWS = (
    "2026-04-03,WIRE REF CC-1003,12500.00,credit,FT1",  # suggested
    "2026-04-03,UNKNOWN INCOMING WIRE,9999.99,credit,FT2",  # needs_review
    "2026-04-03,OUTGOING FEE,-250.00,debit,FT3",  # ignored
)


class AirtableSyncTests(TestCase):
    def setUp(self):
        self.organization = make_organization("northwind", "Northwind Ventures")
        make_line_item(
            self.organization,
            make_capital_call(self.organization),
            "Patel Family Trust",
            "CC-1003",
            "12500.00",
        )

    def test_only_needs_review_transactions_are_sent(self):
        client = FakeAirtableClient()
        import_statement(self.organization, csv_bytes(*ROWS), airtable_client=client)

        self.assertEqual(len(client.records), 1)
        self.assertEqual(client.records[0]["Bank Reference"], "FT2")
        self.assertEqual(client.records[0]["Organization"], "northwind")
        self.assertEqual(client.records[0]["Amount"], "9999.99")

        needs_review = BankTransaction.objects.get(bank_reference="FT2")
        self.assertEqual(needs_review.airtable_sync_status, BankTransaction.SyncStatus.SYNCED)
        self.assertTrue(needs_review.airtable_record_id)

        suggested = BankTransaction.objects.get(bank_reference="FT1")
        self.assertEqual(suggested.airtable_sync_status, BankTransaction.SyncStatus.NOT_SYNCED)
        self.assertEqual(suggested.airtable_record_id, "")

    def test_an_airtable_failure_does_not_break_the_import(self):
        summary = import_statement(
            self.organization, csv_bytes(*ROWS), airtable_client=FakeAirtableClient(fail=True)
        )

        self.assertEqual(summary.imported, 3)
        record = BankTransaction.objects.get(bank_reference="FT2")
        self.assertEqual(record.airtable_sync_status, BankTransaction.SyncStatus.SYNC_FAILED)
        self.assertEqual(record.airtable_record_id, "")

    def test_sync_is_skipped_when_airtable_is_not_configured(self):
        self.assertIsInstance(get_client(), NullAirtableClient)
        summary = import_statement(self.organization, csv_bytes(*ROWS))
        self.assertEqual(summary.imported, 3)
        self.assertEqual(
            BankTransaction.objects.filter(
                airtable_sync_status=BankTransaction.SyncStatus.NOT_SYNCED
            ).count(),
            3,
        )

    def test_the_http_client_is_used_when_airtable_is_enabled(self):
        from reconciliation.integrations.airtable import HttpAirtableClient

        with self.settings(
            AIRTABLE_ENABLED=True, AIRTABLE_API_TOKEN="pat123", AIRTABLE_BASE_ID="app123"
        ):
            client = get_client()
        self.assertIsInstance(client, HttpAirtableClient)
        self.assertTrue(client.url.startswith("https://api.airtable.com/v0/app123/"))
