"""Entry extractors, checked against Kanta test-environment documents."""

from kanta2fhir.model import Identifier, Quantity, Range
from kanta2fhir.pipeline import PipelineResult

from .conftest import ENCOUNTER_ID


def test_conditions(sample_result: PipelineResult) -> None:
    conditions = sample_result.patients[0].clinical.conditions
    assert [
        (c.code.code, c.primary, c.permanence.code if c.permanence else None) for c in conditions
    ] == [
        ("Q32.11", True, "PYS"),
        ("E55.9", False, "KER"),
        ("L43.3", False, "PYS"),
    ]
    q = conditions[0]
    assert q.code.system == "1.2.246.537.6.1.1999"
    assert q.text == "Synnynnäinen keuhkoputken ja ruokatorven välinen halkeama"
    assert q.recorded == "2024-12-18"
    assert q.certainty is not None and q.certainty.code == "TOD"
    assert q.reason_for_visit is False
    assert q.episode_id is not None
    assert q.source.encounter_id == ENCOUNTER_ID
    assert q.source.section.endswith("13 Diagnoosi")
    assert q.author is not None and q.author.organization is not None


def test_risk(sample_result: PipelineResult) -> None:
    [risk] = sample_result.patients[0].clinical.risks
    assert risk.code is not None and risk.code.code == "J46"
    assert risk.text == "Kipulääkkeen aiheuttama astmakohtaus"
    assert risk.severity is not None and risk.severity.code == "1"
    assert risk.risk_type is not None and risk.risk_type.code == "L9"
    assert [a.code for a in risk.agents] == ["M01AE03"]
    assert risk.note == "Ei saa käyttää tulehduskipulääkkettä"
    # The risk entry has its own author (the person who observed the risk).
    assert risk.author is not None and risk.author.function is not None
    assert risk.author.function.code == "RIS"


def test_immunization(sample_result: PipelineResult) -> None:
    [imm] = sample_result.patients[0].clinical.immunizations
    assert imm.vaccine is not None and imm.vaccine.code == "J07AM51"
    assert imm.product is not None and (imm.product.code, imm.product.display) == (
        "041332",
        "DITEBOOSTER",
    )
    assert imm.lot_number == "12345"
    assert imm.route is not None and imm.route.code == "ID"
    assert imm.site is not None and imm.site.code == "VO"
    assert imm.dose == Quantity("1.5", "ml")
    assert imm.dose_number == 1
    assert [d.code for d in imm.target_diseases] == ["2", "7"]
    assert imm.status == "completed"


def test_lab_result_text_value(sample_result: PipelineResult) -> None:
    [lab] = [r for r in sample_result.patients[0].clinical.lab_results if r.code.code == "6466"]
    assert not lab.source.from_summary
    assert lab.value == "negat"
    assert lab.order_id is None


def test_lab_order_and_results(results_result: PipelineResult) -> None:
    clinical = results_result.patients[0].clinical
    [lab_order] = [o for o in clinical.orders if o.category == "laboratory"]
    assert lab_order.order_id == Identifier("1.2.246.10.1234567.14.2022.123.22.2")
    assert lab_order.note == "Oireeton potilas"
    assert lab_order.repeat_count == 10
    assert lab_order.repeat_period is not None
    assert (lab_order.repeat_period.start, lab_order.repeat_period.end) == (
        "2024-12-18",
        "2025-12-31",
    )
    assert [t.code.code for t in lab_order.tests][:3] == ["4591", "4600", "2516"]
    assert lab_order.tests[0].specimen is not None

    by_code = {}
    for r in clinical.lab_results:
        by_code.setdefault(r.code.code, r)
    assert len(clinical.lab_results) == 10
    crea = by_code["4600"]
    assert crea.value == Quantity("112", "umol/l")
    assert crea.status is not None and crea.status.code == "F"
    assert crea.interpretation is not None and crea.interpretation.code == "H"
    assert crea.specimen is not None and crea.specimen.code == "B"
    assert crea.order_id == lab_order.order_id
    assert [c.code for c in crea.local_codes] == ["46000"]
    assert crea.reference_ranges[0].low == Quantity("60", "umol/l")
    assert crea.issued == "2024-12-18T12:56:15+02:00"

    ekg = by_code["1270"]
    assert ekg.value == "tulos tekstinä tähän"
    assert ekg.procedure_code is not None and ekg.procedure_code.code == "FP1B5"

    fractions = by_code["2522"]
    assert fractions.value is None
    assert fractions.statement is not None
    assert fractions.statement_status is not None and fractions.statement_status.code == "2"


