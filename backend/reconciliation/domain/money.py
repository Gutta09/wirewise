"""Decimal money parsing and formatting. Floats are never used for amounts."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENTS = Decimal("0.01")


class AmountError(ValueError):
    """Raised when a string cannot be read as a money amount."""


def parse_amount(raw: str) -> Decimal:
    """Parse a CSV amount into a ``Decimal``, allowing thousands separators.

    Accepts ``"25,000.00"``, ``"-1 250.50"``, ``"(500.00)"`` and ``"+90"``.
    Rounds half-up to two decimal places, which is the precision the database
    column stores.
    """
    text = (raw or "").strip()
    if not text:
        raise AmountError("amount is required")

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()

    cleaned = text.replace(",", "").replace("_", "").replace(" ", "").replace(" ", "")
    if cleaned in {"", "+", "-"}:
        raise AmountError(f"amount {raw.strip()!r} is not a number")

    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise AmountError(f"amount {raw.strip()!r} is not a number") from None
    if not value.is_finite():
        raise AmountError(f"amount {raw.strip()!r} is not a number")

    if negative:
        value = -value
    value = value.quantize(CENTS, rounding=ROUND_HALF_UP)
    if value == 0:
        raise AmountError("amount must not be zero")
    return value


def format_money(value: Decimal) -> str:
    """Format an amount the way the match reasons read: ``12,500.00``."""
    return f"{value:,.2f}"
