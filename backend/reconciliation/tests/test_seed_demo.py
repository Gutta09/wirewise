"""The seed command is the only way the demo data is created, and it is idempotent."""

from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from reconciliation.models import CapitalCall, InvestorEntity, LineItem, Organization

EXPECTED = {
    "northwind": [
        (1, "Haller Capital LLC", "CC-1001", "27500.00"),
        (1, "Rahul Shah Trust", "CC-1002", "25000.00"),
        (1, "Patel Family Trust", "CC-1003", "12500.00"),
        (1, "Meridian Partners LP", "CC-1004", "15000.00"),
        (1, "Oakridge Holdings LLC", "CC-1005", "15000.00"),
        (2, "Oakridge Holdings LLC", "CC-1006", "15000.00"),
    ],
    "bluebird": [(1, "Cedar Grove Fund LP", "CC-2001", "40000.00")],
}


class SeedDemoTests(TestCase):
    def seed(self, *args):
        call_command("seed_demo", *args, stdout=StringIO())

    def test_seed_creates_the_documented_data(self):
        self.seed()

        self.assertEqual(
            sorted(Organization.objects.values_list("slug", flat=True)),
            ["bluebird", "northwind"],
        )
        self.assertEqual(
            Organization.objects.get(slug="northwind").name, "Northwind Ventures"
        )

        call = CapitalCall.objects.get(organization__slug="northwind", sequence=1)
        self.assertEqual(str(call.call_date), "2026-03-25")
        self.assertEqual(str(call.due_date), "2026-04-10")
        second = CapitalCall.objects.get(organization__slug="northwind", sequence=2)
        self.assertEqual(str(second.call_date), "2026-04-01")
        self.assertEqual(str(second.due_date), "2026-04-20")

        for slug, rows in EXPECTED.items():
            for sequence, investor, reference, amount in rows:
                with self.subTest(reference=reference):
                    item = LineItem.objects.get(
                        organization__slug=slug, expected_wire_reference=reference
                    )
                    self.assertEqual(item.capital_call.sequence, sequence)
                    self.assertEqual(item.investor_entity.name, investor)
                    self.assertEqual(item.amount_called, Decimal(amount))
                    self.assertEqual(item.amount_funded, Decimal("0.00"))
                    self.assertEqual(item.status, LineItem.Status.OPEN)

        self.assertEqual(LineItem.objects.count(), 7)
        # Oakridge appears on two calls but is one investor entity.
        self.assertEqual(InvestorEntity.objects.filter(organization__slug="northwind").count(), 5)

    def test_running_the_seed_twice_creates_no_duplicates(self):
        self.seed()
        self.seed()

        self.assertEqual(Organization.objects.count(), 2)
        self.assertEqual(CapitalCall.objects.count(), 3)
        self.assertEqual(InvestorEntity.objects.count(), 6)
        self.assertEqual(LineItem.objects.count(), 7)

    def test_reseeding_does_not_undo_an_approval(self):
        self.seed()
        item = LineItem.objects.get(expected_wire_reference="CC-1003")
        item.amount_funded = Decimal("12500.00")
        item.status = LineItem.Status.FUNDED
        item.save()

        self.seed()

        item.refresh_from_db()
        self.assertEqual(item.amount_funded, Decimal("12500.00"))
        self.assertEqual(item.status, LineItem.Status.FUNDED)

    def test_reset_rebuilds_the_demo_organizations(self):
        self.seed()
        item = LineItem.objects.get(expected_wire_reference="CC-1003")
        item.amount_funded = Decimal("12500.00")
        item.save()

        self.seed("--reset")

        self.assertEqual(LineItem.objects.count(), 7)
        self.assertEqual(
            LineItem.objects.get(expected_wire_reference="CC-1003").amount_funded,
            Decimal("0.00"),
        )
