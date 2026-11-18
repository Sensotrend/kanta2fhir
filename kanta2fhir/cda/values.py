"""Typed CDA values and Kanta's sub-observation pattern.

Kanta packs most attributes of a clinical statement into ``entryRelationship`` children, each
an observation with a ``code`` (e.g. ``13.6`` "Riskin aste") and a typed ``value``. The helpers
here read those values without each extractor having to repeat the XML handling.
"""

from __future__ import annotations

from collections.abc import Iterator

from kanta2fhir.cda.util import (
    XSI_TYPE,
    Element,
    coding,
    find,
    findall,
    identifier,
    local_name,
    period,
    text,
    ts_to_fhir,
)
from kanta2fhir.model import Coding, Identifier, Quantity, Range, ReferenceRange, Value


class DocContext:
    """Per-document lookups, e.g. resolving ``<reference value="#ID"/>`` to narrative text."""

    def __init__(self, root: Element) -> None:
        self.root = root
        self._by_id: dict[str, Element] | None = None

    def element_by_id(self, ref: str) -> Element | None:
        if self._by_id is None:
            self._by_id = {el.get("ID", ""): el for el in self.root.iter() if el.get("ID")}
        return self._by_id.get(ref.removeprefix("#"))

    def resolve_text(self, el: Element | None) -> str | None:
        """Text of an ED/originalText element: inline text, or the narrative it references."""
        if el is None:
            return None
        ref = find(el, "h:reference")
        if ref is not None and ref.get("value", "").startswith("#"):
            target = self.element_by_id(ref.get("value", ""))
            return text(target)
        return text(el)


def xsi_type(el: Element) -> str:
    return (el.get(XSI_TYPE) or "").rsplit(":", 1)[-1]


def quantity(el: Element | None) -> Quantity | None:
    if el is None or el.get("value") is None:
        return None
    return Quantity(value=el.get("value", ""), unit=el.get("unit"))


def coded_value(el: Element | None, ctx: DocContext | None = None) -> Coding | None:
    """A CD/CV/CE value; when displayName is missing, originalText is used as display."""
    c = coding(el)
    if c is None or c.display or el is None:
        return c
    original = ctx.resolve_text(find(el, "h:originalText")) if ctx else text(el, "h:originalText")
    return Coding(code=c.code, system=c.system, display=original, system_name=c.system_name)


def original_text(el: Element | None, ctx: DocContext) -> str | None:
    return ctx.resolve_text(find(el, "h:originalText"))


def typed_value(el: Element | None, ctx: DocContext) -> Value | None:
    """Convert a ``<value xsi:type=…>`` element to a model value."""
    if el is None or el.get("nullFlavor") is not None:
        return None
    match xsi_type(el):
        case "PQ":
            return quantity(el)
        case "IVL_PQ":
            low, high = quantity(find(el, "h:low")), quantity(find(el, "h:high"))
            return Range(low=low, high=high) if (low or high) else None
        case "CD" | "CV" | "CE" | "CO" | "CS":
            return coded_value(el, ctx)
        case "ST" | "SC":
            return text(el)
        case "ED":
            return ctx.resolve_text(el)
        case "BL":
            v = el.get("value")
            return None if v is None else v == "true"
        case "TS":
            return ts_to_fhir(el.get("value"))
        case "IVL_TS":
            return period(el)
        case "II":
            return identifier(el)
        case "INT":
            v = el.get("value")
            return int(v) if v and v.lstrip("-").isdigit() else None
        case _:
            return text(el)


def related(el: Element) -> Iterator[Element]:
    """The clinical statements inside ``entryRelationship``/``component`` children of ``el``."""
    for rel in [*findall(el, "h:entryRelationship"), *findall(el, "h:component")]:
        for child in rel:
            if isinstance(child.tag, str) and local_name(child) != "templateId":
                yield child


class SubObservations:
    """The ``entryRelationship`` observations of a statement, indexed by code.

    ``codes`` limits the index to the given code systems (Kanta uses several, e.g.
    ``1.2.246.537.6.12.999.2003`` for diagnoses and ``1.2.246.537.6.12.2002.103`` for lab).
    """

    def __init__(self, el: Element, ctx: DocContext, systems: tuple[str, ...]) -> None:
        self.ctx = ctx
        self._items: dict[str, list[Element]] = {}
        for child in related(el):
            c = coding(find(child, "h:code"))
            if c is not None and c.system in systems:
                self._items.setdefault(c.code, []).append(child)

    def elements(self, code: str) -> list[Element]:
        return self._items.get(code, [])

    def values(self, code: str) -> list[Value]:
        """All values of all sub-observations with this code (an observation may repeat
        ``<value>``, e.g. 19.1 lists several diseases)."""
        out: list[Value] = []
        for obs in self.elements(code):
            for v in findall(obs, "h:value"):
                val = typed_value(v, self.ctx)
                if val is not None:
                    out.append(val)
        return out

    def value(self, code: str) -> Value | None:
        vals = self.values(code)
        return vals[0] if vals else None

    def text(self, code: str) -> str | None:
        v = self.value(code)
        return v if isinstance(v, str) else None

    def texts(self, code: str) -> list[str]:
        return [v for v in self.values(code) if isinstance(v, str)]

    def coding(self, code: str) -> Coding | None:
        v = self.value(code)
        return v if isinstance(v, Coding) else None

    def codings(self, code: str) -> list[Coding]:
        return [v for v in self.values(code) if isinstance(v, Coding)]

    def identifier(self, code: str) -> Identifier | None:
        v = self.value(code)
        return v if isinstance(v, Identifier) else None

    def quantity(self, code: str) -> Quantity | None:
        v = self.value(code)
        return v if isinstance(v, Quantity) else None

    def boolean(self, code: str) -> bool | None:
        v = self.value(code)
        return v if isinstance(v, bool) else None


def reference_ranges(
    el: Element, ctx: DocContext, text_value: str | None = None
) -> list[ReferenceRange]:
    """``referenceRange/observationRange`` values, plus an optional free-text range."""
    out: list[ReferenceRange] = []
    for rr in findall(el, "h:referenceRange/h:observationRange"):
        v = typed_value(find(rr, "h:value"), ctx)
        if isinstance(v, Range):
            out.append(ReferenceRange(low=v.low, high=v.high, text=text(rr, "h:text")))
    if text_value:
        if out and out[0].text is None:
            out[0] = ReferenceRange(low=out[0].low, high=out[0].high, text=text_value)
        else:
            out.append(ReferenceRange(text=text_value))
    return out


def qualifier_values(code_el: Element | None) -> list[Coding]:
    """Values of ``code/qualifier`` elements (e.g. PAA/SIVU, side, anatomical region)."""
    return [c for q in findall(code_el, "h:qualifier") if (c := coding(find(q, "h:value")))]


def translations(code_el: Element | None) -> list[Coding]:
    return [c for t in findall(code_el, "h:translation") if (c := coding(t))]
