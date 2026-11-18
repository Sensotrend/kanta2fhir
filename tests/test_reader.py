import base64
import json
from pathlib import Path

from kanta2fhir.reader import ReadResult, read_ndjson

from .conftest import ENCOUNTER_ID, SERVICE_EVENT_LINE, SUMMARY_LINE, TEST_HETU


def test_reads_sample(sample_read: ReadResult) -> None:
    assert sample_read.lines == 6
    assert len(sample_read.documents) == 6
    assert sample_read.issues == []

    se = sample_read.documents[SERVICE_EVENT_LINE - 1]
    assert se.type_code == "1"
    assert se.patient_hetu == TEST_HETU
    assert se.related_ids == (ENCOUNTER_ID,)
    assert se.period_start == "2024-12-18T09:00:00+02:00"
    assert se.content_type == "text/xml"
    assert se.data.startswith(b"<?xml")

    summary = sample_read.documents[SUMMARY_LINE - 1]
    assert summary.type_code == "3"
    assert summary.related_ids == ()


def test_hetu_not_in_repr(sample_read: ReadResult) -> None:
    assert TEST_HETU not in repr(sample_read.documents[0])


def _docref(**overrides: object) -> dict:
    resource = {
        "resourceType": "DocumentReference",
        "identifier": [{"value": "1.2.3"}],
        "subject": {"identifier": {"system": "urn:oid:1.2.246.21", "value": "x"}},
        "content": [
            {"attachment": {"contentType": "text/xml", "data": base64.b64encode(b"<a/>").decode()}}
        ],
    }
    resource.update(overrides)
    return resource


def test_problem_lines_become_issues(tmp_path: Path) -> None:
    lines = [
        json.dumps({"resource": _docref()}),  # ok, wrapped
        json.dumps(_docref()),  # ok, bare resource
        "",  # blank: ignored
        "{not json",
        json.dumps({"resource": {"resourceType": "Patient"}}),
        json.dumps({"resource": _docref(content=[])}),
        json.dumps({"resource": _docref(content=[{"attachment": {"data": "!!"}}])}),
        json.dumps({"resource": _docref(content=[{"attachment": {"url": "http://x"}}])}),
    ]
    path = tmp_path / "x.ndjson"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = read_ndjson(path)
    assert len(result.documents) == 2
    assert result.lines == 7
    assert [(i.line, i.code) for i in result.issues] == [
        (4, "invalid-json"),
        (5, "not-documentreference"),
        (6, "no-content"),
        (7, "invalid-base64"),
        (8, "no-attachment-data"),
    ]
