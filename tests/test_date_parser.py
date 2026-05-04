"""Unit tests for the date parser helpers."""

from __future__ import annotations

from datetime import date

import pytest

from app.utils.date_parser import parse_date, parse_mrz_date


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("12.05.2010", date(2010, 5, 12)),
        ("12/05/2010", date(2010, 5, 12)),
        ("2010-05-12", date(2010, 5, 12)),
        ("12 май 2010", date(2010, 5, 12)),
        ("12 мая 2010 г.", date(2010, 5, 12)),
        ("12 may 2010", date(2010, 5, 12)),
        ("12 mart 2010", date(2010, 3, 12)),
        ("01.01.2030", date(2030, 1, 1)),
    ],
)
def test_parse_date_known_formats(raw: str, expected: date) -> None:
    assert parse_date(raw) == expected


def test_parse_date_returns_none_for_garbage() -> None:
    assert parse_date("not a date") is None
    assert parse_date("") is None
    assert parse_date(None) is None


def test_parse_mrz_date_pivot_window() -> None:
    assert parse_mrz_date("900512") == date(1990, 5, 12)
    assert parse_mrz_date("250101") == date(2025, 1, 1)
    assert parse_mrz_date("491231") == date(2049, 12, 31)
    assert parse_mrz_date("500101") == date(1950, 1, 1)


def test_parse_mrz_date_invalid() -> None:
    assert parse_mrz_date("13xxxx") is None
    assert parse_mrz_date("") is None
    assert parse_mrz_date("999999") is None
