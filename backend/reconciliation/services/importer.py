"""Bank statement CSV import (assessment Section 5).

The whole file is validated and written inside one database transaction. A
missing column rejects the file before anything is written; an invalid or
duplicate row is skipped and reported with its line number.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from django.db import transaction as db_transaction

from ..domain.money import AmountError, parse_amount
from ..integrations import airtable
from ..models import BankTransaction, LineItem, Match, Organization
from . import matching

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("date", "description", "amount", "type", "reference")
MAX_DESCRIPTION_LENGTH = 2000
MAX_REFERENCE_LENGTH = 128

# Control characters a bank export should never contain. A NUL in particular is
# accepted by SQLite but rejected by PostgreSQL, so it is removed on the way in.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class FileRejected(Exception):
    """The file cannot be imported at all; nothing is saved."""

    def __init__(self, message: str, missing_columns: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.missing_columns = missing_columns or []


@dataclass
class RowError:
    line: int
    message: str


@dataclass
class DuplicateRow:
    line: int
    bank_reference: str
    reason: str


@dataclass
class ImportSummary:
    imported: int = 0
    duplicates: int = 0
    errors: list[RowError] = field(default_factory=list)
    duplicate_rows: list[DuplicateRow] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=dict)
    rows_read: int = 0


@dataclass
class _ParsedRow:
    line: int
    date: datetime.date
    description: str
    amount: Decimal
    type: str
    bank_reference: str


def decode(raw: bytes) -> str:
    """Decode an uploaded file, tolerating a BOM and Excel's cp1252 exports."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise FileRejected("The file could not be read as text. Please upload a UTF-8 CSV.")


def _clean(value) -> str:
    """Trim surrounding whitespace and control characters; missing cells read as empty."""
    if value is None:
        return ""
    if isinstance(value, list):  # extra, unnamed columns
        value = value[0] if value else ""
    return CONTROL_CHARACTERS.sub("", str(value)).strip()


def _build_reader(text: str) -> csv.DictReader:
    reader = csv.DictReader(io.StringIO(text))
    header = reader.fieldnames
    if not header:
        raise FileRejected("The file is empty.")
    reader.fieldnames = [_clean(name).lower() for name in header]
    missing = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
    if missing:
        raise FileRejected(
            "The file is missing required column(s): " + ", ".join(missing),
            missing_columns=missing,
        )

    # A header that names a required column twice is ambiguous: the reader would
    # silently keep whichever came last. Reject the file instead of guessing.
    repeated = sorted(
        {
            column
            for column in REQUIRED_COLUMNS
            if reader.fieldnames.count(column) > 1
        }
    )
    if repeated:
        raise FileRejected(
            "The file names the same column more than once: " + ", ".join(repeated)
        )
    return reader


def _parse_row(line: int, row: dict, errors: list[RowError]) -> _ParsedRow | None:
    """Validate one row, appending every problem found. Returns None if invalid."""
    before = len(errors)

    raw_date = _clean(row.get("date"))
    parsed_date = None
    if not raw_date:
        errors.append(RowError(line, "date is required"))
    else:
        try:
            parsed_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            errors.append(
                RowError(line, f"date {raw_date!r} is not a real calendar date in YYYY-MM-DD form")
            )

    description = _clean(row.get("description"))
    if not description:
        errors.append(RowError(line, "description is required"))
    elif len(description) > MAX_DESCRIPTION_LENGTH:
        errors.append(
            RowError(line, f"description is longer than {MAX_DESCRIPTION_LENGTH} characters")
        )

    bank_reference = _clean(row.get("reference"))
    if not bank_reference:
        errors.append(RowError(line, "reference is required"))
    elif len(bank_reference) > MAX_REFERENCE_LENGTH:
        errors.append(
            RowError(line, f"reference is longer than {MAX_REFERENCE_LENGTH} characters")
        )

    amount = None
    try:
        amount = parse_amount(_clean(row.get("amount")))
    except AmountError as exc:
        errors.append(RowError(line, str(exc)))

    raw_type = _clean(row.get("type")).lower()
    row_type = None
    if not raw_type:
        errors.append(RowError(line, "type is required"))
    elif raw_type not in {BankTransaction.Type.CREDIT, BankTransaction.Type.DEBIT}:
        errors.append(RowError(line, f"type {_clean(row.get('type'))!r} must be credit or debit"))
    else:
        row_type = raw_type

    if amount is not None and row_type is not None:
        if row_type == BankTransaction.Type.CREDIT and amount < 0:
            errors.append(RowError(line, "a credit must have a positive amount"))
            row_type = None
        elif row_type == BankTransaction.Type.DEBIT and amount > 0:
            errors.append(RowError(line, "a debit must have a negative amount"))
            row_type = None

    if len(errors) != before:
        return None
    return _ParsedRow(
        line=line,
        date=parsed_date,
        description=description,
        amount=amount,
        type=row_type,
        bank_reference=bank_reference,
    )


