"""Coverage report: what the export contains, and how much of it is mapped.

The report must never contain personal data: no names, no identity codes, no free text from
the documents. Patients are identified by their pseudonym, and documents by their CDA
document id (an OID).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import fields
from typing import Any

from kanta2fhir import __version__, hetu
from kanta2fhir.cda.sections import iter_entries, iter_sections
from kanta2fhir.extract import DocumentExtraction, Outcome
from kanta2fhir.model import ClinicalData, Issue
from kanta2fhir.pipeline import PatientResult, PipelineResult


def build_report(input_name: str, result: PipelineResult) -> dict[str, Any]:
    extractions = [x for p in result.patients for x in p.extractions]
    all_issues = result.all_issues

    entry_types: dict[str, dict[str, Any]] = {}
    displays: dict[str, str | None] = {}
    doc_counts: Counter[str] = Counter()
    for x in extractions:
        for entry in iter_entries(x.document.root):
            displays.setdefault(entry.key, entry.code.display if entry.code else None)
        for key in {k for k, _ in x.outcomes}:
            doc_counts[key] += 1
        for (key, outcome), n in x.outcomes.items():
            info = entry_types.setdefault(
                key,
                {
                    "element": key.split(" ", 1)[0],
                    "display": None,
                    "count": 0,
                    "documents": 0,
                    "outcomes": {},
                },
            )
            info["count"] += n
            info["outcomes"][outcome.value] = info["outcomes"].get(outcome.value, 0) + n
    for key, info in entry_types.items():
        info["display"] = displays.get(key)
        info["documents"] = doc_counts[key]
        info["status"] = _status(info["outcomes"])

    outcome_totals: Counter[str] = Counter()
    for info in entry_types.values():
        outcome_totals.update(info["outcomes"])

    return {
        "generator": {"name": "kanta2fhir", "version": __version__},
        "input": {
            "file": hetu.redact(input_name),
            "lines": result.read.lines,
            "documents_read": len(result.read.documents),
            "documents_parsed": len(result.parsed),
        },
        "patients": [_patient_entry(p) for p in result.patients],
        "summary": {
            "documents_by_kind": dict(Counter(d.kind.value for d in result.parsed)),
            "current_documents": sum(1 for d in result.parsed if d.is_current),
            "templates": dict(
                Counter(d.header.template_ids[-1] for d in result.parsed if d.header.template_ids)
            ),
            "entries_by_outcome": dict(outcome_totals),
            "entry_types": dict(sorted(entry_types.items(), key=lambda kv: -kv[1]["count"])),
            "issues_by_severity": dict(Counter(i.severity.value for i in all_issues)),
        },
        "issues": [_issue_entry(i) for i in all_issues],
        "documents": [_document_entry(x) for x in extractions],
    }


def _status(outcomes: dict[str, int]) -> str:
    """One word per entry type: mapped, partial, context, not-mapped, failed, superseded."""
    keys = set(outcomes)
    if Outcome.MAPPED.value in keys and keys <= {Outcome.MAPPED.value, Outcome.SUPERSEDED.value}:
        return "mapped"
    if len(keys) == 1:
        return next(iter(keys))
    return "partial"


def _clinical_counts(data: ClinicalData) -> dict[str, int]:
    return {f.name: len(getattr(data, f.name)) for f in fields(data)}


def _patient_entry(p: PatientResult) -> dict[str, Any]:
    record = p.record
    linked = sum(len(e.documents) for e in record.encounters.values())
    stats = p.stats
    names = sorted(set(stats.from_originals) | set(stats.from_summaries))
    consolidation = {
        name: {
            "from_originals": stats.from_originals[name],
            "from_summaries": stats.from_summaries[name],
            "duplicates_dropped": stats.duplicates_dropped[name],
            "summary_dropped_origin_present": stats.summary_dropped_origin_present[name],
            "summary_used": stats.summary_used[name],
            "result": len(getattr(p.clinical, name)),
        }
        for name in names
    }
    return {
        "pseudonym": record.patient.pseudonym,
        "documents": len(record.documents),
        "current_documents": len(record.current_documents()),
        "has_name": record.patient.name is not None,
        "gender": record.patient.gender.code if record.patient.gender else None,
        "has_birth_date": record.patient.birth_date is not None,
        "encounters": {
            "total": len(record.encounters),
            "with_service_event_document": sum(
                1 for e in record.encounters.values() if e.service_event_document
            ),
            "by_type": dict(
                Counter(
                    f"{e.encounter_type.code} {e.encounter_type.display}"
                    if e.encounter_type
                    else "unknown"
                    for e in record.encounters.values()
                )
            ),
            "record_entries_linked": linked,
        },
        "clinical": _clinical_counts(p.clinical),
        "consolidation": consolidation,
    }


def _document_entry(x: DocumentExtraction) -> dict[str, Any]:
    doc = x.document
    entries: Counter[str] = Counter()
    by_outcome: dict[str, int] = defaultdict(int)
    for (key, outcome), n in x.outcomes.items():
        entries[key] += n
        by_outcome[outcome.value] += n
    encounter = doc.header.encounter
    return {
        "line": doc.source.line,
        "id": doc.id,
        "kind": doc.kind.value,
        "current": doc.is_current,
        "title": doc.header.title,
        "effective_time": doc.header.effective_time,
        "template": doc.header.template_ids[-1] if doc.header.template_ids else None,
        "views": list(doc.source.category_codes),
        "encounter": encounter.identifier.key if encounter and encounter.identifier else None,
        "sections": sorted(
            {" / ".join(s.label for s in path) for path, _ in iter_sections(doc.root)}
        ),
        "entries": dict(entries),
        "outcomes": dict(by_outcome),
        "items": dict(Counter(type(i).__name__ for i in x.items)),
        "narrative_sections": len(x.narratives),
    }


def _issue_entry(issue: Issue) -> dict[str, Any]:
    out: dict[str, Any] = {
        "severity": issue.severity.value,
        "code": issue.code,
        "message": issue.message,
    }
    if issue.line is not None:
        out["line"] = issue.line
    if issue.document_id is not None:
        out["document"] = issue.document_id
    return out


def format_summary(report: dict[str, Any]) -> str:
    """A short human-readable summary for the terminal."""
    s = report["summary"]
    lines = [
        f"Input: {report['input']['file']} ({report['input']['lines']} lines, "
        f"{report['input']['documents_parsed']} documents parsed)",
        "Documents by kind: "
        + ", ".join(f"{k} {v}" for k, v in sorted(s["documents_by_kind"].items())),
    ]
    for p in report["patients"]:
        enc = p["encounters"]
        lines.append(
            f"Patient {p['pseudonym']}: {p['current_documents']} current documents, "
            f"{enc['total']} encounters ({enc['with_service_event_document']} with a service "
            f"event document), {enc['record_entries_linked']} record entries linked"
        )
        clinical = ", ".join(f"{k} {v}" for k, v in p["clinical"].items() if v)
        lines.append(f"  Clinical data after consolidation: {clinical or 'none'}")
    total = sum(t["count"] for t in s["entry_types"].values())
    outcomes = ", ".join(f"{k} {v}" for k, v in sorted(s["entries_by_outcome"].items()))
    lines.append(f"Entries: {total} in {len(s['entry_types'])} types ({outcomes})")
    unmapped = [
        (k, t) for k, t in s["entry_types"].items() if t["status"] not in ("mapped", "context")
    ]
    for key, t in unmapped[:10]:
        lines.append(f"  {t['status']:10} {t['count']:5}  {key}  {t['display'] or ''}".rstrip())
    issues = s["issues_by_severity"]
    lines.append("Issues: " + (", ".join(f"{k} {v}" for k, v in sorted(issues.items())) or "none"))
    return "\n".join(lines)
