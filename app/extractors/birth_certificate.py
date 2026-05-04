"""Birth certificate field extractor.

Birth certificates have no MRZ, so extraction is purely label-driven. Layout
varies a lot across the years: the labels below cover the most common Uzbek
templates (Cyrillic and Latin) plus their Russian counterparts. OCR output
on these documents is typically much noisier than on passports — many fields
return None for older or photographed templates, and that's expected.
"""

from __future__ import annotations

import re

from app.extractors.base import BaseExtractor, ExtractionContext
from app.schemas.responses import BirthCertificateFields
from app.utils.date_parser import parse_date

_SERIES_RE = re.compile(r"\b([IVX]{1,4}-[A-Z]{2,3})\b")
_NUMBER_RE = re.compile(
    r"(?:№|No\.?|N\.?|#)\s*(\d{4,8})", flags=re.IGNORECASE
)
_DATE_RE = re.compile(r"\b(\d{1,2}[.\-/\s]\d{1,2}[.\-/\s]\d{2,4})\b")

_LBL_FAMILY = ("Familiya", "Фамилия", "Фамилияси", "Surname")
_LBL_GIVEN = ("Ismi", "Имя", "Given names", "Given name")
_LBL_DOB = ("Tug'ilgan sanasi", "Tug'ilgan vaqti", "Дата рождения", "Date of birth")
_LBL_POB = ("Tug'ilgan joyi", "Место рождения", "Place of birth")
_LBL_SEX = ("Jinsi", "Пол", "Sex")
_LBL_FATHER = ("Otasi", "Отец", "Father")
_LBL_FATHER_NAT = ("Otasining millati", "Национальность отца", "Otasining millati / Nationality")
_LBL_MOTHER = ("Onasi", "Мать", "Mother")
_LBL_MOTHER_NAT = ("Onasining millati", "Национальность матери")
_LBL_REGISTRY = (
    "FHDYO",
    "Qayd etish joyi",
    "ЗАГС",
    "Registry office",
    "Место регистрации",
)
_LBL_REG_NUMBER = ("Yozuv akti", "Запись акта", "Registration")
_LBL_REG_DATE = ("Ro'yxatga olingan", "Дата регистрации", "Registration date")
_LBL_ISSUE_DATE = ("Berilgan vaqti", "Berilgan sana", "Дата выдачи", "Date of issue")


class BirthCertificateExtractor(BaseExtractor):
    """Extracts birth certificate fields from OCR text."""

    def extract(self, ctx: ExtractionContext) -> tuple[BirthCertificateFields, list[str]]:
        """Return parsed `BirthCertificateFields` and the list of low-confidence keys."""
        text = ctx.raw_text
        low: list[str] = []

        series = self.find_first(text, _SERIES_RE)
        number = self.find_first(text, _NUMBER_RE)

        child_surname = self.find_value_after_label(text, _LBL_FAMILY)
        child_given = self.find_value_after_label(text, _LBL_GIVEN)
        dob_raw = self.find_value_after_label(text, _LBL_DOB, value_pattern=_DATE_RE)
        pob_raw = self.find_value_after_label(text, _LBL_POB)
        sex_raw = self.find_value_after_label(text, _LBL_SEX, max_lookahead=2)

        father = self.find_value_after_label(text, _LBL_FATHER)
        father_nat = self.find_value_after_label(text, _LBL_FATHER_NAT)
        mother = self.find_value_after_label(text, _LBL_MOTHER)
        mother_nat = self.find_value_after_label(text, _LBL_MOTHER_NAT)

        registry = self.find_value_after_label(text, _LBL_REGISTRY)
        reg_number = self.find_value_after_label(text, _LBL_REG_NUMBER)
        reg_date_raw = self.find_value_after_label(
            text, _LBL_REG_DATE, value_pattern=_DATE_RE
        )
        issue_raw = self.find_value_after_label(
            text, _LBL_ISSUE_DATE, value_pattern=_DATE_RE
        )

        dob = parse_date(dob_raw)
        reg_date = parse_date(reg_date_raw)
        issue = parse_date(issue_raw)

        for name, val in {
            "child_surname": child_surname,
            "child_given_names": child_given,
            "child_date_of_birth": dob,
        }.items():
            if not val:
                low.append(name)

        return (
            BirthCertificateFields(
                certificate_series=series,
                certificate_number=number,
                child_surname=child_surname,
                child_given_names=child_given,
                child_date_of_birth=dob,
                child_date_of_birth_raw=dob_raw if not dob else None,
                child_place_of_birth=pob_raw,
                child_sex=self._normalize_sex(sex_raw),
                father_full_name=father,
                father_nationality=father_nat,
                mother_full_name=mother,
                mother_nationality=mother_nat,
                registry_office=registry,
                registration_number=reg_number,
                registration_date=reg_date,
                registration_date_raw=reg_date_raw if not reg_date else None,
                date_of_issue=issue,
                date_of_issue_raw=issue_raw if not issue else None,
            ),
            low,
        )

    @staticmethod
    def _normalize_sex(raw: str | None) -> str | None:
        if not raw:
            return None
        token = raw.strip().lower()
        if token.startswith(("m", "о", "э", "u")):
            return "M"
        if token.startswith(("f", "ж", "а", "q")):
            return "F"
        return None
