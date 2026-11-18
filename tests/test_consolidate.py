import dataclasses

from kanta2fhir.consolidate import consolidate
from kanta2fhir.extract import Outcome, extract_document
from kanta2fhir.model import DocumentKind
from kanta2fhir.pipeline import PipelineResult
from kanta2fhir.record import ParsedDocument

from .conftest import LAB_LINE, SUMMARY_LINE, by_line


def test_summary_items_dropped_when_origin_present(sample_result: PipelineResult) -> None:
    patient = sample_result.patients[0]
    stats = patient.stats
    assert stats.from_summaries["lab_results"] == 11
    # The lab Kooste covers 11 results from several documents; only the COVID test's
    # original is in the sample, so the other 10 are used as fallback.
    assert stats.summary_dropped_origin_present["lab_results"] == 1
    assert stats.summary_used["lab_results"] == 10
    assert len(patient.clinical.lab_results) == 11
    from_summary = [r for r in patient.clinical.lab_results if r.source.from_summary]
    assert len(from_summary) == 10
    assert all(r.source.origin_document for r in from_summary)


def test_summary_items_not_used_when_original_exists(sample_parsed: list[ParsedDocument]) -> None:
    lab = by_line(sample_parsed, LAB_LINE)
    summary = by_line(sample_parsed, SUMMARY_LINE)
    data, _ = consolidate([extract_document(d, []) for d in (lab, summary)])
    covid = [r for r in data.lab_results if r.code.code == "6466"]
    assert len(covid) == 1 and not covid[0].source.from_summary


def test_duplicates_among_originals(sample_parsed: list[ParsedDocument]) -> None:
    lab = by_line(sample_parsed, LAB_LINE)
    copy = dataclasses.replace(
        lab, header=dataclasses.replace(lab.header, effective_time="2025-01-01T00:00:00+02:00")
    )
    data, stats = consolidate([extract_document(d, []) for d in (lab, copy)])
    assert len(data.lab_results) == 1
    assert stats.duplicates_dropped["lab_results"] == 1


def test_superseded_document_is_not_extracted(sample_parsed: list[ParsedDocument]) -> None:
    lab = by_line(sample_parsed, LAB_LINE)
    old = dataclasses.replace(lab, superseded_by="newer")
    x = extract_document(old, [])
    assert x.items == []
    assert set(o for _, o in x.outcomes) == {Outcome.SUPERSEDED}


def test_everything_in_sample_is_handled(sample_result: PipelineResult) -> None:
    outcomes = {o for p in sample_result.patients for x in p.extractions for _, o in x.outcomes}
    assert outcomes <= {Outcome.MAPPED, Outcome.CONTEXT}
    kinds = {x.document.kind for x in sample_result.patients[0].extractions}
    assert DocumentKind.SUMMARY in kinds
