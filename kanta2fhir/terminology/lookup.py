"""Terminology lookups backed by the CSV tables in ``data/`` and the local title cache."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from kanta2fhir.model import Coding

DATA = Path(__file__).parent / "data"
VOCAB = Path(__file__).resolve().parents[2] / "vocab"
TITLE_CACHE = VOCAB / "tx_titles.csv"

LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"
ATC = "http://www.whocc.no/atc"
ICD10_WHO = "http://hl7.org/fhir/sid/icd-10"
UCUM = "http://unitsofmeasure.org"
V3_INTERPRETATION = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"

# Kanta code systems that get special treatment
ICD10_FI = "1.2.246.537.6.1.1999"
LAB_FI = "1.2.246.537.6.3.2006"
INTERPRETATION_FI = "1.2.246.537.5.78.1997"
RESULT_STATUS_FI = "1.2.246.537.5.85.1997"
GENDER_FI = "1.2.246.537.5.1.1997"

_WHO_ICD10_SHAPE = re.compile(r"^[A-Z]\d\d(\.\d)?$")


@dataclass(frozen=True, slots=True)
class FhirCoding:
    system: str
    code: str
    display: str | None = None
    display_en: str | None = None  # English translation of a non-English display


def _read(name: str, directory: Path = DATA) -> list[dict[str, str]]:
    path = directory / name
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def system_uri(oid: str | None) -> str:
    """FHIR system for a Kanta code system OID (``urn:oid:`` form)."""
    if not oid:
        return "urn:oid:unknown"
    if oid.startswith(("http://", "https://", "urn:")):
        return oid
    return f"urn:oid:{oid}"


_UNIT_SEGMENTS = {"l": "L", "ml": "mL", "dl": "dL", "fl": "fL", "µl": "uL", "ul": "uL"}


def ucum_unit(unit: str | None, table: dict[str, str] | None = None) -> str | None:
    """Normalise a Finnish unit to UCUM: ``mmol/l`` → ``mmol/L``, ``l/min`` → ``L/min``."""
    if unit is None:
        return None
    unit = unit.strip()
    if table and unit in table:
        return table[unit]
    unit = unit.replace("µ", "u")
    return "/".join(_UNIT_SEGMENTS.get(seg, seg) for seg in unit.split("/"))


class Terminology:
    """All terminology lookups. Tables are loaded on first use."""

    def __init__(self, data_dir: Path = DATA, title_cache: Path = TITLE_CACHE) -> None:
        self.data_dir = data_dir
        self.title_cache = title_cache

    # --- tables ------------------------------------------------------------------------

    @cached_property
    def _labfi(self) -> dict[str, dict[str, str]]:
        return {r["code"]: r for r in _read("labfi.csv", self.data_dir)}

    @cached_property
    def _icd10fi(self) -> dict[str, dict[str, str]]:
        return {r["code"]: r for r in _read("icd10fi.csv", self.data_dir)}

    @cached_property
    def _equivalent(self) -> dict[str, str]:
        return {r["oid"]: r["uri"] for r in _read("equivalent_systems.csv", self.data_dir)}

    @cached_property
    def _snomed(self) -> dict[tuple[str, str], dict[str, str]]:
        return {
            (r["source_system"], r["source_code"]): r for r in _read("snomed.csv", self.data_dir)
        }

    @cached_property
    def _interpretation(self) -> dict[str, dict[str, str]]:
        return {r["source_code"]: r for r in _read("interpretation.csv", self.data_dir)}

    @cached_property
    def _result_status(self) -> dict[str, str]:
        return {
            r["source_code"]: r["fhir_status"] for r in _read("result_status.csv", self.data_dir)
        }

    @cached_property
    def _gender(self) -> dict[str, str]:
        return {r["source_code"]: r["fhir_gender"] for r in _read("gender.csv", self.data_dir)}

    @cached_property
    def _ucum(self) -> dict[str, str]:
        return {r["source_unit"]: r["ucum"] for r in _read("ucum.csv", self.data_dir)}

    @cached_property
    def _titles(self) -> dict[tuple[str, str], str]:
        """English titles fetched from tx.fhir.org (git-ignored cache; may be missing)."""
        if not self.title_cache.is_file():
            return {}
        rows = _read(self.title_cache.name, self.title_cache.parent)
        return {(r["system"], r["code"]): r["display"] for r in rows if r.get("display")}

    # --- lookups -----------------------------------------------------------------------

    def title(self, system: str, code: str) -> str | None:
        return self._titles.get((system, code))

    def is_who_icd10(self, code: str) -> bool:
        """A Finnish ICD-10 code that is also a WHO ICD-10 code (D15).

        Finnish additions are listed in the ICD10fi table, so a WHO-shaped code that is not
        in that table is taken to be a WHO code.
        """
        return bool(_WHO_ICD10_SHAPE.match(code)) and code not in self._icd10fi

    def english(self, c: Coding) -> str | None:
        """An English name for a Kanta coding, when one is known."""
        if c.system == LAB_FI and (row := self._labfi.get(c.code)):
            return row["name_en"] or None
        if c.system == ICD10_FI:
            if row := self._icd10fi.get(c.code):
                return row["name_en"] or None
            if self.is_who_icd10(c.code):
                return self.title(ICD10_WHO, c.code)
        if c.system and (uri := self._equivalent.get(c.system)):
            return self.title(uri, c.code)
        return None

    def codings(self, c: Coding) -> list[FhirCoding]:
        """The original coding, followed by any international equivalents."""
        out = [
            FhirCoding(
                system=system_uri(c.system),
                code=c.code,
                display=c.display,
                display_en=self.english(c),
            )
        ]
        out.extend(self.equivalents(c))
        return out

    def equivalents(self, c: Coding) -> list[FhirCoding]:
        out: list[FhirCoding] = []
        if c.system == LAB_FI:
            row = self._labfi.get(c.code)
            if row and row["mapping_status"] == "APPROVED" and row["loinc_code"]:
                out.append(FhirCoding(LOINC, row["loinc_code"], row["loinc_display"] or None))
        elif c.system == ICD10_FI and self.is_who_icd10(c.code):
            out.append(FhirCoding(ICD10_WHO, c.code, self.title(ICD10_WHO, c.code)))
        elif c.system and (uri := self._equivalent.get(c.system)):
            out.append(FhirCoding(uri, c.code, self.title(uri, c.code)))
        if c.system and (row := self._snomed.get((c.system, c.code))):
            out.append(FhirCoding(SNOMED, row["snomed_code"], row["snomed_display"]))
        return out

    def loinc_for_lab(self, code: str) -> FhirCoding | None:
        for fc in self.equivalents(Coding(code=code, system=LAB_FI)):
            if fc.system == LOINC:
                return fc
        return None

    def lab_mapping_status(self, code: str) -> str | None:
        row = self._labfi.get(code)
        return row["mapping_status"] if row else None

    def interpretation(self, c: Coding | None) -> FhirCoding | None:
        if c is None or c.system != INTERPRETATION_FI:
            return None
        row = self._interpretation.get(c.code)
        if row is None:
            return None
        return FhirCoding(V3_INTERPRETATION, row["target_code"], row["target_display"])

    def result_status(self, c: Coding | None, default: str = "final") -> str:
        """FHIR Observation.status for a Kanta result status qualifier."""
        if c is None or c.system != RESULT_STATUS_FI:
            return default
        return self._result_status.get(c.code, "unknown")

    def gender(self, c: Coding | None) -> str:
        if c is None or c.system != GENDER_FI:
            return "unknown"
        return self._gender.get(c.code, "unknown")

    def ucum(self, unit: str | None) -> str | None:
        return ucum_unit(unit, self._ucum)
