"""Assemble parsed documents into patient records: patient, service events, document versions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from kanta2fhir import hetu as hetu_
from kanta2fhir.cda.header import CdaHeader, parse_header
from kanta2fhir.cda.util import Element, NotCdaError, parse_cda
from kanta2fhir.model import (
    DocumentKind,
    Encounter,
    HumanName,
    Identifier,
    Issue,
    Patient,
    Severity,
)
from kanta2fhir.reader import SourceDocument

SUMMARY_TEMPLATE = "1.2.246.777.11.2018.12"  # Kooste
XML_CONTENT_TYPES = {"text/xml", "application/xml", "application/hl7-v3+xml"}

# DocumentReference.type codes (https://hrp.kanta.fi/fihrp-cs-documentreferencetype)
_KIND_BY_DOCREF_TYPE = {
    "1": DocumentKind.SERVICE_EVENT,
    "2": DocumentKind.RECORD_ENTRY,
    "3": DocumentKind.SUMMARY,
}
# hl7fi:localHeader/documentType codes (1.2.246.537.5.5001.2011)
_KIND_BY_CDA_DOCUMENT_TYPE = {
    "1": DocumentKind.RECORD_ENTRY,  # Kertomusteksti
    "4": DocumentKind.SERVICE_EVENT,  # Palvelutapahtuma-asiakirja
}

# Gender codes (1.2.246.537.5.1.1997) mapped to what the HETU says
_GENDER_TO_SEX = {"1": "male", "2": "female"}


@dataclass(slots=True)
class ParsedDocument:
    source: SourceDocument
    header: CdaHeader
    root: Element = field(repr=False)
    kind: DocumentKind
    superseded_by: str | None = None

    @property
    def id(self) -> str:
        if self.header.document_id is not None:
            return self.header.document_id.key
        return self.source.identifier or f"line-{self.source.line}"

    @property
    def is_current(self) -> bool:
        return self.superseded_by is None


@dataclass(slots=True)
class PatientRecord:
    patient: Patient
    documents: list[ParsedDocument]
    encounters: dict[str, Encounter]  # by encounter identifier key
    issues: list[Issue] = field(default_factory=list)

    def current_documents(self, kind: DocumentKind | None = None) -> list[ParsedDocument]:
        return [d for d in self.documents if d.is_current and (kind is None or d.kind == kind)]


def parse_documents(sources: Iterable[SourceDocument], issues: list[Issue]) -> list[ParsedDocument]:
    """Parse the CDA payload and header of every source document."""
    parsed: list[ParsedDocument] = []
    for src in sources:
        doc = _parse_one(src, issues)
        if doc is not None:
            parsed.append(doc)
    return parsed


def _parse_one(src: SourceDocument, issues: list[Issue]) -> ParsedDocument | None:
    if src.content_type and src.content_type not in XML_CONTENT_TYPES:
        issues.append(
            Issue(
                Severity.ERROR,
                "unsupported-content-type",
                f"Content type {src.content_type} is not supported",
                src.line,
                src.identifier,
            )
        )
        return None
    try:
        root = parse_cda(src.data)
    except NotCdaError as e:
        issues.append(Issue(Severity.ERROR, "not-cda", str(e), src.line, src.identifier))
        return None
    header = parse_header(root)
    kind = _classify(src, header, issues)
    return ParsedDocument(source=src, header=header, root=root, kind=kind)


def _classify(src: SourceDocument, header: CdaHeader, issues: list[Issue]) -> DocumentKind:
    def issue(code: str, message: str) -> None:
        issues.append(Issue(Severity.WARNING, code, message, src.line, src.identifier))

    by_docref = _KIND_BY_DOCREF_TYPE.get(src.type_code or "")
    if SUMMARY_TEMPLATE in header.template_ids:
        by_cda: DocumentKind | None = DocumentKind.SUMMARY
    else:
        doc_type = header.local.document_type
        by_cda = _KIND_BY_CDA_DOCUMENT_TYPE.get(doc_type.code) if doc_type else None
    if by_docref and by_cda and by_docref != by_cda:
        issue(
            "kind-mismatch",
            f"DocumentReference type says {by_docref}, CDA header says {by_cda}; using {by_docref}",
        )
    kind = by_docref or by_cda
    if kind is None:
        issue("unknown-document-kind", "Cannot tell what kind of document this is")
        return DocumentKind.UNKNOWN
    return kind


def build_records(parsed: Iterable[ParsedDocument], issues: list[Issue]) -> list[PatientRecord]:
    """Group documents by patient and build one record per patient."""
    by_patient: dict[str, list[ParsedDocument]] = defaultdict(list)
    for doc in parsed:
        if not doc.source.patient_hetu:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "no-patient-identifier",
                    "DocumentReference.subject has no personal identity code; document skipped",
                    doc.source.line,
                    doc.id,
                )
            )
            continue
        by_patient[doc.source.patient_hetu].append(doc)

    records = []
    for hetu, docs in by_patient.items():
        record_issues: list[Issue] = []
        _mark_superseded(docs, record_issues)
        patient = _consolidate_patient(hetu, docs, record_issues)
        encounters = _build_encounters(docs, record_issues)
        records.append(PatientRecord(patient, docs, encounters, record_issues))
    return records


def _mark_superseded(docs: list[ParsedDocument], issues: list[Issue]) -> None:
    """Only the latest version of a document counts (setId + versionNumber, relatedDocument)."""
    by_set: dict[str, list[ParsedDocument]] = defaultdict(list)
    for doc in docs:
        if doc.header.set_id is not None:
            by_set[doc.header.set_id.key].append(doc)
    for versions in by_set.values():
        if len(versions) < 2:
            continue
        versions.sort(key=lambda d: d.header.version or 0)
        latest = versions[-1]
        for old in versions[:-1]:
            old.superseded_by = latest.id

    by_id = {doc.id: doc for doc in docs}
    for doc in docs:
        for rel in doc.header.related_documents:
            if rel.type_code == "RPLC" and rel.identifier is not None:
                replaced = by_id.get(rel.identifier.key)
                if replaced is not None and replaced is not doc:
                    replaced.superseded_by = doc.id

    superseded = sum(1 for d in docs if not d.is_current)
    if superseded:
        issues.append(
            Issue(
                Severity.INFO,
                "superseded-versions",
                f"{superseded} older document versions ignored",
            )
        )


def instant(value: str | None) -> datetime:
    """Sort key for FHIR date/dateTime strings (missing values sort first)."""
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    if "T" not in value:
        parts = [*value.split("-"), "01", "01"][:3]
        return datetime(int(parts[0]), int(parts[1]), int(parts[2]), tzinfo=UTC)
    return datetime.fromisoformat(value)


def _consolidate_patient(hetu: str, docs: list[ParsedDocument], issues: list[Issue]) -> Patient:
    """Pick demographics from the most recent original document, and report disagreements."""
    pseudonym = hetu_.pseudonym(hetu)

    def issue(code: str, message: str, severity: Severity = Severity.WARNING) -> None:
        issues.append(Issue(severity, code, f"Patient {pseudonym}: {message}"))

    if not hetu_.is_valid(hetu):
        issue("invalid-hetu", "personal identity code is not valid (format or check character)")
    elif hetu_.is_test_hetu(hetu):
        issue("test-hetu", "personal identity code is in the test range (900-999)", Severity.INFO)

    # Originals before summaries, newest first.
    current = [d for d in docs if d.is_current]
    current.sort(key=lambda d: (d.kind != DocumentKind.SUMMARY, instant(d.header.effective_time)))
    current.reverse()
    demographics = [d.header.patient for d in current]

    names: list[HumanName] = [x.name for x in demographics if x.name is not None]
    genders = [x.gender for x in demographics if x.gender is not None]
    birth_dates = [x.birth_date for x in demographics if x.birth_date]

    name_variants = {(n.family, n.given, n.calling_name) for n in names}
    if len(name_variants) > 1:
        issue(
            "patient-name-variants",
            f"{len(name_variants)} different name variants across documents; "
            "using the most recent original document",
        )
    if len({g.code for g in genders}) > 1:
        issue("patient-gender-variants", "documents disagree on gender")
    if len(set(birth_dates)) > 1:
        issue("patient-birthdate-variants", "documents disagree on birth date")

    hetu_sex = hetu_.sex(hetu)
    # When documents disagree, prefer the most recent gender that agrees with the HETU.
    agreeing = [g for g in genders if _GENDER_TO_SEX.get(g.code) == hetu_sex]
    gender = agreeing[0] if agreeing else (genders[0] if genders else None)
    birth_date = birth_dates[0] if birth_dates else None
    hetu_birth = hetu_.birth_date(hetu)
    if hetu_birth:
        if birth_date and birth_date[:10] != hetu_birth:
            issue("birthdate-hetu-mismatch", "birth date in documents differs from the HETU")
        birth_date = birth_date or hetu_birth
    if gender and hetu_sex and _GENDER_TO_SEX.get(gender.code) not in (None, hetu_sex):
        issue("gender-hetu-mismatch", "gender in documents differs from the HETU")

    return Patient(
        hetu=hetu,
        pseudonym=pseudonym,
        name=names[0] if names else None,
        gender=gender,
        birth_date=birth_date,
    )


def _build_encounters(docs: list[ParsedDocument], issues: list[Issue]) -> dict[str, Encounter]:
    """Service events from Palvelutapahtuma documents, with record entries linked to them."""
    encounters: dict[str, Encounter] = {}

    for doc in docs:
        if not doc.is_current or doc.kind != DocumentKind.SERVICE_EVENT:
            continue
        enc = doc.header.encounter
        if enc is None or enc.identifier is None:
            issues.append(
                Issue(
                    Severity.WARNING,
                    "service-event-without-encounter",
                    "Service event document has no encompassingEncounter id",
                    doc.source.line,
                    doc.id,
                )
            )
            continue
        key = enc.identifier.key
        if key in encounters:
            issues.append(
                Issue(
                    Severity.WARNING,
                    "duplicate-service-event",
                    f"Several current service event documents for encounter {key}",
                    doc.source.line,
                    doc.id,
                )
            )
            continue
        encounters[key] = Encounter(
            identifier=enc.identifier,
            period=enc.period,
            encounter_type=doc.header.local.encounter_type,
            service_provider=enc.responsible_organization,
            participants=list(enc.participant_organizations),
            service_event_document=doc.id,
        )

    for doc in docs:
        if not doc.is_current or doc.kind != DocumentKind.RECORD_ENTRY:
            continue
        key = _encounter_key(doc, issues)
        if key is None:
            continue
        if key not in encounters:
            enc = doc.header.encounter
            encounters[key] = Encounter(
                identifier=enc.identifier if enc and enc.identifier else Identifier(system=key),
                period=enc.period if enc else None,
                service_provider=enc.responsible_organization if enc else None,
            )
            issues.append(
                Issue(
                    Severity.INFO,
                    "encounter-without-service-event",
                    f"No service event document for encounter {key}",
                    doc.source.line,
                    doc.id,
                )
            )
        encounters[key].documents.append(doc.id)
    return encounters


def _encounter_key(doc: ParsedDocument, issues: list[Issue]) -> str | None:
    """The encounter a record entry belongs to: from the CDA header, else the DocumentReference."""
    enc = doc.header.encounter
    from_cda = enc.identifier.key if enc and enc.identifier else None
    related = doc.source.related_ids
    if from_cda and related and from_cda not in related:
        issues.append(
            Issue(
                Severity.WARNING,
                "encounter-link-mismatch",
                "CDA encompassingEncounter id is not among DocumentReference.context.related",
                doc.source.line,
                doc.id,
            )
        )
    return from_cda or (related[0] if related else None)
