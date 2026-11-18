import re
import subprocess
import sys
from pathlib import Path

import pytest

from kanta2fhir.cli import main
from kanta2fhir.fhir.hdr import PROFILES, SECTIONS, build_discharge_reports, inpatient_stays
from kanta2fhir.pipeline import PipelineResult, run
from kanta2fhir.terminology import Terminology
from kanta2fhir.validate import validator_available

from .conftest import FIXTURES

SYNTHETIC = FIXTURES / "synthetic" / "inpatient.ndjson"
TS = "2026-11-18T12:00:00+02:00"
T = Terminology()


@pytest.fixture(scope="module")
def synthetic() -> PipelineResult:
    return run(SYNTHETIC)


@pytest.fixture(scope="module")
def hdr(synthetic: PipelineResult) -> dict:
    [(stem, bundle)] = build_discharge_reports(synthetic.patients[0], T, TS)
    assert stem == "1.2.246.10.99999999.1.2025.100.2"
    return bundle


def resolve(bundle: dict, ref: dict) -> dict:
    return next(e["resource"] for e in bundle["entry"] if e["fullUrl"] == ref["reference"])


def sections(bundle: dict) -> dict[str, dict]:
    return {s["code"]["coding"][0]["code"]: s for s in bundle["entry"][0]["resource"]["section"]}


def text(section: dict) -> str:
    return re.sub(r"<[^>]+>", " ", section["text"]["div"])


def test_inpatient_stays(synthetic: PipelineResult, sample_result: PipelineResult) -> None:
    assert len(inpatient_stays(synthetic.patients[0])) == 1
    assert inpatient_stays(sample_result.patients[0]) == []  # outpatient visits only


def test_bundle_composition_and_encounter(hdr: dict) -> None:
    assert hdr["meta"]["profile"] == [PROFILES["Bundle"]]
    assert hdr["language"] == "fi"
    comp = hdr["entry"][0]["resource"]
    assert comp["type"]["coding"][0] == {
        "system": "http://loinc.org",
        "code": "34105-7",
        "display": "Hospital Discharge Summary",
    }
    assert comp["identifier"]["value"] == "urn:oid:1.2.246.10.99999999.1.2025.101"
    assert resolve(hdr, comp["author"][0])["resourceType"] == "PractitionerRole"
    enc = resolve(hdr, comp["encounter"])
    assert enc["meta"]["profile"] == [PROFILES["Encounter"]]
    assert enc["class"]["code"] == "IMP"
    assert enc["status"] == "finished"
    assert enc["period"] == {
        "start": "2025-03-10T14:30:00+02:00",
        "end": "2025-03-17T11:00:00+02:00",
    }
    assert [(d["use"]["coding"][0]["code"], d.get("rank")) for d in enc["diagnosis"]] == [
        ("DD", 1),
        ("DD", None),
    ]


def test_sections(hdr: dict) -> None:
    s = sections(hdr)
    order = [x.code for x in SECTIONS]
    assert list(s) == sorted(s, key=order.index)
    assert "8648-8" in s and "18842-5" in s  # cmp-hdr-2: hospital course or discharge summary
    assert "rintakivun" in text(s["67851-6"])  # admission evaluation ← heading 21
    assert "Kotiutetaan" in text(s["18842-5"])  # discharge summary ← heading 62
    assert "pallolaajennus" in text(s["8648-8"])  # hospital course ← phase 15 narrative
    assert "Osastohoitojakso 2025-03-10 - 2025-03-17" in text(s["8648-8"])
    assert "Tikagrelori" in text(s["75311-1"])  # discharge medications ← heading 55
    assert "Kontrolli" in text(s["18776-5"])  # plan of care ← heading 75
    assert all(sec["text"]["div"] for sec in s.values())


def test_structured_entries(hdr: dict) -> None:
    s = sections(hdr)
    diagnoses = [resolve(hdr, e) for e in s["11535-2"]["entry"]]
    assert [d["code"]["coding"][0]["code"] for d in diagnoses] == ["I21.4", "E11.9"]
    assert {d["clinicalStatus"]["coding"][0]["code"] for d in diagnoses} == {"active"}
    [procedure] = [resolve(hdr, e) for e in s["10185-7"]["entry"]]
    assert procedure["performedDateTime"] == "2025-03-11"
    results = [resolve(hdr, e) for e in s["30954-2"]["entry"]]
    loinc = {
        c["code"] for r in results for c in r["code"]["coding"] if c["system"].endswith("loinc.org")
    }
    assert loinc == {"6598-7", "1988-5", "718-7"}  # troponin T, CRP, haemoglobin
    assert len(s["8716-3"]["entry"]) == 1


def test_deterministic(synthetic: PipelineResult, hdr: dict) -> None:
    [(_, again)] = build_discharge_reports(synthetic.patients[0], T, TS)
    assert again == hdr


def test_fixture_generator_is_reproducible(tmp_path: Path) -> None:
    before = SYNTHETIC.read_bytes()
    root = Path(__file__).parent.parent
    subprocess.run(
        [sys.executable, str(root / "tools" / "make_synthetic_inpatient.py")], check=True, cwd=root
    )
    assert SYNTHETIC.read_bytes() == before


@pytest.mark.validator
def test_hdr_validates(tmp_path: Path) -> None:
    if not validator_available():
        pytest.skip("FHIR validator not available")
    assert main([str(SYNTHETIC), "--out", str(tmp_path), "--targets", "hdr", "--validate"]) == 0
