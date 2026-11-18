"""Terveys- ja hoitosuunnitelma (health and care plan, view 345).

A care plan document holds a tree of observations, organizers and encounters coded with the
care plan structure codes (``1.2.246.537.6.12.2002.345``). All entries of the document are
collected into one CarePlan.
"""

from __future__ import annotations

from kanta2fhir.cda.entries.base import CAREPLAN, EntryContext, effective
from kanta2fhir.cda.sections import EntryRef
from kanta2fhir.cda.util import Element, coding, find, findall, local_name, period, text
from kanta2fhir.cda.values import DocContext, related, typed_value
from kanta2fhir.model import (
    CarePlan,
    CareTeamMember,
    Coding,
    GoalTarget,
    PlannedService,
    Quantity,
    Range,
    SourceRef,
)

# Codes whose value is a piece of text, and the CarePlan list it goes into.
_TEXT_LISTS = {
    "101": "needs",
    "102": "functional_needs",
    "114": "coordinators",
    "117": "coordinators",
    "201": "goals",
    "202": "functional_goals",
    "211": "goal_setters",
    "301": "means",
}
_TEXT_FIELDS = {"603": "diagnosis_list", "605": "medication_list", "601": "additional_info"}


def new_care_plan(entry: EntryRef, ctx: EntryContext, date: str | None) -> CarePlan:
    return CarePlan(
        source=SourceRef(
            document_id=ctx.document_id,
            line=ctx.line,
            section=entry.path[0].label if entry.path else "",
            encounter_id=ctx.encounter_id,
        ),
        date=date,
        author=ctx.author(entry),
    )


def add_entry(plan: CarePlan, entry: EntryRef, ctx: EntryContext) -> None:
    _visit(plan, entry.element, ctx.doc)


def _code(el: Element) -> Coding | None:
    return coding(find(el, "h:code"))


def _value_text(el: Element, ctx: DocContext) -> str | None:
    v = typed_value(find(el, "h:value"), ctx)
    return v if isinstance(v, str) else None


def _visit(plan: CarePlan, el: Element, ctx: DocContext) -> None:
    code = _code(el)
    kind = local_name(el)
    if code is not None and code.system == CAREPLAN:
        c = code.code
        if c in _TEXT_LISTS and (t := _value_text(el, ctx)):
            getattr(plan, _TEXT_LISTS[c]).append(t)
        elif c in _TEXT_FIELDS:
            setattr(plan, _TEXT_FIELDS[c], _value_text(el, ctx))
        elif c == "111":
            v = typed_value(find(el, "h:value"), ctx)
            if isinstance(v, Coding):
                plan.reasons.append(v)
        elif c == "212":
            plan.targets.append(_target(el, ctx))
            return
        elif c in {"302", "501"} and kind == "encounter":
            plan.care_team.append(_team_member(el, code, ctx))
            return
    elif code is not None and kind == "encounter":
        plan.planned_services.append(_service(el, code, ctx))
        return
    for child in related(el):
        _visit(plan, child, ctx)


def _first_related(el: Element, code: str) -> Element | None:
    for child in related(el):
        c = _code(child)
        if c is not None and c.system == CAREPLAN and c.code == code:
            return child
    return None


def _target(el: Element, ctx: DocContext) -> GoalTarget:
    value = typed_value(find(el, "h:value"), ctx)
    condition = _first_related(el, "213")
    rng = typed_value(find(condition, "h:value"), ctx) if condition is not None else None
    note_el = _first_related(condition, "214") if condition is not None else None
    return GoalTarget(
        code=value if isinstance(value, Coding) else Coding(code="?"),
        range=rng if isinstance(rng, Range) else None,
        note=_value_text(note_el, ctx) if note_el is not None else None,
    )


def _team_member(el: Element, role: Coding, ctx: DocContext) -> CareTeamMember:
    entity = find(el, "h:performer/h:assignedEntity")
    note = None
    for code in ("306", "504"):
        child = _first_related(el, code)
        if child is not None:
            note = _value_text(child, ctx)
    return CareTeamMember(
        role=role,
        organization=text(entity, "h:representedOrganization/h:name"),
        profession=coding(find(entity, "h:code/h:translation/h:qualifier/h:value")),
        note=note,
    )


def _service(el: Element, code: Coding, ctx: DocContext) -> PlannedService:
    service = PlannedService(code=code)
    detail = find(el, "h:entryRelationship/h:encounter")
    if detail is None:
        return service
    p = period(find(detail, "h:effectiveTime"))
    service.start = p.start if p else effective(detail)
    for child in related(detail):
        c = _code(child)
        if c is None or c.system != CAREPLAN:
            for sub in related(child):  # organizer with conditions
                _service_condition(service, sub, ctx)
            continue
        if c.code == "308":
            service.content = _value_text(child, ctx)
        elif c.code == "311":
            service.note = _value_text(child, ctx)
        elif c.code == "312":
            v = typed_value(find(child, "h:value"), ctx)
            service.status = v if isinstance(v, Coding) else None
            when = _first_related(child, "313")
            if when is not None:
                d = typed_value(find(when, "h:value"), ctx)
                service.status_date = d if isinstance(d, str) else None
    return service


def _service_condition(service: PlannedService, el: Element, ctx: DocContext) -> None:
    c = _code(el)
    if c is None or c.system != CAREPLAN:
        return
    if c.code == "315" and (t := _value_text(el, ctx)):
        service.conditions.append(t)
    elif c.code == "316":
        for criterion in findall(el, "h:precondition/h:criterion"):
            name = coding(find(criterion, "h:code"))
            rng = typed_value(find(criterion, "h:value"), ctx)
            if name is None:
                continue
            label = name.display or name.code
            if isinstance(rng, Range):
                label = f"{label} {_range_text(rng)}"
            service.conditions.append(label)


def _range_text(rng: Range) -> str:
    def q(x: Quantity | None) -> str:
        return "" if x is None else x.value

    unit = (rng.low or rng.high).unit if (rng.low or rng.high) else None
    return f"{q(rng.low)}-{q(rng.high)}{f' {unit}' if unit else ''}".strip()
