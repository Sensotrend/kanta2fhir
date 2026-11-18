import dataclasses

from kanta2fhir import hetu
from kanta2fhir.model import Coding, DocumentKind, Issue
from kanta2fhir.reader import ReadResult
from kanta2fhir.record import ParsedDocument, build_records, parse_documents

from .conftest import ENCOUNTER_ID, LAB_LINE, SERVICE_EVENT_LINE, TEST_HETU, by_line


def test_one_patient_one_encounter(sample_parsed: list[ParsedDocument]) -> None:
    issues: list[Issue] = []
    [record] = build_records(sample_parsed, issues)
    assert issues == []

    p = record.patient
    assert p.hetu == TEST_HETU
    assert p.pseudonym == hetu.pseudonym(TEST_HETU)
    assert p.birth_date == "2001-10-05"
    assert p.gender is not None and p.gender.code == "1"
    assert TEST_HETU not in repr(p)

    assert list(record.encounters) == [ENCOUNTER_ID]
    enc = record.encounters[ENCOUNTER_ID]
    assert enc.service_event_document == by_line(sample_parsed, SERVICE_EVENT_LINE).id
    assert len(enc.documents) == 4  # lab, diagnoses, risk, immunisation; not the summary
    assert enc.encounter_type is not None and enc.encounter_type.code == "2"

    # The Kanta test data really does have inconsistent names and genders across documents.
    assert {i.code for i in record.issues} == {
        "test-hetu",
        "patient-name-variants",
        "patient-gender-variants",
    }


def test_record_entry_without_service_event(sample_parsed: list[ParsedDocument]) -> None:
    without_se = [d for d in sample_parsed if d.kind != DocumentKind.SERVICE_EVENT]
    [record] = build_records(without_se, [])
    enc = record.encounters[ENCOUNTER_ID]
    assert enc.service_event_document is None
    assert len(enc.documents) == 4
    assert "encounter-without-service-event" in {i.code for i in record.issues}


def test_older_versions_are_superseded(sample_parsed: list[ParsedDocument]) -> None:
    lab = by_line(sample_parsed, LAB_LINE)
    assert lab.header.set_id is not None
    newer_header = dataclasses.replace(
        lab.header,
        document_id=dataclasses.replace(lab.header.set_id, system=lab.header.set_id.system + ".9"),
        version=2,
    )
    newer = dataclasses.replace(lab, header=newer_header)
    [record] = build_records([*sample_parsed, newer], [])
    assert lab.superseded_by == newer.id
    assert newer.is_current
    assert "superseded-versions" in {i.code for i in record.issues}


def test_gender_disagreement_prefers_hetu(sample_parsed: list[ParsedDocument]) -> None:
    # Make the most recent original document say female.
    newest = max(
        (d for d in sample_parsed if d.kind != DocumentKind.SUMMARY),
        key=lambda d: d.header.effective_time or "",
    )
    female = dataclasses.replace(
        newest.header.patient, gender=Coding(code="2", system="1.2.246.537.5.1.1997")
    )
    newest.header = dataclasses.replace(newest.header, patient=female)
    [record] = build_records(sample_parsed, [])
    assert record.patient.gender is not None and record.patient.gender.code == "1"
    assert "patient-gender-variants" in {i.code for i in record.issues}


def test_document_without_hetu_is_skipped(sample_parsed: list[ParsedDocument]) -> None:
    doc = sample_parsed[0]
    no_hetu = dataclasses.replace(doc, source=dataclasses.replace(doc.source, patient_hetu=None))
    issues: list[Issue] = []
    records = build_records([no_hetu], issues)
    assert records == []
    assert [i.code for i in issues] == ["no-patient-identifier"]


def test_non_cda_payload(sample_read: ReadResult) -> None:
    src = dataclasses.replace(sample_read.documents[0], data=b"<html/>")
    pdf = dataclasses.replace(sample_read.documents[0], content_type="application/pdf")
    issues: list[Issue] = []
    assert parse_documents([src, pdf], issues) == []
    assert [i.code for i in issues] == ["not-cda", "unsupported-content-type"]
