from kanta2fhir.model import DocumentKind
from kanta2fhir.record import ParsedDocument

from .conftest import DIAGNOSIS_LINE, ENCOUNTER_ID, SERVICE_EVENT_LINE, SUMMARY_LINE, by_line


def test_service_event_header(sample_parsed: list[ParsedDocument]) -> None:
    doc = by_line(sample_parsed, SERVICE_EVENT_LINE)
    h = doc.header
    assert doc.kind == DocumentKind.SERVICE_EVENT
    assert h.title == "Palvelutapahtuma-asiakirja"
    assert h.version == 1
    assert h.language == "fi"
    assert h.effective_time == "2024-12-18T12:55:22+02:00"
    assert h.local.document_type is not None and h.local.document_type.code == "4"
    assert h.local.encounter_type is not None and h.local.encounter_type.code == "2"

    enc = h.encounter
    assert enc is not None and enc.identifier is not None
    assert enc.identifier.key == ENCOUNTER_ID
    assert enc.period is not None
    assert enc.period.start == "2024-12-18T09:00:00+02:00"
    assert enc.period.end == "2024-12-19T10:00:00+02:00"
    assert enc.responsible_organization is not None
    assert enc.responsible_organization.name == "Terveyskeskus testausta varten 3"
    assert len(enc.participant_organizations) == 1


def test_patient_demographics_are_read_and_hetu_is_masked(
    sample_parsed: list[ParsedDocument],
) -> None:
    p = by_line(sample_parsed, SERVICE_EVENT_LINE).header.patient
    assert p.birth_date == "2001-10-05"
    assert p.gender is not None and p.gender.code == "1"
    assert p.name is not None and p.name.family == ("Testinen",)


def test_record_entry_header(sample_parsed: list[ParsedDocument]) -> None:
    doc = by_line(sample_parsed, DIAGNOSIS_LINE)
    h = doc.header
    assert doc.kind == DocumentKind.RECORD_ENTRY
    assert h.title == "Yleislääketiede"
    assert h.template_ids[-1] == "1.2.246.777.11.2015.30"
    assert h.encounter is not None and h.encounter.identifier is not None
    assert h.encounter.identifier.key == ENCOUNTER_ID
    assert h.encounter.period is None  # nullFlavor in record entries
    assert [c.code for c in h.local.contents_codes] == ["98"]
    author = h.authors[0]
    assert author.time is None  # nullFlavor
    assert author.person is not None and author.person.identifier is not None
    assert author.person.identifier.masked


def test_summary_header(sample_parsed: list[ParsedDocument]) -> None:
    doc = by_line(sample_parsed, SUMMARY_LINE)
    assert doc.kind == DocumentKind.SUMMARY
    assert doc.header.code is None
    assert doc.header.encounter is None
    assert doc.header.custodian is None
