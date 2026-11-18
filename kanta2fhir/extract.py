"""Extract clinical content from parsed documents: dispatch each entry to its extractor."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum

from kanta2fhir.cda.entries import careplan, clinical, results
from kanta2fhir.cda.entries.base import (
    KANTA,
    LAB_CODES,
    PROCEDURES,
    VITALS,
    EntryContext,
    summary_link,
)
from kanta2fhir.cda.narrative import to_xhtml
from kanta2fhir.cda.sections import EntryRef, iter_entries, iter_sections
from kanta2fhir.cda.util import find
from kanta2fhir.cda.values import DocContext
from kanta2fhir.model import (
    CarePlan,
    Condition,
    DocumentKind,
    ImagingResult,
    Immunization,
    Issue,
    LabResult,
    Order,
    Procedure,
    RiskItem,
    SectionNarrative,
    Severity,
    SourceRef,
    VitalSign,
)
from kanta2fhir.record import ParsedDocument

CAREPLAN_VIEW = "345"

Item = (
    Condition
    | RiskItem
    | Immunization
    | Procedure
    | Order
    | LabResult
    | VitalSign
    | ImagingResult
    | CarePlan
)


class Outcome(StrEnum):
    MAPPED = "mapped"  # extracted into the model
    CONTEXT = "context"  # used as context (Kooste encounter links)
    NOT_MAPPED = "not-mapped"  # no extractor for this kind of entry
    FAILED = "failed"  # extractor found nothing usable or raised an error
    SUPERSEDED = "superseded"  # document is an older version


@dataclass(slots=True)
class DocumentExtraction:
    document: ParsedDocument
    items: list[Item] = field(default_factory=list)
    narratives: list[SectionNarrative] = field(default_factory=list)
    outcomes: Counter[tuple[str, Outcome]] = field(default_factory=Counter)  # (entry key, outcome)


def classify(entry: EntryRef) -> str | None:
    """Which extractor handles this entry (None: not mapped)."""
    kind, code = entry.kind, entry.code
    system, value = (code.system, code.code) if code else (None, None)
    mood = entry.element.get("moodCode")
    if kind == "observation" and system == KANTA and value == "2":
        return "condition"
    if kind == "observation" and system == KANTA and value == "13":
        return "risk"
    if kind == "substanceAdministration" and system == KANTA and value == "19":
        return "immunization"
    if kind == "procedure" and code is not None:
        return "procedure"
    if kind == "organizer" and system == KANTA and value == "27":
        return "lab-order"
    if kind == "organizer" and system == KANTA and value == "26":
        return "imaging-order"
    if kind == "observation" and mood == "EVN":
        if system == LAB_CODES:
            return "lab-result"
        if system == VITALS:
            return "vital-sign"
        if system == PROCEDURES and results.has_imaging_details(entry.element):
            return "imaging-result"
    return None


def is_care_plan(doc: ParsedDocument) -> bool:
    return CAREPLAN_VIEW in doc.source.category_codes or any(
        c.code == CAREPLAN_VIEW for c in doc.header.local.contents_codes
    )


def extract_document(doc: ParsedDocument, issues: list[Issue]) -> DocumentExtraction:
    result = DocumentExtraction(document=doc)
    entries = list(iter_entries(doc.root))
    if not doc.is_current:
        for entry in entries:
            result.outcomes[(entry.key, Outcome.SUPERSEDED)] += 1
        return result

    enc = doc.header.encounter
    ctx = EntryContext(
        document_id=doc.id,
        line=doc.source.line,
        doc=DocContext(doc.root),
        header_author=doc.header.authors[0] if doc.header.authors else None,
        encounter_id=enc.identifier.key if enc and enc.identifier else None,
    )
    if doc.kind != DocumentKind.SUMMARY:
        result.narratives = _narratives(doc)

    plan: CarePlan | None = None
    care_plan_doc = is_care_plan(doc)
    current_section = None
    for entry in entries:
        # Kooste: each top-level section holds an <encounter> entry that says where the
        # item(s) in its subsections came from.
        if doc.kind == DocumentKind.SUMMARY:
            if entry.sections[0] is not current_section:
                current_section = entry.sections[0]
                ctx.summary_link = None
            if entry.kind == "encounter" and entry.code is None:
                ctx.summary_link = summary_link(entry.element)
                result.outcomes[(entry.key, Outcome.CONTEXT)] += 1
                continue

        if care_plan_doc:
            if plan is None:
                plan = careplan.new_care_plan(entry, ctx, doc.header.effective_time)
                result.items.append(plan)
            careplan.add_entry(plan, entry, ctx)
            result.outcomes[(entry.key, Outcome.MAPPED)] += 1
            continue

        handler = classify(entry)
        if handler is None:
            result.outcomes[(entry.key, Outcome.NOT_MAPPED)] += 1
            continue
        try:
            item = _extract(handler, entry, ctx)
        except Exception as e:  # keep going: one broken entry must not stop the export
            issues.append(
                Issue(
                    Severity.ERROR,
                    "extraction-failed",
                    f"{handler} extractor failed on {entry.key}: {type(e).__name__}",
                    doc.source.line,
                    doc.id,
                )
            )
            item = None
        if item is None:
            result.outcomes[(entry.key, Outcome.FAILED)] += 1
            continue
        result.items.append(item)
        result.outcomes[(entry.key, Outcome.MAPPED)] += 1
    return result


def _extract(handler: str, entry: EntryRef, ctx: EntryContext) -> Item | None:
    match handler:
        case "condition":
            return clinical.condition(entry, ctx)
        case "risk":
            return clinical.risk(entry, ctx)
        case "immunization":
            return clinical.immunization(entry, ctx)
        case "procedure":
            return clinical.procedure(entry, ctx)
        case "lab-order":
            return results.order(entry, ctx, "laboratory")
        case "imaging-order":
            return results.order(entry, ctx, "imaging")
        case "lab-result":
            return results.lab_result(entry, ctx)
        case "vital-sign":
            return results.vital_sign(entry, ctx)
        case "imaging-result":
            return results.imaging_result(entry, ctx)
    raise ValueError(f"unknown handler {handler}")


def _narratives(doc: ParsedDocument) -> list[SectionNarrative]:
    out = []
    for path, section in iter_sections(doc.root):
        xhtml = to_xhtml(find(section, "h:text"))
        if xhtml is None:
            continue
        enc = doc.header.encounter
        out.append(
            SectionNarrative(
                source=SourceRef(
                    document_id=doc.id,
                    line=doc.source.line,
                    section=" / ".join(step.label for step in path),
                    encounter_id=enc.identifier.key if enc and enc.identifier else None,
                ),
                view=path[0].code,
                title=path[-1].title,
                xhtml=xhtml,
            )
        )
    return out
