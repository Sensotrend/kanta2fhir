import json
from pathlib import Path

import pytest

from kanta2fhir.cli import main
from kanta2fhir.fhir.lab import (
    COMPOSITION_DR_EXT,
    DR_COMPOSITION_EXT,
    PROFILES,
    build_lab_reports,
    report_inputs,
)
from kanta2fhir.pipeline import PipelineResult
from kanta2fhir.terminology import Terminology
from kanta2fhir.validate import validator_available

from .conftest import RESULTS

TS = "2026-11-18T12:00:00+02:00"
T = Terminology()


def resources(bundle: dict, rtype: str) -> list[dict]:
    return [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == rtype]


def by_ref(bundle: dict) -> dict[str, dict]:
    return {e["fullUrl"]: e["resource"] for e in bundle["entry"]}


def test_report_grouping(results_result: PipelineResult, sample_result: PipelineResult) -> None:
    [group] = report_inputs(results_result.patients[0])
    assert group.document is not None
    assert len(group.results) == 10
    assert [o.category for o in group.orders] == ["laboratory"]

    # Sample: the COVID document, plus Kooste results whose original document is missing.
    groups = report_inputs(sample_result.patients[0])
    assert sorted(len(g.results) for g in groups) == [1, 10]
    kooste = next(g for g in groups if len(g.results) == 10)
    assert kooste.document is None
    assert all(r.source.from_summary for r in kooste.results)


@pytest.fixture(scope="module")
def lab_bundle(results_result: PipelineResult) -> dict:
    [(stem, bundle)] = build_lab_reports(results_result.patients[0], T, TS)
    assert stem == "1.2.246.10.1.20241218125615.93.2009.1132917519546134"
    return bundle


def test_bundle_and_composition(lab_bundle: dict) -> None:
    assert lab_bundle["type"] == "document"
    assert lab_bundle["meta"]["profile"] == [PROFILES["Bundle"]]
    assert lab_bundle["timestamp"] == TS
    composition = lab_bundle["entry"][0]["resource"]
    assert composition["resourceType"] == "Composition"
    assert composition["meta"]["profile"] == [PROFILES["Composition"]]
    [report] = resources(lab_bundle, "DiagnosticReport")

    # Invariants of Bundle-eu-lab: identifiers, type and subject agree; the two link each other.
    assert composition["identifier"] in report["identifier"]
    assert composition["type"] == report["code"]
    assert composition["subject"] == report["subject"]
    assert composition["encounter"] == report["encounter"]
    assert composition["extension"][0]["url"] == COMPOSITION_DR_EXT
    refs = by_ref(lab_bundle)
    assert refs[composition["extension"][0]["valueReference"]["reference"]] is report
    assert report["extension"][0]["url"] == DR_COMPOSITION_EXT
    assert refs[report["extension"][0]["valueReference"]["reference"]] is composition

    [section] = composition["section"]
    assert len(section["entry"]) == 10
    assert section["text"]["div"].startswith('<div xmlns="http://www.w3.org/1999/xhtml">')
    assert 'lang="fi"' in composition["text"]["div"]


def test_observations(lab_bundle: dict) -> None:
    observations = resources(lab_bundle, "Observation")
    assert len(observations) == 10
    assert all(o["performer"] for o in observations)
    crea = next(o for o in observations if o["code"]["coding"][0]["code"] == "4600")
    systems = [c["system"] for c in crea["code"]["coding"]]
    assert systems == [
        "urn:oid:1.2.246.537.6.3.2006",
        "http://loinc.org",
        "urn:oid:1.2.246.10.123456.1.2022",  # local code from <translation>
    ]
    assert crea["valueQuantity"] == {
        "value": 112,
        "unit": "umol/l",
        "system": "http://unitsofmeasure.org",
        "code": "umol/L",
    }
    assert crea["status"] == "final"
    assert crea["interpretation"][0]["coding"][0]["code"] == "H"
    assert crea["referenceRange"][0]["text"] == "miehet"
    assert {"display": "Ville Virtanen"} in crea["performer"]
    assert crea["basedOn"]
    refs = by_ref(lab_bundle)
    assert refs[crea["specimen"]["reference"]]["resourceType"] == "Specimen"

    fractions = next(o for o in observations if o["code"]["coding"][0]["code"] == "2522")
    assert fractions["valueString"].startswith("Koko Proteiinielektroforeesi")


def test_service_requests(lab_bundle: dict) -> None:
    requests = resources(lab_bundle, "ServiceRequest")
    assert len(requests) == 4  # one per requested test (4591, 4600, 2516, 1270)
    requisitions = {json.dumps(sr["requisition"]) for sr in requests}
    assert len(requisitions) == 1  # all from one order
    first = requests[0]
    assert first["occurrenceTiming"]["repeat"]["count"] == 10
    assert first["occurrenceTiming"]["repeat"]["boundsPeriod"] == {
        "start": "2024-12-18",
        "end": "2025-12-31",
    }
    assert first["intent"] == "order"


def test_output_is_deterministic(results_result: PipelineResult, lab_bundle: dict) -> None:
    [(_, again)] = build_lab_reports(results_result.patients[0], T, TS)
    assert again == lab_bundle
    assert len({e["fullUrl"] for e in lab_bundle["entry"]}) == len(lab_bundle["entry"])


def test_cli_writes_lab_documents(tmp_path: Path) -> None:
    assert main([str(RESULTS), "--out", str(tmp_path), "--targets", "lab", "--timestamp", TS]) == 0
    files = list((tmp_path / "lab").glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["timestamp"] == TS


@pytest.mark.validator
def test_lab_documents_validate(tmp_path: Path) -> None:
    if not validator_available():
        pytest.skip("FHIR validator not available")
    code = main([str(RESULTS), "--out", str(tmp_path), "--targets", "lab", "--validate"])
    assert code == 0
