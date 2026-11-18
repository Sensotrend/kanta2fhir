import json
from pathlib import Path

import pytest

from kanta2fhir.cli import main
from kanta2fhir.fhir.eps import PROFILES, SECTIONS, VITAL_SIGNS, build_patient_summaries
from kanta2fhir.pipeline import PipelineResult
from kanta2fhir.terminology import Terminology
from kanta2fhir.validate import validator_available

from .conftest import SAMPLE

TS = "2026-11-18T12:00:00+02:00"
T = Terminology()
EPS_PACKAGE = Path.home() / ".fhir" / "packages" / "hl7.fhir.eu.eps#1.0.0-ballot" / "package"


def build(result: PipelineResult) -> dict:
    [(_, bundle)] = build_patient_summaries(result.patients[0], T, TS)
    return bundle


def sections(bundle: dict) -> dict[str, dict]:
    return {s["code"]["coding"][0]["code"]: s for s in bundle["entry"][0]["resource"]["section"]}


def resolve(bundle: dict, ref: dict) -> dict:
    return next(e["resource"] for e in bundle["entry"] if e["fullUrl"] == ref["reference"])


@pytest.fixture(scope="module")
def sample_eps(sample_result: PipelineResult) -> dict:
    return build(sample_result)


def test_composition_and_bundle(sample_eps: dict) -> None:
    assert sample_eps["meta"]["profile"] == [PROFILES["Bundle"]]
    comp = sample_eps["entry"][0]["resource"]
    assert comp["type"]["coding"][0]["code"] == "60591-5"
    assert resolve(sample_eps, comp["author"][0])["resourceType"] == "Device"
    patient = resolve(sample_eps, comp["subject"])
    assert patient["meta"]["profile"] == [PROFILES["Patient"]]


def test_sections_in_profile_order_with_empty_reasons(sample_eps: dict) -> None:
    codes = list(sections(sample_eps))
    order = [s.code for s in SECTIONS]
    assert codes == sorted(codes, key=order.index)
    for s in SECTIONS:
        if s.required:
            assert s.code in codes
    for code in ("10160-0", "46264-8", "47519-4"):  # medication, devices, procedures: no data
        section = sections(sample_eps)[code]
        assert "entry" not in section
        assert section["emptyReason"]["coding"][0]["code"] == "unavailable"
        assert section["text"]["div"]


def test_active_and_past_problems(sample_eps: dict) -> None:
    s = sections(sample_eps)
    active = [resolve(sample_eps, e) for e in s["11450-4"]["entry"]]
    past = [resolve(sample_eps, e) for e in s["11348-0"]["entry"]]
    assert [c["code"]["coding"][0]["code"] for c in active] == ["Q32.11", "L43.3"]
    assert [c["code"]["coding"][0]["code"] for c in past] == ["E55.9"]
    assert past[0]["clinicalStatus"]["coding"][0]["code"] == "inactive"
    assert active[0]["clinicalStatus"]["coding"][0]["code"] == "active"
    assert active[0]["verificationStatus"]["coding"][0]["code"] == "confirmed"
    # Finnish-only code: no WHO coding; WHO code: WHO coding added
    assert [c["system"] for c in active[0]["code"]["coding"]] == ["urn:oid:1.2.246.537.6.1.1999"]
    assert "http://hl7.org/fhir/sid/icd-10" in [c["system"] for c in past[0]["code"]["coding"]]


def test_allergy(sample_eps: dict) -> None:
    [ref] = sections(sample_eps)["48765-2"]["entry"]
    allergy = resolve(sample_eps, ref)
    assert [c["code"] for c in allergy["code"]["coding"]] == ["M01AE03", "M01AE03"]
    assert allergy["criticality"] == "high"
    assert allergy["category"] == ["medication"]
    manifestation = allergy["reaction"][0]["manifestation"][0]
    assert manifestation["coding"][0]["code"] == "J46"
    assert manifestation["text"] == "Kipulääkkeen aiheuttama astmakohtaus"
    assert allergy["note"][0]["text"] == "Ei saa käyttää tulehduskipulääkkettä"


def test_immunization(sample_eps: dict) -> None:
    [ref] = sections(sample_eps)["11369-6"]["entry"]
    imm = resolve(sample_eps, ref)
    systems = [c["system"] for c in imm["vaccineCode"]["coding"]]
    assert systems == [
        "urn:oid:1.2.246.537.6.32.2007",
        "http://www.whocc.no/atc",
        "urn:oid:1.2.246.537.6.55",
    ]
    protocol = imm["protocolApplied"][0]
    assert protocol["doseNumberPositiveInt"] == 1
    targets = [c["coding"][-1]["code"] for c in protocol["targetDisease"]]
    assert targets == ["397430003", "76902006"]  # SNOMED CT: diphtheria, tetanus
    assert imm["performer"][0]["function"]["coding"][0]["code"] == "AP"
    assert imm["lotNumber"] == "12345"


def test_results_and_vital_signs(results_result: PipelineResult) -> None:
    bundle = build(results_result)
    s = sections(bundle)
    vitals = [resolve(bundle, e) for e in s["8716-3"]["entry"]]
    [weight] = vitals
    assert weight["meta"]["profile"] == [VITAL_SIGNS]
    assert [c["code"] for c in weight["code"]["coding"]] == ["3141-9", "3141-9", "29463-7"]
    results = [resolve(bundle, e) for e in s["30954-2"]["entry"]]
    categories = {r["category"][0]["coding"][0]["code"] for r in results}
    assert categories == {"laboratory", "imaging", "exam"}  # exam: PEF
    assert len(results) == 10 + 7 + 1


def test_care_plan(careplan_result: PipelineResult) -> None:
    bundle = build(careplan_result)
    [ref] = sections(bundle)["18776-5"]["entry"]
    plan = resolve(bundle, ref)
    assert plan["intent"] == "plan" and plan["status"] == "active"
    goal = resolve(bundle, plan["goal"][0])
    assert len(goal["target"]) == 2
    assert [a["detail"]["status"] for a in plan["activity"]] == ["scheduled", "scheduled"]
    assert any(note["text"].startswith("Lääkityslista") for note in plan["note"])
    team = resolve(bundle, plan["careTeam"][0])
    assert len(team["participant"]) == 4
    # The free-text medication list is shown in the (empty) medication section's narrative.
    medication = sections(bundle)["10160-0"]
    assert "Seloken" in medication["text"]["div"]


def test_deterministic(sample_result: PipelineResult, sample_eps: dict) -> None:
    assert build(sample_result) == sample_eps


@pytest.mark.skipif(not EPS_PACKAGE.is_dir(), reason="EPS package not in the FHIR cache")
def test_section_order_matches_profile() -> None:
    sd = json.loads(
        (EPS_PACKAGE / "StructureDefinition-composition-eu-eps.json").read_text(encoding="utf-8")
    )
    slices = [
        e["sliceName"]
        for e in sd["differential"]["element"]
        if e["path"] == "Composition.section" and "sliceName" in e
    ]
    ours = [s.slice for s in SECTIONS if s.slice != "sectionPastProblems"]
    assert ours == slices


@pytest.mark.validator
def test_eps_validates(tmp_path: Path) -> None:
    if not validator_available():
        pytest.skip("FHIR validator not available")
    assert main([str(SAMPLE), "--out", str(tmp_path), "--targets", "eps", "--validate"]) == 0
