from datetime import date
from decimal import Decimal

import pytest

from bahisync_engine.values import parse_amount, parse_date, parse_spaced_date


@pytest.mark.parametrize(
    "text,value,suffix",
    [
        ("1,23,456.78", "123456.78", None),
        ("123456.78", "123456.78", None),
        ("1,234.50", "1234.50", None),
        ("10,000.00 Cr", "10000.00", "cr"),
        ("5,000.00Dr", "5000.00", "dr"),
        ("-1,144.90", "-1144.90", None),
        ("(250.00)", "-250.00", None),
        ("₹2,300.00", "2300.00", None),
    ],
)
def test_amounts(text, value, suffix):
    assert parse_amount(text) == (Decimal(value), suffix)


@pytest.mark.parametrize("text", ["123456", "SBIN0001234", "ABC", "", "12/04/2026"])
def test_not_amounts(text):
    # Bare integers are cheque/reference numbers, not amounts.
    assert parse_amount(text) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("01/04/2026", date(2026, 4, 1)),
        ("01/04/26", date(2026, 4, 1)),
        ("01-04-2026", date(2026, 4, 1)),
        ("01-Apr-2026", date(2026, 4, 1)),
        ("01-SEPT-26", date(2026, 9, 1)),
        ("2026-04-01", date(2026, 4, 1)),
    ],
)
def test_dates(text, expected):
    assert parse_date(text) == expected


def test_spaced_date():
    assert parse_spaced_date(["01", "Apr", "2026", "x"]) == (date(2026, 4, 1), 3)
    assert parse_spaced_date(["Narration"]) is None
