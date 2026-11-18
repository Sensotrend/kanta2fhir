"""Read Kanta ndjson exports: one FHIR DocumentReference per line.

Each line is either ``{"resource": {DocumentReference}}`` (the Kanta export format) or a bare
DocumentReference. The embedded document is in ``content[0].attachment.data`` (base64).
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kanta2fhir.model import Issue, Severity

HETU_SYSTEM = "urn:oid:1.2.246.21"


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """One DocumentReference with its decoded attachment."""

    line: int  # 1-based line number in the ndjson file
    identifier: str | None  # DocumentReference.identifier[0].value (the CDA document OID)
    type_code: str | None  # 1 Palvelutapahtuma, 2 Hoitoasiakirja, 3 Kooste
    type_display: str | None
    category_codes: tuple[str, ...]  # views (näkymät), 1.2.246.537.6.12.2002
    date: str | None
    patient_hetu: str | None = field(repr=False)
    related_ids: tuple[str, ...]  # context.related identifiers (service event ids)
    period_start: str | None
    period_end: str | None
    content_type: str | None
    language: str | None
    data: bytes = field(repr=False)


@dataclass(slots=True)
class ReadResult:
    documents: list[SourceDocument] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    lines: int = 0


def read_ndjson(path: Path) -> ReadResult:
    """Read all documents from an ndjson file. Problems are collected as issues, not raised."""
    result = ReadResult()
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            result.lines += 1
            doc = _parse_line(line, line_no, result.issues)
            if doc is not None:
                result.documents.append(doc)
    return result


def _parse_line(line: str, line_no: int, issues: list[Issue]) -> SourceDocument | None:
    def issue(code: str, message: str, severity: Severity = Severity.ERROR) -> None:
        issues.append(Issue(severity, code, message, line=line_no))

    try:
        obj = json.loads(line)
    except json.JSONDecodeError as e:
        issue("invalid-json", f"Line is not valid JSON: {e.msg}")
        return None

    resource = obj.get("resource", obj) if isinstance(obj, dict) else None
    if not isinstance(resource, dict) or resource.get("resourceType") != "DocumentReference":
        issue("not-documentreference", "Line does not contain a DocumentReference")
        return None

    contents = resource.get("content") or []
    if not contents:
        issue("no-content", "DocumentReference has no content")
        return None
    if len(contents) > 1:
        issue(
            "multiple-content",
            f"DocumentReference has {len(contents)} attachments; only the first is used",
            Severity.WARNING,
        )
    attachment = contents[0].get("attachment") or {}
    if "data" not in attachment:
        issue("no-attachment-data", "Attachment has no inline data (url-only is not supported)")
        return None
    try:
        data = base64.b64decode(attachment["data"], validate=True)
    except (binascii.Error, ValueError):
        issue("invalid-base64", "Attachment data is not valid base64")
        return None

    type_coding = _first_coding(resource.get("type"))
    context = resource.get("context") or {}
    period = context.get("period") or {}

    return SourceDocument(
        line=line_no,
        identifier=_first_identifier_value(resource.get("identifier")),
        type_code=type_coding.get("code"),
        type_display=type_coding.get("display"),
        category_codes=tuple(
            c["code"]
            for cat in resource.get("category") or []
            for c in cat.get("coding") or []
            if "code" in c
        ),
        date=resource.get("date"),
        patient_hetu=_subject_hetu(resource.get("subject")),
        related_ids=tuple(
            v
            for rel in context.get("related") or []
            if (v := (rel.get("identifier") or {}).get("value"))
        ),
        period_start=period.get("start"),
        period_end=period.get("end"),
        content_type=attachment.get("contentType"),
        language=attachment.get("language"),
        data=data,
    )


def _first_coding(concept: Any) -> dict[str, Any]:
    codings = (concept or {}).get("coding") or []
    return codings[0] if codings else {}


def _first_identifier_value(identifiers: Any) -> str | None:
    for ident in identifiers or []:
        if value := ident.get("value"):
            return str(value)
    return None


def _subject_hetu(subject: Any) -> str | None:
    ident = (subject or {}).get("identifier") or {}
    if ident.get("system") == HETU_SYSTEM:
        return ident.get("value")
    return None
