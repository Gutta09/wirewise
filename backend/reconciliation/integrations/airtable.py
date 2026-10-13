"""Optional Airtable sync for needs_review transactions (assessment Section 10).

The client only creates records. It is selected through ``get_client()`` so a
test can swap in ``FakeAirtableClient`` without patching ``requests``, and every
failure is swallowed by ``sync_needs_review`` - an Airtable outage must never
break an import.
"""

from __future__ import annotations

import logging
from typing import Protocol

import requests
from django.conf import settings

from ..models import BankTransaction

logger = logging.getLogger(__name__)


class AirtableClient(Protocol):
    enabled: bool

    def create_record(self, fields: dict) -> str:
        """Create one record and return its Airtable record id."""


class NullAirtableClient:
    """Used when Airtable is not configured: the sync is simply skipped."""

    enabled = False

    def create_record(self, fields: dict) -> str:  # pragma: no cover - never called
        raise RuntimeError("Airtable is not configured.")


class FakeAirtableClient:
    """In-memory double for tests."""

    enabled = True

    def __init__(self, fail: bool = False):
        self.records: list[dict] = []
        self.fail = fail

    def create_record(self, fields: dict) -> str:
        if self.fail:
            raise RuntimeError("Airtable is unavailable")
        self.records.append(fields)
        return f"rec{len(self.records):012d}"


class HttpAirtableClient:
    enabled = True

    def __init__(self, token: str, base_id: str, table_name: str, timeout: float):
        self.token = token
        self.base_id = base_id
        self.table_name = table_name
        self.timeout = timeout

    @property
    def url(self) -> str:
        return f"https://api.airtable.com/v0/{self.base_id}/{requests.utils.quote(self.table_name)}"

    def create_record(self, fields: dict) -> str:
        response = requests.post(
            self.url,
            json={"fields": fields, "typecast": True},
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["id"]


def get_client() -> AirtableClient:
    if not (settings.AIRTABLE_ENABLED and settings.AIRTABLE_API_TOKEN and settings.AIRTABLE_BASE_ID):
        return NullAirtableClient()
    return HttpAirtableClient(
        token=settings.AIRTABLE_API_TOKEN,
        base_id=settings.AIRTABLE_BASE_ID,
        table_name=settings.AIRTABLE_TABLE_NAME,
        timeout=settings.AIRTABLE_TIMEOUT_SECONDS,
    )


def record_fields(transaction: BankTransaction) -> dict:
    return {
        "Organization": transaction.organization.slug,
        "Bank Reference": transaction.bank_reference,
        "Date": transaction.date.isoformat(),
        "Description": transaction.description,
        "Amount": str(transaction.amount),
        "Status": transaction.status,
        "Reason": transaction.status_reason,
    }


def sync_needs_review(
    transactions: list[BankTransaction], client: AirtableClient | None = None
) -> int:
    """Push needs_review transactions to Airtable. Never raises."""
    client = client or get_client()
    pending = [
        record
        for record in transactions
        if record.status == BankTransaction.Status.NEEDS_REVIEW
        and record.airtable_sync_status != BankTransaction.SyncStatus.SYNCED
    ]
    if not client.enabled or not pending:
        return 0

    synced = 0
    for record in pending:
        try:
            record.airtable_record_id = client.create_record(record_fields(record))
            record.airtable_sync_status = BankTransaction.SyncStatus.SYNCED
            synced += 1
        except Exception:
            logger.warning("Airtable sync failed for %s", record.bank_reference, exc_info=True)
            record.airtable_sync_status = BankTransaction.SyncStatus.SYNC_FAILED
        record.save(update_fields=["airtable_record_id", "airtable_sync_status"])
    return synced
