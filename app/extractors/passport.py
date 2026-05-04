"""Passport (TD3 MRZ) field extractor.

Real-world Uzbek passport OCR has labels in mixed scripts. We accept three
shapes for every field:

1. MRZ — the gold standard for surname/given/nationality/dob/expiry/sex.
2. Visual label on its own line, value on the next line.
3. Visual label inline with trailing text on the same line.

Anywhere two paths conflict, the MRZ wins because its check digits make it
self-validating.
"""

from __future__ import annotations

import re

from app.extractors.base import BaseExtractor, ExtractionContext
from app.schemas.responses import PassportFields
from app.utils.date_parser import parse_date

_DOC_NUMBER_RE = re.compile(r"\b([A-Z]{1,2}\s?\d{6,9})\b")
# Uzbek PINFL/JShShIR is 14 digits, but OCR sometimes adds/drops one.
_PINFL_RE = re.compile(r"\b(\d{13,15})\b")
_DATE_RE = re.compile(r"\b(\d{1,2}[.\-/\s]\d{1,2}[.\-/\s]\d{2,4})\b")
_NAME_RE = re.compile(r"^[A-ZА-ЯЁҒҚҲЎ' \-]{2,}$")
_LBL_DOC_NUMBER = (
    "PASSPORT NO",
    "PASSPORT №",
    "PASSPORT N",
    "PASPORT NO",
    "DOCUMENT NO",
    "ПАСПОРТ",
    "ПАСПОРТ РАКАМИ",
    "PASPORT RAQAMI",
    "DOCUMENT NUMBER",
    "ID NUMBER",
    "ID №",
)

# Aggregate label dictionaries — uz Cyrillic + uz Latin + ru + en.
_LBL_SURNAME = (
    "ФАМИЛИЯСИ",
    "ФАМИЛИЯ",
    "FAMILIYASI",
    "FAMILIYA",
    "SURNAME",
)
_LBL_GIVEN = (
    "ИСМИ",
    "ИМЯ",
    "ISMI",
    "GIVEN NAMES",
    "GIVEN NAME",
    "GIVEN NAME(S)",
)
_LBL_NATIONALITY = (
    "МИЛЛАТИ",
    "НАЦИОНАЛЬНОСТЬ",
    "MILLATI",
    "NATIONALITY",
    "FUQAROLIGI",
)
_LBL_DOB = (
    "ТУҒИЛГАН ВАКТИ",
    "ТУГИЛГАН ВАКТИ",
    "ДАТА РОЖДЕНИЯ",
    "TUG'ILGAN SANASI",
    "TUG'ILGAN VAKTI",
    "TUGILGAN SANASI",
    "DATE OF BIRTH",
)
_LBL_POB = (
    "ТУҒИЛГАН ЖОЙИ",
    "МЕСТО РОЖДЕНИЯ",
    "TUG'ILGAN JOYI",
    "TUGILGAN JOYI",
    "PLACE OF BIRTH",
)
_LBL_ISSUE = (
    "БЕРИЛГАН ВАКТИ",
    "ДАТА ВЫДАЧИ",
    "BERILGAN SANASI",
    "BERILGAN VAQTI",
    "BERILGAN SANA",
    "DATE OF ISSUE",
)
_LBL_EXPIRY = (
    "АМАЛ ҚИЛИШ МУХЛАТИ",
    "АМАЛ КИЛИШ МУХЛАТИ",
    "ДЕЙСТВИТЕЛЕН ДО",
    "СРОК ДЕЙСТВИЯ",
    "AMAL QILISH MUDDATI",
    "AMAL QILISH MUXLATI",
    "DATE OF EXPIRY",
)
_LBL_AUTHORITY = (
    "КИМ ТОМОНИДАН БЕРИЛГАН",
    "КЕМ ВЫДАН",
    "AUTHORITY",
    "BERILGAN JOYI",
    "PLACE OF ISSUE",
    "PERSONALLASHTIRISH ORGANI",
    "ISSUING AUTHORITY",
)
_LBL_SEX = ("ЖИНСИ", "JINSI", "ПОЛ", "SEX")