def test_imaging(results_result: PipelineResult) -> None:
    clinical = results_result.patients[0].clinical
    [img_order] = [o for o in clinical.orders if o.category == "imaging"]
    assert img_order.order_id == Identifier("1.2.246.10.1234567.14.2022.123.1.1")
    assert [t.code.code for t in img_order.tests] == ["GD1QA", "GD1LA", "EB1BA"]
    assert [c.code for c in img_order.tests[0].reason_codes] == ["I26.9"]

    results = clinical.imaging_results
    assert len(results) == 7
    statements = [r for r in results if r.has_statement]
    assert len(statements) == 2
    study = next(r for r in results if not r.has_statement)
    assert study.accession is not None and study.study_uid is not None
    assert study.radiation_dose == Quantity("0.1", "mGy.cm2")
    assert study.order_id == img_order.order_id
    assert {q.code for q in study.qualifiers} >= {"ZXA00"}


def test_vital_signs(results_result: PipelineResult) -> None:
    vitals = {v.code.code: v for v in results_result.patients[0].clinical.vital_signs}
    weight, pef = vitals["3141-9"], vitals["33452-4"]
    assert weight.value == Quantity("88.0", "kg")
    assert weight.alternative_values == [Quantity("194.0", "[lb_ap]")]
    assert weight.method is not None and weight.method.code == "2"
    assert pef.value == Quantity("600.0", "l/min")
    assert pef.reference_ranges[0].low == Quantity("540", "l/min")
    assert pef.abnormality is not None and pef.abnormality.code == "2"
    assert pef.notes == ["Lisätiedot tähän"]


def test_care_plan(careplan_result: PipelineResult) -> None:
    [plan] = careplan_result.patients[0].clinical.care_plans
    assert plan.needs and plan.needs[0].startswith("Sokeritasapaino")
    assert [r.code for r in plan.reasons] == ["E11.9"]
    assert len(plan.goals) == 1 and len(plan.functional_goals) == 1
    assert [(t.code.code, t.range) for t in plan.targets] == [
        ("1462", Range(Quantity("1", "mmol/l"), Quantity("10", "mmol/l"))),
        ("29463-7", Range(Quantity("1", "kg"), Quantity("150", "kg"))),
    ]
    assert plan.targets[0].note == "koholla"
    assert [m.role.code for m in plan.care_team] == ["302", "302", "302", "501"]
    assert [s.code.code for s in plan.planned_services] == ["SPAT1223", "SPAT1115"]
    service = plan.planned_services[1]
    assert service.start == "2024-12-23"
    assert service.status is not None and service.status.display == "Varattu"
    assert "B -Glukoosi 1-7 mmol/l" in service.conditions
    assert plan.medication_list is not None and plan.medication_list.startswith("Lääkityslista")
    assert plan.diagnosis_list is not None


def test_narratives(sample_result: PipelineResult) -> None:
    narratives = sample_result.patients[0].clinical.narratives
    assert narratives
    assert all(n.xhtml.startswith('<div xmlns="http://www.w3.org/1999/xhtml">') for n in narratives)
    # Kooste narratives are not used (they duplicate the originals).
    assert all(not n.source.from_summary for n in narratives)
    diagnosis = [n for n in narratives if n.source.section.endswith("13 Diagnoosi")]
    assert diagnosis and "Q32.11" in diagnosis[0].xhtml
