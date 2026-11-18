from pathlib import Path
from typing import Any

import pytest

from kanta2fhir.model import Coding
from kanta2fhir.terminology import FhirCoding, Terminology, ucum_unit
from kanta2fhir.terminology.lookup import ATC, ICD10_WHO, LOINC, SNOMED, system_uri
from kanta2fhir.terminology.tx import TxClient

LAB = "1.2.246.537.6.3.2006"
ICD = "1.2.246.537.6.1.1999"


@pytest.fixture
def terminology(tmp_path: Path) -> Terminology:
    cache = tmp_path / "tx_titles.csv"
    cache.write_text(
        "system,code,display,version,found\n"
        f'{ICD10_WHO},E55.9,"Vitamin D deficiency, unspecified",2019,1\n'
        f"{ATC},M01AE03,ketoprofen,2026,1\n",
        encoding="utf-8",
    )
    return Terminology(title_cache=cache)


def test_system_uri() -> None:
    assert system_uri("1.2.246.537.6.3.2006") == "urn:oid:1.2.246.537.6.3.2006"
    assert system_uri("http://loinc.org") == "http://loinc.org"


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("mmol/l", "mmol/L"),
        ("umol/l", "umol/L"),
        ("µmol/l", "umol/L"),
        ("U/l", "U/L"),
        ("l/min", "L/min"),
        ("ml", "mL"),
        ("kg", "kg"),
        ("mGy.cm2", "mGy.cm2"),
        (None, None),
    ],
)
def test_ucum_rules(unit: str | None, expected: str | None) -> None:
    assert ucum_unit(unit) == expected


def test_ucum_table(terminology: Terminology) -> None:
    assert terminology.ucum("mmHg") == "mm[Hg]"
    assert terminology.ucum("x10E9/l") == "10*9/L"


def test_lab_code_gets_loinc_and_english(terminology: Terminology) -> None:
    codings = terminology.codings(Coding("4600", LAB, "P -Kreatiniini"))
    assert codings == [
        FhirCoding(f"urn:oid:{LAB}", "4600", "P -Kreatiniini", "P -Creatinine"),
        FhirCoding(LOINC, "14682-9", "Creatinine [Moles/volume] in Serum or Plasma"),
    ]
    assert terminology.lab_mapping_status("4600") == "APPROVED"


def test_unmapped_lab_code_has_no_loinc(terminology: Terminology) -> None:
    assert terminology.lab_mapping_status("1001") == "UNCHECKED"
    assert terminology.loinc_for_lab("1001") is None
    assert terminology.english(Coding("1001", LAB)) == "Pt-Adrenocorticotropin Test, Card"


def test_icd10_who_and_finnish_codes(terminology: Terminology) -> None:
    # WHO code: WHO coding added, with the WHO title as English name (D15)
    who = terminology.codings(Coding("E55.9", ICD, "Määrittämätön D-vitamiininpuute"))
    assert who[0].display_en == "Vitamin D deficiency, unspecified"
    assert who[1] == FhirCoding(ICD10_WHO, "E55.9", "Vitamin D deficiency, unspecified")
    # Finnish-only code: no WHO coding; English name from ICD10fi
    fi = terminology.codings(Coding("Q32.11", ICD, "Synnynnäinen …"))
    assert len(fi) == 1
    assert fi[0].display_en == "Congenital tracheo-esophageal fissure"
    # WHO-shaped but Finnish (listed in ICD10fi): no WHO coding
    assert not terminology.is_who_icd10("X85.0")
    assert terminology.is_who_icd10("J46")


def test_atc_and_snomed_equivalents(terminology: Terminology) -> None:
    atc = terminology.equivalents(Coding("M01AE03", "1.2.246.537.6.32.2007", "Ketoprofeeni"))
    assert atc == [FhirCoding(ATC, "M01AE03", "ketoprofen")]
    route = terminology.equivalents(Coding("ID", "1.2.246.537.6.111.2007"))
    assert route == [FhirCoding(SNOMED, "372464004", "Intradermal route")]
    vitals = terminology.equivalents(Coding("3141-9", "1.2.246.537.6.96.2008"))
    assert vitals == [FhirCoding(LOINC, "3141-9", None)]  # no title cached in this test


def test_simple_tables(terminology: Terminology) -> None:
    h = terminology.interpretation(Coding("H", "1.2.246.537.5.78.1997"))
    assert h is not None and (h.code, h.display) == ("H", "High")
    assert terminology.interpretation(Coding("?", "1.2.246.537.5.78.1997")) is None
    assert terminology.result_status(Coding("F", "1.2.246.537.5.85.1997")) == "final"
    assert terminology.result_status(Coding("Z", "1.2.246.537.5.85.1997")) == "unknown"
    assert terminology.result_status(None) == "final"
    assert terminology.gender(Coding("2", "1.2.246.537.5.1.1997")) == "female"
    assert terminology.gender(None) == "unknown"


def test_missing_title_cache_is_fine(tmp_path: Path) -> None:
    t = Terminology(title_cache=tmp_path / "missing.csv")
    [_, who] = t.codings(Coding("E55.9", ICD))
    assert who.display is None


def test_tx_client_parses_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    responses: dict[str, dict[str, Any]] = {
        "CodeSystem/$lookup": {
            "resourceType": "Parameters",
            "parameter": [
                {"name": "display", "valueString": "Tetanus"},
                {"name": "version", "valueString": "2026"},
            ],
        },
        "CodeSystem/$validate-code": {
            "resourceType": "Parameters",
            "parameter": [
                {"name": "result", "valueBoolean": False},
                {"name": "message", "valueString": "Wrong display"},
            ],
        },
    }
    client = TxClient("https://example.org/r4")
    monkeypatch.setattr(client, "_get", lambda path, params: responses[path])
    assert client.lookup(SNOMED, "76902006").display == "Tetanus"
    v = client.validate(SNOMED, "76902006", "Wrong")
    assert not v.valid and v.message == "Wrong display"
