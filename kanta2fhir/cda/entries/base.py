"""Shared context for entry extractors."""

from __future__ import annotations

from dataclasses import dataclass

from kanta2fhir.cda.header import author as parse_author
from kanta2fhir.cda.sections import EntryRef
from kanta2fhir.cda.util import Element, attr, find, findall, identifier, period, ts_to_fhir
from kanta2fhir.cda.values import DocContext
from kanta2fhir.model import Author, SourceRef

# Code systems
KANTA = "1.2.246.537.6.12.999.2003"  # KanTa technical CDA R2 structure codes
LAB = "1.2.246.537.6.12.2002.103"  # laboratory view structure codes
LAB_CODES = "1.2.246.537.6.3.2006"  # Kuntaliitto laboratory nomenclature
VITALS = "1.2.246.537.6.96.2008"  # physiological measurements (LOINC codes)
PROCEDURES = "1.2.246.537.6.2.2007"  # THL procedure classification
CAREPLAN = "1.2.246.537.6.12.2002.345"  # health and care plan structure codes
PRIMARY_SECONDARY = "1.2.246.537.5.40005.2003"  # PAA / SIVU
RESULT_STATUS = "1.2.246.537.5.85.1997"


@dataclass(frozen=True, slots=True)
class SummaryLink:
    """The ``encounter`` entry that precedes each item in a Kooste document."""

    encounter_id: str | None
    document_id: str | None  # the original document the item comes from
    act_ids: tuple[str, ...]


@dataclass(slots=True)
class EntryContext:
    document_id: str
    line: int
    doc: DocContext
    header_author: Author | None
    encounter_id: str | None
    summary_link: SummaryLink | None = None

    def source(self, entry: EntryRef) -> SourceRef:
        link = self.summary_link
        return SourceRef(
            document_id=self.document_id,
            line=self.line,
            section=entry.path_label,
            entry_id=identifier(find(entry.element, "h:id")),
            encounter_id=(link.encounter_id if link else None) or self.encounter_id,
            from_summary=link is not None,
            origin_document=link.document_id if link else None,
        )

    def author(self, entry: EntryRef, el: Element | None = None) -> Author | None:
        """The nearest author: on the statement, then on enclosing sections, then the header."""
        for candidate in (el if el is not None else entry.element, *reversed(entry.sections)):
            a = find(candidate, "h:author")
            if a is not None:
                return parse_author(a)
        return self.header_author


def effective(el: Element | None) -> str | None:
    """effectiveTime as a single point: ``@value``, else ``low``."""
    et = find(el, "h:effectiveTime")
    if et is None:
        return None
    if et.get("value") is not None:
        return ts_to_fhir(et.get("value"))
    p = period(et)
    return p.start if p else None


def summary_link(el: Element) -> SummaryLink:
    doc_id = attr(el, "root", "h:reference/h:externalDocument/h:id")
    acts = tuple(
        i.get("root", "") + (f"/{i.get('extension')}" if i.get("extension") else "")
        for i in findall(el, "h:reference/h:externalAct/h:id")
    )
    return SummaryLink(
        encounter_id=attr(el, "root", "h:performer/h:assignedEntity/h:id"),
        document_id=doc_id,
        act_ids=acts,
    )
