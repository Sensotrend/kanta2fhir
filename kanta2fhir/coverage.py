"""Coverage report: what the export contains, and how much of it is mapped.

The report must never contain personal data: no names, no identity codes, no free text from
the documents. Patients are identified by their pseudonym, and documents by their CDA
document id (an OID).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from kanta2fhir import __version__, hetu
from kanta2fhir.cda.sections import iter_entries, iter_sections
from kanta2fhir.model import DocumentKind, Issue
from kanta2fhir.reader import ReadResult
from kanta2fhir.record import ParsedDocument, PatientRecord

# Mapping status per entry key. Milestone 2 fills this in as extractors are added.
NOT_MAPPED = "not-mapped"


def build_report(
    input_name: str,
    read: ReadResult,
    parsed: list[ParsedDocument],
    records: list[PatientRecord],
    issues: list[Issue],
) -> dict[str, Any]:
    all_issues = [*read.issues, *issues, *(i for r in records for i in r.issues)]
    documents = [_document_entry(d) for d in parsed]

    entry_types: dict[str, dict[str, Any]] = {}
    for doc in parsed:
        for entry in iter_entries(doc.root):
            info = entry_types.setdefault(
                entry.key,
                {
                    "element": entry.kind,
                    "display": entry.code.display if entry.code else None,
                    "count": 0,
                    "count_current_originals": 0,
                    "documents": 0,
                    "status": NOT_MAPPED,
                },
            )
            info["count"] += 1
            if doc.is_current and doc.kind != DocumentKind.SUMMARY:
                info["count_current_originals"] += 1
        for key in {e.key for e in iter_entries(doc.root)}:
            entry_types[key]["documents"] += 1

    return {
        "generator": {"name": "kanta2fhir", "version": __version__},
        "input": {
            "file": hetu.redact(input_name),
            "lines": read.lines,
            "documents_read": len(read.documents),
            "documents_parsed": len(parsed),
        },
        "patients": [_patient_entry(r) for r in records],
        "summary": {
            "documents_by_kind": dict(Counter(d.kind.value for d in parsed)),
            "current_documents": sum(1 for d in parsed if d.is_current),
            "templates": dict(
                Counter(d.header.template_ids[-1] for d in parsed if d.header.template_ids)
            ),
            "entry_types": dict(sorted(entry_types.items(), key=lambda kv: -kv[1]["count"])),
            "issues_by_severity": dict(Counter(i.severity.value for i in all_issues)),
        },
        "issues": [_issue_entry(i) for i in all_issues],
        "documents": documents,
    }


def _patient_entry(record: PatientRecord) -> dict[str, Any]:
    linked = sum(len(e.documents) for e in record.encounters.values())
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
    }


def _document_entry(doc: ParsedDocument) -> dict[str, Any]:
    entries = Counter(e.key for e in iter_entries(doc.root))
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
        "mapped": 0,
        "not_mapped": sum(entries.values()),
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
    total = sum(t["count"] for t in s["entry_types"].values())
    lines.append(f"Entries: {total} in {len(s['entry_types'])} types (0 mapped so far)")
    for key, t in list(s["entry_types"].items())[:10]:
        lines.append(f"  {t['count']:5}  {key}  {t['display'] or ''}".rstrip())
    issues = s["issues_by_severity"]
    lines.append("Issues: " + (", ".join(f"{k} {v}" for k, v in sorted(issues.items())) or "none"))
    return "\n".join(lines)