def import_statement(
    organization: Organization, raw: bytes, airtable_client=None
) -> ImportSummary:
    """Import one bank statement for one organization.

    ``airtable_client`` is only used by the optional Airtable sync, which runs
    after the rows are committed and cannot fail the import.
    """
    text = decode(raw) if isinstance(raw, bytes) else raw
    reader = _build_reader(text)

    summary = ImportSummary()
    parsed_rows: list[_ParsedRow] = []
    seen_in_file: dict[str, int] = {}
    existing_references = set(
        BankTransaction.objects.filter(organization=organization).values_list(
            "bank_reference", flat=True
        )
    )

    for row in reader:
        line = reader.line_num
        if not any(_clean(value) for value in row.values()):
            continue  # a blank line is not worth reporting
        summary.rows_read += 1

        parsed = _parse_row(line, row, summary.errors)
        if parsed is None:
            continue

        if parsed.bank_reference in existing_references:
            summary.duplicate_rows.append(
                DuplicateRow(
                    line=line,
                    bank_reference=parsed.bank_reference,
                    reason="bank reference was already imported for this organization",
                )
            )
            continue
        if parsed.bank_reference in seen_in_file:
            summary.duplicate_rows.append(
                DuplicateRow(
                    line=line,
                    bank_reference=parsed.bank_reference,
                    reason=(
                        "bank reference also appears on line "
                        f"{seen_in_file[parsed.bank_reference]} of this file"
                    ),
                )
            )
            continue

        seen_in_file[parsed.bank_reference] = line
        parsed_rows.append(parsed)

    summary.duplicates = len(summary.duplicate_rows)

    created = _persist(organization, parsed_rows)
    summary.imported = len(created)
    for record in created:
        summary.status_counts[record.status] = summary.status_counts.get(record.status, 0) + 1

    # Bonus: outside the transaction above, and deliberately never fatal.
    try:
        airtable.sync_needs_review(created, client=airtable_client)
    except Exception:  # pragma: no cover - sync_needs_review already swallows
        logger.warning("Airtable sync raised unexpectedly", exc_info=True)
    return summary


@db_transaction.atomic
def _persist(organization: Organization, rows: list[_ParsedRow]) -> list[BankTransaction]:
    """Save the valid rows and run matching on the credits, in one transaction."""
    if not rows:
        return []

    # Loaded once per file: no approval happens during an import, so funded
    # amounts cannot move underneath us and the suggestions stay deterministic.
    line_items = list(
        LineItem.objects.filter(organization=organization).select_related(
            "capital_call", "investor_entity"
        )
    )

    created: list[BankTransaction] = []
    matches: list[Match] = []
    for row in rows:
        record = BankTransaction(
            organization=organization,
            date=row.date,
            description=row.description,
            amount=row.amount,
            type=row.type,
            bank_reference=row.bank_reference,
            source_line_number=row.line,
            status=BankTransaction.Status.IGNORED,
        )
        if record.is_credit:
            matches.extend(matching.apply(record, line_items))
        else:
            record.status_reason = "Debit: money out cannot pay a capital call."
        created.append(record)

    BankTransaction.objects.bulk_create(created)
    if matches:
        # bulk_create above assigns primary keys on SQLite and PostgreSQL, so the
        # match rows can be written in one more statement.
        for match in matches:
            match.transaction_id = match.transaction.pk
        Match.objects.bulk_create(matches)
    return created
