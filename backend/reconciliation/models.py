"""Domain model for Wirewise capital-call reconciliation.

Every record carries its own ``organization`` foreign key. Tenant scoping is a
single ``filter(organization=...)`` on each query, which keeps the rule easy to
audit and impossible to forget behind a join.
"""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from .domain.normalisation import normalise_name, normalise_reference

ZERO = Decimal("0.00")
MONEY = {"max_digits": 18, "decimal_places": 2}


class Organization(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class InvestorEntity(models.Model):
    """The legal entity an LP invests through; this is the name the bank shows."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="investor_entities"
    )
    name = models.CharField(max_length=200)
    normalised_name = models.CharField(max_length=200, editable=False)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="uniq_investor_name_per_org"
            )
        ]

    def save(self, *args, **kwargs):
        self.normalised_name = normalise_name(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class CapitalCall(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="capital_calls"
    )
    # Human-facing number, unique inside an organization ("Capital Call #2").
    sequence = models.PositiveIntegerField()
    call_date = models.DateField()
    due_date = models.DateField()

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "sequence"], name="uniq_call_sequence_per_org"
            )
        ]

    @property
    def label(self) -> str:
        return f"Capital Call #{self.sequence}"

    def __str__(self) -> str:
        return f"{self.organization.slug} {self.label}"


class LineItem(models.Model):
    """One LP's share of one capital call. Payments are matched to line items."""

    class Status(models.TextChoices):
        OPEN = "open"
        PARTIALLY_FUNDED = "partially_funded"
        FUNDED = "funded"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="line_items"
    )
    capital_call = models.ForeignKey(
        CapitalCall, on_delete=models.CASCADE, related_name="line_items"
    )
    investor_entity = models.ForeignKey(
        InvestorEntity, on_delete=models.PROTECT, related_name="line_items"
    )
    expected_wire_reference = models.CharField(max_length=64)
    normalised_reference = models.CharField(max_length=64, editable=False)
    amount_called = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0.01"))])
    amount_funded = models.DecimalField(**MONEY, default=ZERO)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["capital_call__sequence", "expected_wire_reference"]
        constraints = [
            models.UniqueConstraint(
                fields=["capital_call", "investor_entity"],
                name="uniq_line_item_per_call_investor",
            ),
            models.UniqueConstraint(
                fields=["organization", "expected_wire_reference"],
                name="uniq_wire_reference_per_org",
            ),
            # A line item is never funded beyond its amount called, whatever path
            # the write took. The database is the last line of defence.
            models.CheckConstraint(
                condition=models.Q(amount_funded__lte=models.F("amount_called")),
                name="line_item_not_overfunded",
            ),
        ]

    @property
    def amount_remaining(self) -> Decimal:
        return self.amount_called - self.amount_funded

    def status_for_funded(self, amount_funded: Decimal) -> str:
        if amount_funded <= ZERO:
            return self.Status.OPEN
        if amount_funded >= self.amount_called:
            return self.Status.FUNDED
        return self.Status.PARTIALLY_FUNDED

    def save(self, *args, **kwargs):
        self.normalised_reference = normalise_reference(self.expected_wire_reference)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.expected_wire_reference} ({self.investor_entity.name})"


class BankTransaction(models.Model):
    """One row of an imported bank statement."""

    class Status(models.TextChoices):
        SUGGESTED = "suggested"
        NEEDS_REVIEW = "needs_review"
        RECONCILED = "reconciled"
        IGNORED = "ignored"

    class Type(models.TextChoices):
        CREDIT = "credit"
        DEBIT = "debit"

    class SyncStatus(models.TextChoices):
        NOT_SYNCED = "not_synced"
        SYNCED = "synced"
        SYNC_FAILED = "sync_failed"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="transactions"
    )
    date = models.DateField()
    description = models.TextField()
    amount = models.DecimalField(**MONEY)
    type = models.CharField(max_length=10, choices=Type.choices)
    bank_reference = models.CharField(max_length=128)
    status = models.CharField(max_length=20, choices=Status.choices)
    # Why this transaction ended up where it did: set for every needs_review row
    # and for debits, and kept alongside the per-match reasons.
    status_reason = models.TextField(blank=True)
    source_line_number = models.PositiveIntegerField(
        help_text="Line number in the uploaded CSV, where the header is line 1."
    )
    imported_at = models.DateTimeField(auto_now_add=True)

    airtable_record_id = models.CharField(max_length=64, blank=True)
    airtable_sync_status = models.CharField(
        max_length=20, choices=SyncStatus.choices, default=SyncStatus.NOT_SYNCED
    )

    class Meta:
        # Newest first, with the id as a stable tie-breaker inside one date.
        ordering = ["-date", "-id"]
        constraints = [
            # The duplicate rule: a bank reference is unique per organization, so
            # two organizations may legitimately share one.
            models.UniqueConstraint(
                fields=["organization", "bank_reference"], name="uniq_bank_reference_per_org"
            )
        ]

    @property
    def is_credit(self) -> bool:
        return self.type == self.Type.CREDIT

    def __str__(self) -> str:
        return f"{self.bank_reference} {self.amount}"


class Match(models.Model):
    """A proposed, approved or rejected link from one transaction to one line item."""

    class Status(models.TextChoices):
        PROPOSED = "proposed"
        APPROVED = "approved"
        REJECTED = "rejected"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="matches"
    )
    transaction = models.ForeignKey(
        BankTransaction, on_delete=models.CASCADE, related_name="matches"
    )
    line_item = models.ForeignKey(LineItem, on_delete=models.CASCADE, related_name="matches")
    amount = models.DecimalField(**MONEY)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROPOSED)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["transaction", "line_item"], name="uniq_match_per_transaction_line_item"
            ),
            # At most one approved match per transaction.
            models.UniqueConstraint(
                fields=["transaction"],
                condition=models.Q(status="approved"),
                name="uniq_approved_match_per_transaction",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.transaction.bank_reference} -> {self.line_item.expected_wire_reference}"
