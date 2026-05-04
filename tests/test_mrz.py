"""Pure unit tests for MRZ parsing and check-digit logic."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.mrz_parser import (
    compute_check_digit,
    parse_mrz_from_text,
    parse_td1,
    parse_td3,
)


@pytest.mark.parametrize(
    "field,expected",
    [
        ("AB2134", 5),
        ("L898902C3", 6),
        ("ZE184226B", 1),
        ("520727", 3),
    ],
)
def test_check_digit_examples_from_icao_9303(field: str, expected: int) -> None:
    assert compute_check_digit(field) == expected


_TD3_LINE1 = "P<UZBKARIMOV<<ALISHER<<<<<<<<<<<<<<<<<<<<<<<"
_TD3_LINE2 = "AA12345670UZB9005120M30010101234567890123400"


def test_td3_parser_extracts_expected_fields() -> None:
    assert len(_TD3_LINE1) == 44 and len(_TD3_LINE2) == 44
    result = parse_td3(_TD3_LINE1, _TD3_LINE2)
    assert result.format == "TD3"
    assert result.surname == "KARIMOV"
    assert result.given_names == "ALISHER"
    assert result.nationality == "UZB"
    assert result.sex == "M"
    assert result.date_of_birth == date(1990, 5, 12)


def test_td1_parser_extracts_expected_fields() -> None:
    line1 = "I<UZBAA1234567<<<<<<<<<<<<<<<<"
    line2 = "9005120M3001017UZB<<<<<<<<<<<8"
    line3 = "KARIMOV<<ALISHER<<<<<<<<<<<<<<"
    assert len(line1) == 30 and len(line2) == 30 and len(line3) == 30
    result = parse_td1(line1, line2, line3)
    assert result.format == "TD1"
    assert result.surname == "KARIMOV"
    assert result.given_names == "ALISHER"


def test_parse_mrz_from_text_picks_td3() -> None:
    text = f"Some header text\n{_TD3_LINE1}\n{_TD3_LINE2}\n"
    parsed = parse_mrz_from_text(text)
    assert parsed is not None
    assert parsed.format == "TD3"


def test_parse_mrz_from_text_returns_none_on_garbage() -> None:
    assert parse_mrz_from_text("hello world") is None
