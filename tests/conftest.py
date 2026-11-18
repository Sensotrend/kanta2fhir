from __future__ import annotations

from pathlib import Path

import pytest

from kanta2fhir.model import Issue
from kanta2fhir.pipeline import PipelineResult, run
from kanta2fhir.reader import ReadResult, read_ndjson
from kanta2fhir.record import ParsedDocument, parse_documents

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "real" / "sample.ndjson"

# sample.ndjson: lines from the Kanta test-environment export, in this order
SERVICE_EVENT_LINE = 1  # Palvelutapahtuma-asiakirja
LAB_LINE = 2  # Laboratorio (COVID-19 PCR)
DIAGNOSIS_LINE = 3  # Yleislääketiede, 3 diagnoses
RISK_LINE = 4  # Riskitiedot
IMMUNIZATION_LINE = 5  # Rokotukset
SUMMARY_LINE = 6  # Laboratoriotutkimuskooste

TEST_HETU = "051001A937S"
ENCOUNTER_ID = "1.2.246.10.1.20241218125522.93.2009.1132917519211170.2"


@pytest.fixture(scope="session")
def sample_read() -> ReadResult:
    return read_ndjson(SAMPLE)


@pytest.fixture
def sample_parsed(sample_read: ReadResult) -> list[ParsedDocument]:
    issues: list[Issue] = []
    parsed = parse_documents(sample_read.documents, issues)
    assert issues == []
    return parsed


def by_line(parsed: list[ParsedDocument], line: int) -> ParsedDocument:
    return next(d for d in parsed if d.source.line == line)


CAREPLAN = FIXTURES / "real" / "careplan.ndjson"  # Terveys- ja hoitosuunnitelma
RESULTS = FIXTURES / "real" / "results.ndjson"  # Laboratorio, Radiologia, Sisätaudit (vitals)


@pytest.fixture(scope="session")
def sample_result() -> PipelineResult:
    return run(SAMPLE)


@pytest.fixture(scope="session")
def careplan_result() -> PipelineResult:
    return run(CAREPLAN)


@pytest.fixture(scope="session")
def results_result() -> PipelineResult:
    return run(RESULTS)
