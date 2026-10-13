"""``python manage.py seed_demo`` - the only way the demo data is created.

Idempotent: every record is created with ``get_or_create`` on its natural key, so
running the command twice changes nothing. Funded amounts of line items that
already exist are left alone, so re-seeding never undoes an approval; pass
``--reset`` to rebuild the demo organizations from scratch.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from reconciliation.models import (
    BankTransaction,
    CapitalCall,
    InvestorEntity,
    LineItem,
    Organization,
)

ORGANIZATIONS = [
    ("northwind", "Northwind Ventures"),
    ("bluebird", "Bluebird Capital"),
]

# (org slug, call sequence, call date, due date)
CAPITAL_CALLS = [
    ("northwind", 1, "2026-03-25", "2026-04-10"),
    ("northwind", 2, "2026-04-01", "2026-04-20"),
    ("bluebird", 1, "2026-04-01", "2026-04-15"),
]

# (org slug, call sequence, investor entity, expected wire reference, amount called)
LINE_ITEMS = [
    ("northwind", 1, "Haller Capital LLC", "CC-1001", "27500.00"),
    ("northwind", 1, "Rahul Shah Trust", "CC-1002", "25000.00"),
    ("northwind", 1, "Patel Family Trust", "CC-1003", "12500.00"),
    ("northwind", 1, "Meridian Partners LP", "CC-1004", "15000.00"),
    ("northwind", 1, "Oakridge Holdings LLC", "CC-1005", "15000.00"),
    ("northwind", 2, "Oakridge Holdings LLC", "CC-1006", "15000.00"),
    ("bluebird", 1, "Cedar Grove Fund LP", "CC-2001", "40000.00"),
]


class Command(BaseCommand):
    help = "Create the demo organizations, capital calls and line items."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete the demo organizations first, including imported transactions.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            self._reset()

        organizations = {}
        for slug, name in ORGANIZATIONS:
            organization, created = Organization.objects.get_or_create(
                slug=slug, defaults={"name": name}
            )
            organizations[slug] = organization
            self._report("organization", name, created)

        calls = {}
        for slug, sequence, call_date, due_date in CAPITAL_CALLS:
            call, created = CapitalCall.objects.get_or_create(
                organization=organizations[slug],
                sequence=sequence,
                defaults={"call_date": call_date, "due_date": due_date},
            )
            calls[(slug, sequence)] = call
            self._report("capital call", f"{slug} #{sequence}", created)

        for slug, sequence, investor_name, reference, amount in LINE_ITEMS:
            organization = organizations[slug]
            investor, created = InvestorEntity.objects.get_or_create(
                organization=organization, name=investor_name
            )
            self._report("investor entity", f"{slug} {investor_name}", created)

            _line_item, created = LineItem.objects.get_or_create(
                organization=organization,
                capital_call=calls[(slug, sequence)],
                investor_entity=investor,
                defaults={
                    "expected_wire_reference": reference,
                    "amount_called": Decimal(amount),
                    "amount_funded": Decimal("0.00"),
                    "status": LineItem.Status.OPEN,
                },
            )
            self._report("line item", f"{slug} {reference}", created)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete: {Organization.objects.count()} organizations, "
                f"{CapitalCall.objects.count()} capital calls, "
                f"{LineItem.objects.count()} line items."
            )
        )

    def _reset(self) -> None:
        """Remove the demo organizations, child rows first.

        ``LineItem.investor_entity`` is PROTECTed, so an investor who has line
        items cannot be deleted by accident; the reset path deletes in order.
        """
        organizations = Organization.objects.filter(slug__in=[slug for slug, _ in ORGANIZATIONS])
        removed = 0
        for model in (BankTransaction, LineItem, InvestorEntity, CapitalCall):
            deleted, _ = model.objects.filter(organization__in=organizations).delete()
            removed += deleted
        deleted, _ = organizations.delete()
        self.stdout.write(f"Reset: removed {removed + deleted} demo records.")

    def _report(self, kind: str, label: str, created: bool) -> None:
        verb = "created" if created else "already present"
        self.stdout.write(f"  {kind} {label}: {verb}")