class PassportExtractor(BaseExtractor):
    """Extracts passport fields by combining MRZ data with visual labels."""

    def extract(self, ctx: ExtractionContext) -> tuple[PassportFields, list[str]]:
        """Return parsed `PassportFields` and a list of low-confidence keys."""
        text = ctx.raw_text
        mrz = ctx.mrz
        low: list[str] = []

        document_number = (mrz.document_number if mrz else None) or self._find_doc_number(text)
        surname = (mrz.surname if mrz else None) or self._find_surname(text)
        given = (mrz.given_names if mrz else None) or self._find_given(text)
        nationality_raw = (mrz.nationality if mrz else None) or self.find_value_after_label(
            text, _LBL_NATIONALITY
        )
        if not nationality_raw:
            nationality_raw = self._find_iso_nationality(text)

        dob_raw = self.find_value_after_label(
            text, _LBL_DOB, value_pattern=_DATE_RE
        )
        issue_raw = self.find_value_after_label(
            text, _LBL_ISSUE, value_pattern=_DATE_RE
        )
        expiry_raw = self.find_value_after_label(
            text, _LBL_EXPIRY, value_pattern=_DATE_RE
        )
        # When the issue + expiry labels share a line and the value line holds
        # both dates, the same first match captures for both. Use the second
        # date in that shared line as the expiry override.
        if issue_raw and expiry_raw and issue_raw == expiry_raw:
            second = self._second_date_after_label(text, _LBL_ISSUE + _LBL_EXPIRY)
            if second and second != issue_raw:
                expiry_raw = second

        place_raw = self.find_value_after_label(text, _LBL_POB)
        nationality, place_of_birth = self._split_nationality_and_place(
            nationality_raw, place_raw
        )

        authority = self.find_value_after_label(text, _LBL_AUTHORITY)
        personal = (mrz.personal_number if mrz else None) or self.find_first(
            text, _PINFL_RE
        )

        sex = mrz.sex if mrz else self._find_sex(text)

        date_of_birth = mrz.date_of_birth if mrz else parse_date(dob_raw)
        date_of_expiry = mrz.date_of_expiry if mrz else parse_date(expiry_raw)
        date_of_issue = parse_date(issue_raw)

        for name, value in {
            "document_number": document_number,
            "surname": surname,
            "given_names": given,
            "date_of_birth": date_of_birth,
            "date_of_expiry": date_of_expiry,
        }.items():
            if not value:
                low.append(name)

        return (
            PassportFields(
                document_number=document_number,
                surname=surname,
                given_names=given,
                nationality=nationality,
                date_of_birth=date_of_birth,
                date_of_birth_raw=dob_raw if not date_of_birth else None,
                sex=sex,
                place_of_birth=place_of_birth,
                date_of_issue=date_of_issue,
                date_of_issue_raw=issue_raw if not date_of_issue else None,
                date_of_expiry=date_of_expiry,
                date_of_expiry_raw=expiry_raw if not date_of_expiry else None,
                issuing_authority=authority,
                personal_number=personal,
                mrz_line_1=mrz.raw_lines[0] if mrz and mrz.raw_lines else None,
                mrz_line_2=mrz.raw_lines[1] if mrz and len(mrz.raw_lines) > 1 else None,
                mrz_check_digits_valid=mrz.check_digits_valid if mrz else None,
            ),
            low,
        )

    # ------------------------------------------------------------------ #
    # Field-specific helpers
    # ------------------------------------------------------------------ #

    def _find_surname(self, text: str) -> str | None:
        """Surname is usually a single all-caps token under the label line."""
        candidate = self.find_value_after_label(text, _LBL_SURNAME)
        return self._clean_name(candidate)

    def _find_given(self, text: str) -> str | None:
        """Given names — same logic as surname; may have multiple words."""
        candidate = self.find_value_after_label(text, _LBL_GIVEN)
        return self._clean_name(candidate)

    @staticmethod
    def _clean_name(value: str | None) -> str | None:
        """Drop OCR junk before/after a name token."""
        if not value:
            return None
        # Take the first all-caps run of the candidate (OCR often prefixes "р " etc.)
        m = re.search(r"([A-ZА-ЯЁҒҚҲЎ'][A-ZА-ЯЁҒҚҲЎ' \-]{1,})", value)
        if m:
            return m.group(1).strip()
        return None if not _NAME_RE.match(value) else value

    def _find_doc_number(self, text: str) -> str | None:
        """Search for a passport-style serial: 1–2 letters + 6–9 digits."""
        labelled = self.find_value_after_label(
            text, _LBL_DOC_NUMBER, value_pattern=_DOC_NUMBER_RE
        )
        if labelled:
            return labelled.replace(" ", "")
        for line in text.splitlines():
            m = _DOC_NUMBER_RE.search(line.upper())
            if m:
                return m.group(1).replace(" ", "")
        return None

    def _find_sex(self, text: str) -> str | None:
        """Visual sex marker — `M`/`F` near a SEX/JINSI/ПОЛ label."""
        candidate = self.find_value_after_label(text, _LBL_SEX, max_lookahead=2)
        if candidate:
            token = candidate.strip().upper()
            if token.startswith(("M", "Э", "ER", "MA")):
                return "M"
            if token.startswith(("F", "А", "AY", "WO")):
                return "F"
        # Substring match on Uzbek words — these appear on dual-script docs even
        # when the SEX/JINSI label itself is mangled by OCR.
        upper = text.upper()
        if re.search(r"\bERKAK\b|\bЭРКАК\b", upper):
            return "M"
        if re.search(r"\bAYOL\b|\bАЁЛ\b", upper):
            return "F"
        return None

    @staticmethod
    def _find_iso_nationality(text: str) -> str | None:
        """Capture a stand-alone 3-letter country code (UZB / RUS / KAZ ...)."""
        m = re.search(r"\b(UZB|RUS|KAZ|KGZ|TJK|TKM)\b", text)
        return m.group(1) if m else None

    @staticmethod
    def _second_date_after_label(text: str, labels: tuple[str, ...]) -> str | None:
        """Return the second `_DATE_RE` match on the line *after* any label."""
        from app.extractors.base import _normalize_for_match  # local import to avoid cycle
        lines = text.splitlines()
        for i, raw_line in enumerate(lines):
            line = _normalize_for_match(raw_line)
            if any(_normalize_for_match(label) in line for label in labels):
                for j in range(i + 1, min(i + 3, len(lines))):
                    matches: list[str] = _DATE_RE.findall(lines[j])
                    if len(matches) >= 2:
                        return str(matches[1])
        return None

    @staticmethod
    def _split_nationality_and_place(
        nationality: str | None, place: str | None
    ) -> tuple[str | None, str | None]:
        """If both fields collapsed to the same merged value, split on whitespace.

        Common pattern: `МИЛЛАТИ ТУҒИЛГАН ЖОЙИ` labels on one line cause both
        captures to return `"УЗБЕК ТОШКЕНТ"`. We pick the first token as the
        nationality and the rest as the place of birth.
        """
        if (
            nationality
            and place
            and nationality == place
            and len(nationality.split()) >= 2
        ):
            tokens = re.split(r"[\s/(]+", nationality, maxsplit=1)
            head = tokens[0].strip(" /(),.")
            tail = tokens[1].strip(" /(),.") if len(tokens) > 1 else None
            return head or None, tail or None
        # Trim a stray opening parenthesis OCR sometimes injects.
        if place:
            place = place.lstrip("(").strip()
        return nationality, place
