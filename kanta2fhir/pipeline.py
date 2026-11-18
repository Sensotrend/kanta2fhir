"""The conversion pipeline: read → parse → patient records → extract → consolidate."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kanta2fhir.consolidate import ConsolidationStats, consolidate
from kanta2fhir.extract import DocumentExtraction, extract_document
from kanta2fhir.model import ClinicalData, Issue
from kanta2fhir.reader import ReadResult, read_ndjson
from kanta2fhir.record import ParsedDocument, PatientRecord, build_records, parse_documents


@dataclass(slots=True)
class PatientResult:
    record: PatientRecord
    extractions: list[DocumentExtraction]
    clinical: ClinicalData
    stats: ConsolidationStats


@dataclass(slots=True)
class PipelineResult:
    read: ReadResult
    parsed: list[ParsedDocument]
    patients: list[PatientResult] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)  # not tied to one patient

    @property
    def all_issues(self) -> list[Issue]:
        return [
            *self.read.issues,
            *self.issues,
            *(i for p in self.patients for i in p.record.issues),
        ]


def run(path: Path) -> PipelineResult:
    read = read_ndjson(path)
    issues: list[Issue] = []
    parsed = parse_documents(read.documents, issues)
    result = PipelineResult(read=read, parsed=parsed, issues=issues)
    for record in build_records(parsed, issues):
        extractions = [extract_document(doc, record.issues) for doc in record.documents]
        clinical, stats = consolidate(extractions)
        result.patients.append(PatientResult(record, extractions, clinical, stats))
    return result
