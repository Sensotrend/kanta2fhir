import json
from pathlib import Path

import pytest

from kanta2fhir.cli import main

from .conftest import SAMPLE, TEST_HETU


def test_cli_writes_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(SAMPLE), "--out", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert report["input"]["documents_parsed"] == 6
    assert report["summary"]["documents_by_kind"] == {
        "service_event": 1,
        "record_entry": 4,
        "summary": 1,
    }
    [patient] = report["patients"]
    assert patient["encounters"]["total"] == 1
    assert patient["encounters"]["record_entries_linked"] == 4
    diag = report["summary"]["entry_types"]["observation 1.2.246.537.6.12.999.2003#2"]
    assert diag["count"] == 3
    assert diag["status"] == "not-mapped"

    out = capsys.readouterr().out
    assert "Skipping eps: not implemented yet" in out


def test_report_contains_no_personal_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main([str(SAMPLE), "--out", str(tmp_path)])
    text = (tmp_path / "report.json").read_text(encoding="utf-8") + capsys.readouterr().out
    for secret in (TEST_HETU, "Testinen", "Lekuri", "2001-10-05"):
        assert secret not in text


def test_report_redacts_hetu_in_file_name(tmp_path: Path) -> None:
    named = tmp_path / f"kanta_terveystiedot_{TEST_HETU}_123.ndjson"
    named.write_bytes(SAMPLE.read_bytes())
    main([str(named), "--out", str(tmp_path / "out")])
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["input"]["file"] == "kanta_terveystiedot_<hetu>_123.ndjson"


def test_cli_rejects_unknown_target(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main([str(SAMPLE), "--out", str(tmp_path), "--targets", "eps,xyz"])
