"""Small builders so each test states only what it cares about."""

from decimal import Decimal

from reconciliation.models import BankTransaction, CapitalCall, InvestorEntity, LineItem, Organization

NORTHWIND_HEADERS = {"X-Organization": "northwind"}
BLUEBIRD_HEADERS = {"X-Organization": "bluebird"}

CSV_HEADER = "date,description,amount,type,reference\n"


def csv_bytes(*rows: str, header: str = CSV_HEADER) -> bytes:
    return (header + "".join(row if row.endswith("\n") else row + "\n" for row in rows)).encode()


def make_organization(slug="northwind", name=None) -> Organization:
    return Organization.objects.create(slug=slug, name=name or slug.title())


def make_capital_call(organization, sequence=1, call_date="2026-03-25", due_date="2026-04-10"):
    return CapitalCall.objects.create(
        organization=organization, sequence=sequence, call_date=call_date, due_date=due_date
    )


def make_line_item(
    organization,
    capital_call=None,
    investor_name="Patel Family Trust",
    reference="CC-1003",
    amount_called="12500.00",
    amount_funded="0.00",
) -> LineItem:
    capital_call = capital_call or make_capital_call(organization)
    investor, _ = InvestorEntity.objects.get_or_create(
        organization=organization, name=investor_name
    )
    item = LineItem.objects.create(
        organization=organization,
        capital_call=capital_call,
        investor_entity=investor,
        expected_wire_reference=reference,
        amount_called=Decimal(amount_called),
        amount_funded=Decimal(amount_funded),
    )
    item.status = item.status_for_funded(item.amount_funded)
    item.save(update_fields=["status"])
    return item


def make_transaction(
    organization,
    date="2026-04-03",
    description="WIRE INCOMING PATEL FAMILY TRUST",
    amount="12500.00",
    type=BankTransaction.Type.CREDIT,
    bank_reference="FT0001",
    status=BankTransaction.Status.NEEDS_REVIEW,
    line=2,
) -> BankTransaction:
    return BankTransaction.objects.create(
        organization=organization,
        date=date,
        description=description,
        amount=Decimal(amount),
        type=type,
        bank_reference=bank_reference,
        status=status,
        source_line_number=line,
    )
