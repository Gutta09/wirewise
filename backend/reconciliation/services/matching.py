"""Suggestion engine (assessment Section 6).

``decide`` is a pure function over already-loaded line items: given one credit it
returns the transaction status, a reason, and the matches to propose. ``apply``
is the thin persistence wrapper used by the importer.

Suggestions are calculated once, at import time. Approval re-checks the amount.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Sequence

from ..domain.money import format_money
from ..domain.normalisation import contains_name, contains_reference
from ..models import BankTransaction, LineItem, Match

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class ProposedMatch:
    line_item: LineItem
    reason: str


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str
    proposals: Sequence[ProposedMatch] = field(default_factory=tuple)


def eligible_line_items(
    line_items: Iterable[LineItem], transaction_date: date
) -> list[LineItem]:
    """Step 1: a remaining amount above 0.00 and a call date on or before the payment.

    Callers pass line items already scoped to the transaction's organization.
    """
    return [
        item
        for item in line_items
        if item.amount_remaining > ZERO and item.capital_call.call_date <= transaction_date
    ]


def _reference_location(item: LineItem, description: str, bank_reference: str) -> str | None:
    in_description = contains_reference(description, item.normalised_reference)
    in_bank_reference = contains_reference(bank_reference, item.normalised_reference)
    if in_description and in_bank_reference:
        return "description and bank reference"
    if in_description:
        return "description"
    if in_bank_reference:
        return "bank reference"
    return None


def decide(
    *,
    transaction_date: date,
    amount: Decimal,
    description: str,
    bank_reference: str,
    line_items: Iterable[LineItem],
) -> Decision:
    """Apply the matching rule to one credit."""
    eligible = eligible_line_items(line_items, transaction_date)
    if not eligible:
        return Decision(
            status=BankTransaction.Status.NEEDS_REVIEW,
            reason=(
                "No line item was eligible: none had a remaining amount above 0.00 "
                f"and a call date on or before {transaction_date.isoformat()}."
            ),
        )

    # Step 2: reference check.
    hits = [
        (item, where)
        for item in eligible
        if (where := _reference_location(item, description, bank_reference)) is not None
    ]
    if hits:
        return _decide_by_reference(hits, amount)

    # Step 3: name and amount check.
    named = [
        item
        for item in eligible
        if item.amount_remaining == amount
        and contains_name(description, item.investor_entity.normalised_name)
    ]
    if named:
        return _decide_by_name(named, amount)

    return Decision(
        status=BankTransaction.Status.NEEDS_REVIEW,
        reason=(
            f"No expected wire reference was found, and no eligible line item has both "
            f"the investor name in the description and a remaining amount of exactly "
            f"{format_money(amount)} ({len(eligible)} line "
            f"item{'' if len(eligible) == 1 else 's'} eligible)."
        ),
    )


def _decide_by_reference(hits: list[tuple[LineItem, str]], amount: Decimal) -> Decision:
    if len(hits) == 1:
        item, where = hits[0]
        remaining = item.amount_remaining
        reference = item.expected_wire_reference
        if amount > remaining:
            # Overpayment: no match at all, the GP decides what to do.
            return Decision(
                status=BankTransaction.Status.NEEDS_REVIEW,
                reason=(
                    f"Reference {reference} found in {where}, but the amount "
                    f"{format_money(amount)} is more than the remaining "
                    f"{format_money(remaining)} (overpayment)."
                ),
            )
        if amount == remaining:
            detail = f"amount equals remaining {format_money(remaining)}"
        else:
            detail = (
                f"amount {format_money(amount)} is a partial payment of remaining "
                f"{format_money(remaining)}"
            )
        return Decision(
            status=BankTransaction.Status.SUGGESTED,
            reason=f"Reference {reference} found in {where}; {detail}.",
            proposals=(
                ProposedMatch(
                    line_item=item,
                    reason=f"Reference {reference} found in {where}; {detail}.",
                ),
            ),
        )

    references = ", ".join(item.expected_wire_reference for item, _ in hits)
    return Decision(
        status=BankTransaction.Status.NEEDS_REVIEW,
        reason=(
            f"{len(hits)} references were found in this payment ({references}); "
            "a GP has to choose which line item it pays."
        ),
        proposals=tuple(
            ProposedMatch(
                line_item=item,
                reason=(
                    f"Reference {item.expected_wire_reference} found in {where}; "
                    f"one of {len(hits)} references found in this payment. "
                    f"Amount {format_money(amount)} against remaining "
                    f"{format_money(item.amount_remaining)}."
                ),
            )
            for item, where in hits
        ),
    )


def _decide_by_name(named: list[LineItem], amount: Decimal) -> Decision:
    if len(named) == 1:
        item = named[0]
        reason = (
            f'Investor name "{item.investor_entity.name}" found in the description; '
            f"amount equals remaining {format_money(item.amount_remaining)} on "
            f"{item.expected_wire_reference}."
        )
        return Decision(
            status=BankTransaction.Status.SUGGESTED,
            reason=reason,
            proposals=(ProposedMatch(line_item=item, reason=reason),),
        )

    references = ", ".join(item.expected_wire_reference for item in named)
    return Decision(
        status=BankTransaction.Status.NEEDS_REVIEW,
        reason=(
            f"{len(named)} line items match on investor name and an exact amount of "
            f"{format_money(amount)} ({references}); a GP has to choose."
        ),
        proposals=tuple(
            ProposedMatch(
                line_item=item,
                reason=(
                    f'Investor name "{item.investor_entity.name}" found in the description; '
                    f"amount equals remaining {format_money(item.amount_remaining)} on "
                    f"{item.expected_wire_reference}. One of {len(named)} candidates with "
                    "the same amount."
                ),
            )
            for item in named
        ),
    )


def apply(transaction: BankTransaction, line_items: Iterable[LineItem]) -> list[Match]:
    """Run the matching rule for a saved credit and return unsaved ``Match`` rows.

    The caller persists them (the importer does one ``bulk_create`` per file).
    """
    decision = decide(
        transaction_date=transaction.date,
        amount=transaction.amount,
        description=transaction.description,
        bank_reference=transaction.bank_reference,
        line_items=line_items,
    )
    transaction.status = decision.status
    transaction.status_reason = decision.reason
    return [
        Match(
            organization_id=transaction.organization_id,
            transaction=transaction,
            line_item=proposal.line_item,
            amount=transaction.amount,
            reason=proposal.reason,
            status=Match.Status.PROPOSED,
        )
        for proposal in decision.proposals
    ]
