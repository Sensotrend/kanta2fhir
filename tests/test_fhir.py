import json
from pathlib import Path

import pytest

from kanta2fhir.fhir import datatypes as dt
from kanta2fhir.fhir.bundle import document_bundle
from kanta2fhir.fhir.profiles import EU_CORE
from kanta2fhir.fhir.resources import ResourceSet
from kanta2fhir.model import Coding, HumanName, Identifier, Quantity
from kanta2fhir.pipeline import PipelineResult
from kanta2fhir.terminology import FhirCoding, Terminology
from kanta2fhir.validate import parse_output, validator_available

from .conftest import ENCOUNTER_ID, SAMPLE, TEST_HETU

T = Terminology()


def test_resource_ids_are_deterministic() -> None:
    assert dt.resource_id("Patient", "x") == dt.resource_id("Patient", "x")
    assert dt.resource_id("Patient", "x") != dt.resource_id("Patient", "y")
    assert dt.full_url("abc") == "urn:uuid:abc"


def test_identifier_forms() -> None:
    assert dt.identifier(Identifier("1.2.3")) == {
        "system": "urn:ietf:rfc:3986",
        "value": "urn:oid:1.2.3",
    }
    assert dt.identifier(Identifier("1.2.3", "abc")) == {"system": "urn:oid:1.2.3", "value": "abc"}
    assert dt.identifier(Identifier("1.2.246.21", masked=True)) is None


def test_coding_with_english_translation() -> None:
    c = dt.coding(FhirCoding("urn:oid:1.2", "4600", "P -Kreatiniini", "P -Creatinine"))
    assert c["display"] == "P -Kreatiniini"
    ext = c["_display"]["extension"][0]
    assert ext["url"] == dt.TRANSLATION
    assert {"url": "lang", "valueCode": "en"} in ext["extension"]
    assert {"url": "content", "valueString": "P -Creatinine"} in ext["extension"]
    # English only: becomes the display itself
    assert dt.coding(FhirCoding("s", "c", None, "English"))["display"] == "English"


def test_codeable_concept_adds_loinc() -> None:
    cc = dt.codeable_concept(Coding("4600", "1.2.246.537.6.3.2006", "P -Kreatiniini"), T)
    assert cc is not None
    assert [c["system"] for c in cc["coding"]] == [
        "urn:oid:1.2.246.537.6.3.2006",
        "http://loinc.org",
    ]
    assert cc["text"] == "P -Kreatiniini"


def test_quantity_and_decimal() -> None:
    assert dt.quantity(Quantity("112", "umol/l"), T) == {
        "value": 112,
        "unit": "umol/l",
        "system": "http://unitsofmeasure.org",
        "code": "umol/L",
    }
    assert dt.decimal("88.0") == 88.0
    assert dt.decimal("5,2") == 5.2
    assert dt.decimal("abc") is None
    assert dt.quantity(Quantity("x", "kg"), T) is None


def test_human_names_with_calling_name() -> None:
    names = dt.human_names(
        HumanName(family=("Potilas",), given=("Testi", "Matti"), calling_name="Matti")
    )
    assert names == [{"use": "official", "family": "Potilas", "given": ["Testi", "Matti"]}]
    names = dt.human_names(HumanName(family=("P",), given=("Testi",), calling_name="Tepi"))
    assert names[1] == {"use": "usual", "given": ["Tepi"]}


def test_resource_set(sample_result: PipelineResult) -> None:
    record = sample_result.patients[0].record
    rs = ResourceSet(T, profiles=EU_CORE)
    patient = rs.patient(record.patient)
    assert rs.patient(record.patient) == patient  # added once
    p = rs.resources[patient["reference"]]
    assert p["meta"]["profile"] == [EU_CORE["Patient"]]
    assert p["identifier"] == [{"system": dt.HETU_SYSTEM, "value": TEST_HETU}]
    assert p["gender"] == "male" and p["birthDate"] == "2001-10-05"

    enc = rs.resources[rs.encounter(record.encounters[ENCOUNTER_ID], patient)["reference"]]
    assert enc["class"]["code"] == "AMB"
    assert enc["status"] == "finished"
    assert enc["serviceProvider"]["reference"].startswith("urn:uuid:")

    # The risk entry's author has both a person and an organisation.
    author = rs.author(sample_result.patients[0].clinical.risks[0].author)
    assert author is not None
    role = rs.resources[author["reference"]]
    assert role["resourceType"] == "PractitionerRole"
    assert role["meta"]["profile"] == [EU_CORE["PractitionerRole"]]

    prov = rs.resources[
        rs.provenance([patient], [record.documents[0].id], "2026-01-01T00:00:00+02:00")["reference"]
    ]
    assert prov["entity"][0]["what"]["identifier"]["value"] == f"urn:oid:{record.documents[0].id}"
    assert prov["agent"][0]["who"]["reference"].startswith("urn:uuid:")
    assert all(r.get("text", {}).get("status") == "generated" for r in rs.resources.values())


def test_document_bundle() -> None:
    composition = {"resourceType": "Composition", "id": "c1"}
    other = ("urn:uuid:p1", {"resourceType": "Patient", "id": "p1"})
    b = document_bundle("eps|x", "2026-01-01T00:00:00+02:00", composition, [other], profile="P")
    assert b["type"] == "document"
    assert b["meta"]["profile"] == ["P"]
    assert b["entry"][0]["resource"] is composition
    assert b["entry"][1]["fullUrl"] == "urn:uuid:p1"
    assert b["identifier"]["value"] == dt.full_url(b["id"])
    assert b["id"] == document_bundle("eps|x", "t", composition, [])["id"]


def test_parse_validator_output() -> None:
    data = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "OperationOutcome",
                    "extension": [
                        {
                            "url": "http://hl7.org/fhir/StructureDefinition/operationoutcome-file",
                            "valueString": "/x/a.json",
                        }
                    ],
                    "issue": [
                        {"severity": "error", "details": {"text": "Bad"}, "expression": ["P.x"]},
                        {"severity": "warning", "details": {"text": "Hmm"}},
                        {"severity": "information", "details": {"text": "All OK"}},
                    ],
                }
            }
        ],
    }
    [r] = parse_output(data)
    assert r.file == "/x/a.json"
    assert r.counts == {"fatal": 0, "error": 1, "warning": 1, "information": 0}
    assert not r.ok
    assert r.messages[0].location == "P.x"


@pytest.mark.validator
def test_shared_resources_validate(tmp_path: Path) -> None:
    if not validator_available():
        pytest.skip("FHIR validator not available")
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
    from validate_shared import build  # type: ignore[import-not-found]

    from kanta2fhir.fhir.profiles import PACKAGES
    from kanta2fhir.validate import run_validator

    files = []
    for i, bundle in enumerate(build(SAMPLE)):
        f = tmp_path / f"shared-{i}.json"
        f.write_text(json.dumps(bundle), encoding="utf-8")
        files.append(f)
    [result] = run_validator(files, PACKAGES["base"], tmp_path / "oo.json")
    assert result.ok, [m for m in result.messages if m.severity in ("error", "fatal")]
