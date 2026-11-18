"""Diagnoses, risk information, immunisations and procedures."""

from __future__ import annotations

from kanta2fhir.cda.entries.base import KANTA, PRIMARY_SECONDARY, EntryContext, effective
from kanta2fhir.cda.sections import EntryRef
from kanta2fhir.cda.util import attr, coding, find, period, text
from kanta2fhir.cda.values import SubObservations, coded_value, original_text, qualifier_values
from kanta2fhir.model import Coding, Condition, Immunization, Procedure, Quantity, RiskItem


def _primary(qualifiers: list[Coding]) -> bool | None:
    for q in qualifiers:
        if q.system == PRIMARY_SECONDARY:
            return {"PAA": True, "SIVU": False}.get(q.code)
    return None


def condition(entry: EntryRef, ctx: EntryContext) -> Condition | None:
    el = entry.element
    value_el = find(el, "h:value")
    code = coded_value(value_el, ctx.doc)
    if code is None:
        return None
    subs = SubObservations(el, ctx.doc, (KANTA,))
    return Condition(
        code=code,
        source=ctx.source(entry),
        text=original_text(value_el, ctx.doc),
        recorded=effective(el),
        primary=_primary(qualifier_values(find(el, "h:code"))),
        permanence=subs.coding("2.1"),
        certainty=subs.coding("2.2"),
        reason_for_visit=subs.boolean("2.10"),
        episode_id=subs.identifier("2.14"),
        episode_name=subs.text("2.15"),
        author=ctx.author(entry),
    )


def risk(entry: EntryRef, ctx: EntryContext) -> RiskItem:
    el = entry.element
    value_el = find(el, "h:value")
    subs = SubObservations(el, ctx.doc, (KANTA,))
    return RiskItem(
        source=ctx.source(entry),
        code=coded_value(value_el, ctx.doc),
        text=original_text(value_el, ctx.doc),
        date=effective(el),
        risk_id=subs.identifier("13.9"),
        severity=subs.coding("13.6"),
        risk_type=subs.coding("13.7"),
        certainty=subs.coding("2.2"),
        permanence=subs.coding("2.1"),
        agents=subs.codings("13.2"),
        note=subs.text("13.4"),
        author=ctx.author(entry),
    )


def immunization(entry: EntryRef, ctx: EntryContext) -> Immunization:
    el = entry.element
    subs = SubObservations(el, ctx.doc, (KANTA,))
    material = find(el, "h:consumable/h:manufacturedProduct/h:manufacturedMaterial")
    product = find(
        el, "h:entryRelationship/h:supply/h:product/h:manufacturedProduct/h:manufacturedMaterial"
    )
    dose_el = find(el, "h:doseQuantity")
    dose_number = attr(el, "value", "h:repeatNumber")
    return Immunization(
        source=ctx.source(entry),
        date=effective(el),
        status=attr(el, "code", "h:statusCode"),
        vaccine=coded_value(find(material, "h:code"), ctx.doc),
        product=coded_value(find(product, "h:code"), ctx.doc),
        lot_number=text(product, "h:lotNumberText") or text(material, "h:lotNumberText"),
        route=coding(find(el, "h:routeCode")),
        site=coding(find(el, "h:approachSiteCode")),
        dose=Quantity(dose_el.get("value", ""), dose_el.get("unit"))
        if dose_el is not None and dose_el.get("value")
        else None,
        dose_number=int(dose_number) if dose_number and dose_number.isdigit() else None,
        target_diseases=subs.codings("19.1"),
        immunization_id=subs.identifier("19.7"),
        author=ctx.author(entry),
    )


def procedure(entry: EntryRef, ctx: EntryContext) -> Procedure | None:
    el = entry.element
    code_el = find(el, "h:code")
    code = coded_value(code_el, ctx.doc)
    if code is None:
        return None
    subs = SubObservations(el, ctx.doc, (KANTA,))
    return Procedure(
        code=code,
        source=ctx.source(entry),
        text=original_text(code_el, ctx.doc),
        performed=period(find(el, "h:effectiveTime")),
        primary=_primary(qualifier_values(code_el)),
        additional_codes=subs.codings("3.7"),
        procedure_type=subs.coding("3.9"),
        body_sites=subs.codings("3.3"),
        procedure_id=subs.identifier("3.8"),
        author=ctx.author(entry),
    )
