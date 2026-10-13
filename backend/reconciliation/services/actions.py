"""GP actions on suggestions (assessment Section 7): approve, reject, ignore.

Approve is the only path that moves money. It runs in one database transaction
and claims both the match and the line item with conditional ``UPDATE``
statements, so a repeated or concurrent approval can never fund twice: the
second writer finds nothing left to claim and gets a 409.
"""

from __future__ import annotations

from django.db import transaction as db_transaction
from django.db.models import F
from django.utils import timezone

from ..domain.money import format_money
from ..models import BankTransaction, LineItem, Match


class ActionConflict(Exception):
    """The action is not valid for the current state of the record (HTTP 409)."""


@db_transaction.atomic
def approve_match(match: Match) -> Match:
    """Approve one proposed match and fund its line item."""
    now = timezone.now()

    # Claim the match. A compare-and-set on the row, so of two identical requests
    # exactly one proceeds whatever the interleaving.
    claimed = Match.objects.filter(pk=match.pk, status=Match.Status.PROPOSED).update(
        status=Match.Status.APPROVED, decided_at=now
    )
    if not claimed:
        raise ActionConflict(
            f"This match is already {match.status} and cannot be approved again."
        )

    transaction = match.transaction
    if transaction.status == BankTransaction.Status.RECONCILED:
        raise ActionConflict("This transaction is already reconciled.")
    if transaction.status == BankTransaction.Status.IGNORED:
        raise ActionConflict("This transaction is ignored; un-ignoring is out of scope.")

    # Re-check the amount against the live remaining amount, and fund in the same
    # statement so the check and the write cannot come apart.
    line_item = match.line_item
    funded = LineItem.objects.filter(
        pk=line_item.pk,
        organization_id=line_item.organization_id,
        amount_funded__lte=F("amount_called") - match.amount,
    ).update(amount_funded=F("amount_funded") + match.amount)
    if not funded:
        line_item.refresh_from_db()
        raise ActionConflict(
            f"Amount {format_money(match.amount)} is more than the remaining "
            f"{format_money(line_item.amount_remaining)} on "
            f"{line_item.expected_wire_reference}."
        )

    line_item.refresh_from_db()
    line_item.status = line_item.status_for_funded(line_item.amount_funded)
    line_item.save(update_fields=["status"])

    # One approved match per transaction: the others are rejected.
    Match.objects.filter(transaction=transaction, status=Match.Status.PROPOSED).exclude(
        pk=match.pk
    ).update(status=Match.Status.REJECTED, decided_at=now)

    transaction.status = BankTransaction.Status.RECONCILED
    transaction.status_reason = (
        f"Approved against {line_item.expected_wire_reference} "
        f"({line_item.investor_entity.name}) for {format_money(match.amount)}."
    )
    transaction.save(update_fields=["status", "status_reason"])

    match.refresh_from_db()
    return match


@db_transaction.atomic
def reject_match(match: Match) -> Match:
    """Reject one proposed match; the transaction falls back to needs_review."""
    rejected = Match.objects.filter(pk=match.pk, status=Match.Status.PROPOSED).update(
        status=Match.Status.REJECTED, decided_at=timezone.now()
    )
    if not rejected:
        raise ActionConflict(
            f"This match is already {match.status} and cannot be rejected."
        )

    transaction = match.transaction
    if transaction.status == BankTransaction.Status.SUGGESTED and not (
        Match.objects.filter(
            transaction=transaction, status=Match.Status.PROPOSED
        ).exists()
    ):
        transaction.status = BankTransaction.Status.NEEDS_REVIEW
        transaction.status_reason = (
            "Every suggested match was rejected; this payment needs a manual decision."
        )
        transaction.save(update_fields=["status", "status_reason"])

    match.refresh_from_db()
    return match


@db_transaction.atomic
def ignore_transaction(transaction: BankTransaction) -> BankTransaction:
    """Ignore a suggested or needs_review credit and reject its matches."""
    ignorable = {BankTransaction.Status.SUGGESTED, BankTransaction.Status.NEEDS_REVIEW}
    if transaction.status not in ignorable or not transaction.is_credit:
        raise ActionConflict(
            f"A {transaction.get_status_display().lower()} {transaction.type} "
            "cannot be ignored."
        )

    updated = BankTransaction.objects.filter(
        pk=transaction.pk, status__in=list(ignorable)
    ).update(
        status=BankTransaction.Status.IGNORED,
        status_reason="Ignored by the GP: this payment does not pay a capital call.",
    )
    if not updated:
        raise ActionConflict("This transaction has already been decided.")

    Match.objects.filter(transaction=transaction, status=Match.Status.PROPOSED).update(
        status=Match.Status.REJECTED, decided_at=timezone.now()
    )
    transaction.refresh_from_db()
    return transaction
