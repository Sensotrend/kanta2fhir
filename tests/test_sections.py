from collections import Counter

from kanta2fhir.cda.sections import iter_entries, iter_sections
from kanta2fhir.record import ParsedDocument

from .conftest import DIAGNOSIS_LINE, SERVICE_EVENT_LINE, SUMMARY_LINE, by_line


def test_diagnosis_document_sections_and_entries(sample_parsed: list[ParsedDocument]) -> None:
    root = by_line(sample_parsed, DIAGNOSIS_LINE).root
    paths = [" / ".join(s.label for s in path) for path, _ in iter_sections(root)]
    assert paths == [
        "98 Yleislääketiede",
        "98 Yleislääketiede / 16 Hoidon arviointi",
        "98 Yleislääketiede / 16 Hoidon arviointi / 13 Diagnoosi",
    ]
    entries = list(iter_entries(root))
    assert [e.key for e in entries] == ["observation 1.2.246.537.6.12.999.2003#2"] * 3
    assert entries[0].path_label.endswith("13 Diagnoosi")
    assert entries[0].entry_template_ids == ("1.2.246.777.11.2015.30",)


def test_service_event_has_no_entries(sample_parsed: list[ParsedDocument]) -> None:
    assert list(iter_entries(by_line(sample_parsed, SERVICE_EVENT_LINE).root)) == []


def test_summary_entries(sample_parsed: list[ParsedDocument]) -> None:
    kinds = Counter(e.kind for e in iter_entries(by_line(sample_parsed, SUMMARY_LINE).root))
    assert kinds == {"encounter": 12, "observation": 11, "organizer": 1}
