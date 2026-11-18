"""Consolidation: merge extracted items of one patient, removing duplicates.

Rules (plan §2.3, D7):
1. Original documents first, newest first, so the latest recording of a duplicate wins.
2. Duplicates among originals are found by Kanta's unique identifiers (diagnosis episode,
   risk id, immunisation id, procedure id, lab test id, measurement id …), falling back to
   the entry id and then to a content key.
3. Kooste (summary) items are a fallback only. An item is dropped when the original document
   it came from is in the export, or when an equal item is already present.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field

from kanta2fhir.extract import DocumentExtraction, Item
from kanta2fhir.model import (
    CarePlan,
    ClinicalData,
    Condition,
    DocumentKind,
    ImagingResult,
    Immunization,
    LabResult,
    Order,
    Procedure,
    RiskItem,
    VitalSign,
)
from kanta2fhir.record import instant

_LISTS: dict[type, str] = {
    Condition: "conditions",
    RiskItem: "risks",
    Immunization: "immunizations",
    Procedure: "procedures",
    Order: "orders",
    LabResult: "lab_results",
    VitalSign: "vital_signs",
    ImagingResult: "imaging_results",
    CarePlan: "care_plans",
}


@dataclass(slots=True)
class ConsolidationStats:
    """Counts per item type (the list name in ClinicalData)."""

    from_originals: Counter[str] = field(default_factory=Counter)
    from_summaries: Counter[str] = field(default_factory=Counter)
    duplicates_dropped: Counter[str] = field(default_factory=Counter)
    summary_dropped_origin_present: Counter[str] = field(default_factory=Counter)
    summary_used: Counter[str] = field(default_factory=Counter)


def item_key(item: Item) -> Hashable:
    """Identity of an item for de-duplication."""
    entry = item.source.entry_id.key if item.source.entry_id else None
    match item:
        case Condition():
            if item.episode_id:
                return ("condition", item.episode_id.key, item.code.code)
            return ("condition", item.code.system, item.code.code, item.recorded)
        case RiskItem():
            if item.risk_id:
                return ("risk", item.risk_id.key)
            return ("risk", item.code.code if item.code else None, item.date, item.text)
        case Immunization():
            if item.immunization_id:
                return ("immunization", item.immunization_id.key)
            return ("immunization", _code(item.vaccine), _code(item.product), item.date)
        case Procedure():
            if item.procedure_id:
                return ("procedure", item.procedure_id.key)
            if entry:
                return ("procedure", entry)
            start = item.performed.start if item.performed else None
            return ("procedure", item.code.code, start, item.text)
        case Order():
            if item.order_id:
                return ("order", item.category, item.order_id.key)
            return ("order", item.category, entry or item.date)
        case LabResult():
            if item.test_id:
                return ("lab", item.test_id.key)
            if entry:
                return ("lab", entry)
            return ("lab", item.code.code, item.effective, repr(item.value))
        case VitalSign():
            if item.measurement_id:
                return ("vital", item.measurement_id.key)
            if entry:
                return ("vital", entry)
            return ("vital", item.code.code, item.effective, repr(item.value))
        case ImagingResult():
            if entry:
                return ("imaging", entry)
            uid = item.study_uid.key if item.study_uid else None
            return ("imaging", item.code.code, uid, item.has_statement, item.effective)
        case CarePlan():
            return ("careplan", item.source.document_id)
    raise TypeError(f"unknown item type {type(item).__name__}")


def _code(c: object) -> str | None:
    return getattr(c, "code", None)


def consolidate(
    extractions: Iterable[DocumentExtraction],
) -> tuple[ClinicalData, ConsolidationStats]:
    extractions = list(extractions)
    data = ClinicalData()
    stats = ConsolidationStats()
    seen: set[Hashable] = set()

    originals = [x for x in extractions if x.document.kind != DocumentKind.SUMMARY]
    summaries = [x for x in extractions if x.document.kind == DocumentKind.SUMMARY]
    originals.sort(key=lambda x: instant(x.document.header.effective_time), reverse=True)
    original_ids = {x.document.id for x in originals if x.document.is_current}

    for x in originals:
        data.narratives.extend(x.narratives)
        for item in x.items:
            name = _LISTS[type(item)]
            stats.from_originals[name] += 1
            key = item_key(item)
            if key in seen:
                stats.duplicates_dropped[name] += 1
                continue
            seen.add(key)
            getattr(data, name).append(item)

    for x in summaries:
        for item in x.items:
            name = _LISTS[type(item)]
            stats.from_summaries[name] += 1
            if item.source.origin_document in original_ids:
                stats.summary_dropped_origin_present[name] += 1
                continue
            key = item_key(item)
            if key in seen:
                stats.duplicates_dropped[name] += 1
                continue
            seen.add(key)
            stats.summary_used[name] += 1
            getattr(data, name).append(item)

    _sort(data)
    return data, stats


def _sort(data: ClinicalData) -> None:
    """Chronological order, newest first, within each list."""

    def when(item: Item) -> str:
        match item:
            case Condition():
                return item.recorded or ""
            case RiskItem():
                return item.date or ""
            case Immunization():
                return item.date or ""
            case Procedure():
                return (item.performed.start if item.performed else None) or ""
            case Order():
                return item.date or ""
            case LabResult() | VitalSign() | ImagingResult():
                return item.effective or ""
            case CarePlan():
                return item.date or ""
        return ""

    for name in _LISTS.values():
        items = getattr(data, name)
        items.sort(key=lambda i: instant(when(i) or None), reverse=True)
