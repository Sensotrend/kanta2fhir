"""Lab and imaging orders, lab results, physiological measurements and imaging results."""

from __future__ import annotations

from kanta2fhir.cda.entries.base import KANTA, LAB, RESULT_STATUS, EntryContext, effective
from kanta2fhir.cda.sections import EntryRef
from kanta2fhir.cda.util import Element, attr, coding, find, findall, period
from kanta2fhir.cda.values import (
    SubObservations,
    coded_value,
    qualifier_values,
    quantity,
    reference_ranges,
    related,
    translations,
    typed_value,
)
from kanta2fhir.model import (
    Coding,
    ImagingResult,
    LabResult,
    Order,
    OrderedTest,
    Quantity,
    VitalSign,
)


def _specimen(el: Element) -> Coding | None:
    return coding(find(el, "h:specimen/h:specimenRole/h:specimenPlayingEntity/h:code"))


def order(entry: EntryRef, ctx: EntryContext, category: str) -> Order:
    """Organizer 27 (lab) or 26 (imaging): general info + one observation per requested test."""
    el = entry.element
    result = Order(category=category, source=ctx.source(entry))
    systems = (LAB, KANTA)
    general_codes = {"20", "26.1"}
    for comp in findall(el, "h:component/h:observation"):
        code = coding(find(comp, "h:code"))
        if code is None:
            continue
        subs = SubObservations(comp, ctx.doc, systems)
        if code.code in general_codes and code.system in systems:
            result.date = effective(comp)
            result.requester = ctx.author(entry, comp)
            if category == "laboratory":
                result.order_id = subs.identifier("21")
                result.note = subs.text("22")
                repeat = subs.elements("32")
                if repeat:
                    result.repeat_period = period(find(repeat[0], "h:effectiveTime"))
                    count = attr(repeat[0], "value", "h:repeatNumber")
                    result.repeat_count = int(count) if count and count.isdigit() else None
            else:
                result.order_id = subs.identifier("26.2")
                result.note = subs.text("26.3")
            continue
        test_code = coded_value(find(comp, "h:code"), ctx.doc)
        if test_code is None:
            continue
        notes = subs.texts("23")
        result.tests.append(
            OrderedTest(
                code=test_code,
                specimen=_specimen(comp),
                note=notes[0] if notes else None,
                procedure_code=subs.coding("37") or subs.coding("26.7"),
                qualifiers=qualifier_values(find(comp, "h:code")),
                reason_codes=subs.codings("26.5"),
            )
        )
    return result


def lab_result(entry: EntryRef, ctx: EntryContext) -> LabResult | None:
    el = entry.element
    code_el = find(el, "h:code")
    code = coding(code_el)
    if code is None:
        return None
    subs = SubObservations(el, ctx.doc, (LAB,))
    status = next((q for q in qualifier_values(code_el) if q.system == RESULT_STATUS), None)
    statement_el = subs.elements("4")
    statement_status = None
    if statement_el:
        statement_status = SubObservations(statement_el[0], ctx.doc, (LAB,)).coding("29")
    issued = subs.value("13")
    return LabResult(
        code=code,
        source=ctx.source(entry),
        local_codes=translations(code_el),
        status=status,
        effective=effective(el),
        value=typed_value(find(el, "h:value"), ctx.doc),
        interpretation=coding(find(el, "h:interpretationCode")),
        reference_ranges=reference_ranges(el, ctx.doc, subs.text("27")),
        specimen=_specimen(el),
        order_id=subs.identifier("21"),
        test_id=subs.identifier("30"),
        performer_name=subs.text("28"),
        method=subs.coding("26"),
        issued=issued if isinstance(issued, str) else None,
        notes=[*subs.texts("23"), *subs.texts("24")],
        procedure_code=subs.coding("37"),
        study_uid=subs.identifier("36"),
        statement=subs.text("4"),
        statement_status=statement_status,
        author=ctx.author(entry),
    )


def vital_sign(entry: EntryRef, ctx: EntryContext) -> VitalSign | None:
    el = entry.element
    code = coding(find(el, "h:code"))
    if code is None:
        return None
    subs = SubObservations(el, ctx.doc, (KANTA,))
    value_el = find(el, "h:value")
    alternatives = [
        Quantity(value=t.get("value", ""), unit=t.get("code"))
        for t in findall(value_el, "h:translation")
        if t.get("value")
    ]
    return VitalSign(
        code=code,
        source=ctx.source(entry),
        effective=effective(el),
        value=quantity(value_el),
        alternative_values=alternatives,
        measurement_id=subs.identifier("23.6"),
        method=subs.coding("23.1"),
        reference_ranges=reference_ranges(el, ctx.doc, subs.text("23.2")),
        abnormality=subs.coding("23.5"),
        notes=subs.texts("23.3"),
        author=ctx.author(entry),
    )


def imaging_result(entry: EntryRef, ctx: EntryContext) -> ImagingResult | None:
    el = entry.element
    code_el = find(el, "h:code")
    code = coded_value(code_el, ctx.doc)
    if code is None:
        return None
    subs = SubObservations(el, ctx.doc, (KANTA,))
    return ImagingResult(
        code=code,
        source=ctx.source(entry),
        qualifiers=qualifier_values(code_el),
        effective=effective(el),
        study_uid=subs.identifier("22.2"),
        accession=subs.identifier("22.1"),
        performers=subs.text("22.4"),
        diagnoses=subs.codings("22.5"),
        procedure_refinements=subs.codings("22.10"),
        interruption_reason=subs.coding("22.7"),
        radiation_dose=subs.quantity("22.8"),
        patient_weight=subs.quantity("22.9"),
        body_sites=subs.codings("3.3"),
        order_id=subs.identifier("26.2"),
        statement=subs.text("24.2"),
        statement_status=subs.coding("24.1"),
        assessment=subs.coding("24.3"),
        author=ctx.author(entry),
    )


def has_imaging_details(el: Element) -> bool:
    """Imaging results carry 22.x/24.x sub-observations (study id, statement …)."""
    for child in related(el):
        c = coding(find(child, "h:code"))
        if c is not None and c.system == KANTA and c.code.split(".")[0] in {"22", "24"}:
            return True
    return False
