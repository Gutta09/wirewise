"""Import tests: required cases 1, 2 and 3 of Section 9."""

from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from reconciliation.models import BankTransaction
from reconciliation.tests.factories import (
    BLUEBIRD_HEADERS,
    NORTHWIND_HEADERS,
    csv_bytes,
    make_capital_call,
    make_line_item,
    make_organization,
)


class ImportApiTestCase(TestCase):
    def setUp(self):
        self.northwind = make_organization("northwind", "Northwind Ventures")
        self.bluebird = make_organization("bluebird", "Bluebird Capital")
        call = make_capital_call(self.northwind, sequence=1)
        self.patel = make_line_item(
            self.northwind,
            capital_call=call,
            investor_name="Patel Family Trust",
            reference="CC-1003",
            amount_called="12500.00",
        )
        self.url = reverse("import-create")

    def upload(self, payload: bytes, headers=None, filename="statement.csv"):
        return self.client.post(
            self.url,
            {"file": SimpleUploadedFile(filename, payload, content_type="text/csv")},
            headers=headers if headers is not None else NORTHWIND_HEADERS,
        )


class MissingColumnTests(ImportApiTestCase):
    """Case 1: a missing column rejects the file and saves nothing."""

    def test_missing_column_rejects_the_whole_file(self):
        response = self.upload(
            csv_bytes(
                "2026-04-03,WIRE INCOMING PATEL FAMILY TRUST,12500.00,FT1",
                header="date,description,amount,reference\n",
            )
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("type", response.json()["missing_columns"])
        self.assertEqual(BankTransaction.objects.count(), 0)

    def test_valid_rows_are_not_saved_when_a_column_is_missing(self):
        self.upload(
            csv_bytes(
                "2026-04-03,WIRE INCOMING PATEL FAMILY TRUST,12500.00,credit",
                header="date,description,amount,type\n",
            )
        )
        self.assertEqual(BankTransaction.objects.count(), 0)

    def test_a_repeated_required_column_rejects_the_file(self):
        """Two 'date' columns are ambiguous: the reader would silently keep the last."""
        response = self.upload(
            csv_bytes(
                "2026-04-03,WIRE ONE,100.00,credit,FT1,2026-01-01",
                header="date,description,amount,type,reference,date\n",
            )
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("more than once", response.json()["detail"])
        self.assertEqual(BankTransaction.objects.count(), 0)

    def test_empty_file_is_rejected(self):
        response = self.upload(b"")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(BankTransaction.objects.count(), 0)

    def test_upload_without_a_file_is_a_400(self):
        response = self.client.post(self.url, {}, headers=NORTHWIND_HEADERS)
        self.assertEqual(response.status_code, 400)


class RowValidationTests(ImportApiTestCase):
    """Case 2: amount parsing, sign/type mismatches and invalid dates."""

    def test_thousands_separators_are_stored_as_decimal(self):
        response = self.upload(
            csv_bytes('2026-04-03,WIRE INCOMING PATEL FAMILY TRUST,"12,500.00",credit,FT1')
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["imported"], 1)

        record = BankTransaction.objects.get(bank_reference="FT1")
        self.assertIsInstance(record.amount, Decimal)
        self.assertEqual(record.amount, Decimal("12500.00"))
        # Read straight back from the database, not from the in-memory instance.
        self.assertIsInstance(BankTransaction.objects.get(pk=record.pk).amount, Decimal)

    def test_invalid_rows_are_skipped_and_reported_with_their_line_number(self):
        response = self.upload(
            csv_bytes(
                "2026-02-30,BAD DATE,100.00,credit,FT1",  # line 2: not a calendar date
                "2026-04-03,NEGATIVE CREDIT,-100.00,credit,FT2",  # line 3: sign mismatch
                "2026-04-03,POSITIVE DEBIT,100.00,debit,FT3",  # line 4: sign mismatch
                "2026-04-03,ZERO,0.00,credit,FT4",  # line 5: zero is invalid
                "2026-04-03,BAD TYPE,100.00,transfer,FT5",  # line 6: unknown type
                "2026-04-03,,100.00,credit,FT6",  # line 7: description required
                "2026-04-03,NO REFERENCE,100.00,credit,",  # line 8: reference required
                "2026-04-03,NOT A NUMBER,one hundred,credit,FT8",  # line 9
                ",NO DATE,100.00,credit,FT9",  # line 10
                "2026-04-03,GOOD ROW,100.00,CrEdIt,FT10",  # line 11: imported
            )
        )
        body = response.json()
        self.assertEqual(body["imported"], 1)
        self.assertEqual([error["line"] for error in body["errors"]], list(range(2, 11)))
        self.assertIn("calendar date", body["errors"][0]["message"])
        self.assertIn("positive", body["errors"][1]["message"])
        self.assertIn("negative", body["errors"][2]["message"])
        self.assertIn("zero", body["errors"][3]["message"])
        self.assertEqual(
            list(BankTransaction.objects.values_list("bank_reference", flat=True)), ["FT10"]
        )

    def test_fields_are_trimmed_and_type_case_is_ignored(self):
        self.upload(
            csv_bytes(
                '  2026-04-03 ,  WIRE INCOMING PATEL FAMILY TRUST  ," 12,500.00 ", CREDIT , FT1 '
            )
        )
        record = BankTransaction.objects.get()
        self.assertEqual(record.bank_reference, "FT1")
        self.assertEqual(record.description, "WIRE INCOMING PATEL FAMILY TRUST")
        self.assertEqual(record.type, BankTransaction.Type.CREDIT)
        self.assertEqual(record.amount, Decimal("12500.00"))

    def test_blank_lines_are_skipped_without_an_error(self):
        response = self.upload(
            csv_bytes("2026-04-03,WIRE ONE,100.00,credit,FT1", "", ",,,,", "")
        )
        body = response.json()
        self.assertEqual(body["imported"], 1)
        self.assertEqual(body["errors"], [])

    def test_a_bom_and_unknown_extra_columns_are_tolerated(self):
        payload = (
            "﻿date,description,amount,type,reference,balance\n"
            "2026-04-03,WIRE ONE,100.00,credit,FT1,9999.00\n"
        ).encode()
        response = self.upload(payload)
        self.assertEqual(response.json()["imported"], 1)

    def test_line_numbers_survive_a_quoted_newline(self):
        payload = csv_bytes(
            '2026-04-03,"WIRE ONE\nSECOND LINE",100.00,credit,FT1',
            "2026-02-30,BAD DATE,100.00,credit,FT2",
        )
        response = self.upload(payload)
        # The bad row is the fourth physical line of the file.
        self.assertEqual([error["line"] for error in response.json()["errors"]], [4])

    def test_an_amount_too_large_for_the_column_is_a_row_error(self):
        """The row is skipped, and every other row stays readable afterwards."""
        response = self.upload(
            csv_bytes(
                "2026-04-03,ABSURD WIRE,99999999999999999999.00,credit,FT1",
                "2026-04-03,NORMAL WIRE,100.00,credit,FT2",
            )
        )
        body = response.json()
        self.assertEqual(body["imported"], 1)
        self.assertEqual(body["errors"][0]["line"], 2)
        self.assertIn("larger than the maximum", body["errors"][0]["message"])

        # Reading the list back must not blow up on a stored over-precision value.
        listing = self.client.get(reverse("transaction-list"), headers=NORTHWIND_HEADERS)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([row["amount"] for row in listing.json()], ["100.00"])

    def test_control_characters_are_stripped_from_fields(self):
        self.upload(csv_bytes("2026-04-03,WIRE\x00ONE,100.00,credit,FT\x011"))
        record = BankTransaction.objects.get()
        self.assertEqual(record.description, "WIREONE")
        self.assertEqual(record.bank_reference, "FT1")

    def test_a_statement_of_a_few_thousand_rows_imports(self):
        rows = [
            f"2026-04-03,WIRE {index} REF CC-1003,100.00,credit,FT{index:05d}"
            for index in range(2000)
        ]
        body = self.upload(csv_bytes(*rows)).json()
        self.assertEqual(body["imported"], 2000)
        self.assertEqual(BankTransaction.objects.count(), 2000)
        # Matches are written by the same bulk path, so they must exist too.
        self.assertEqual(
            BankTransaction.objects.filter(status=BankTransaction.Status.SUGGESTED).count(),
            2000,
        )

    def test_debits_are_stored_as_ignored_and_never_matched(self):
        self.upload(csv_bytes("2026-04-03,OUTGOING FEE,-250.00,debit,FT1"))
        record = BankTransaction.objects.get()
        self.assertEqual(record.status, BankTransaction.Status.IGNORED)
        self.assertEqual(record.matches.count(), 0)
        self.assertIn("Debit", record.status_reason)


class DuplicateTests(ImportApiTestCase):
    """Case 3: duplicates on re-upload and inside a single file."""

    def test_duplicate_inside_one_file_is_skipped_and_reported(self):
        response = self.upload(
            csv_bytes(
                "2026-04-03,WIRE ONE,100.00,credit,FT1",
                "2026-04-04,WIRE ONE AGAIN,100.00,credit,FT1",
            )
        )
        body = response.json()
        self.assertEqual(body["imported"], 1)
        self.assertEqual(body["duplicates"], 1)
        self.assertEqual(body["duplicate_rows"][0]["line"], 3)
        self.assertIn("line 2 of this file", body["duplicate_rows"][0]["reason"])
        self.assertEqual(BankTransaction.objects.count(), 1)

    def test_reuploading_the_same_file_imports_nothing_new(self):
        payload = csv_bytes(
            "2026-04-03,WIRE ONE,100.00,credit,FT1",
            "2026-04-03,WIRE TWO,200.00,credit,FT2",
        )
        self.assertEqual(self.upload(payload).json()["imported"], 2)

        body = self.upload(payload).json()
        self.assertEqual(body["imported"], 0)
        self.assertEqual(body["duplicates"], 2)
        self.assertIn("already imported", body["duplicate_rows"][0]["reason"])
        self.assertEqual(BankTransaction.objects.count(), 2)

    def test_two_organizations_may_share_a_bank_reference(self):
        payload = csv_bytes("2026-04-03,WIRE ONE,100.00,credit,FT1")
        self.assertEqual(self.upload(payload).json()["imported"], 1)
        self.assertEqual(self.upload(payload, headers=BLUEBIRD_HEADERS).json()["imported"], 1)
        self.assertEqual(BankTransaction.objects.count(), 2)
        self.assertEqual(
            BankTransaction.objects.filter(organization=self.bluebird).count(), 1
        )
