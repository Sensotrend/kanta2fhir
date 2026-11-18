"""Small helpers for reading CDA XML with lxml."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from lxml import etree

from kanta2fhir.model import Coding, HumanName, Identifier, Organization, Period, Person

NS = {
    "h": "urn:hl7-org:v3",
    "fi": "urn:hl7finland",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}
H = "{urn:hl7-org:v3}"
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

# CDA timestamps without an explicit offset are Finnish local time.
HELSINKI = ZoneInfo("Europe/Helsinki")

# Kanta masks personal identity codes inside CDA with this value.
MASKED = "****"

Element = etree._Element


class NotCdaError(ValueError):
    """The payload is not an HL7 v3 CDA ClinicalDocument."""


def parse_cda(data: bytes) -> Element:
    """Parse a CDA document safely (no external entities, no network access)."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    try:
        root = etree.fromstring(data, parser)
    except etree.XMLSyntaxError as e:
        raise NotCdaError(f"Not well-formed XML: {e}") from e
    if root.tag != f"{H}ClinicalDocument":
        raise NotCdaError(f"Root element is {etree.QName(root).localname}, not ClinicalDocument")
    return root


def local_name(el: Element) -> str:
    return etree.QName(el).localname


def find(el: Element | None, path: str) -> Element | None:
    """``el.find(path)`` with the CDA namespaces; None-safe."""
    return None if el is None else el.find(path, NS)


def findall(el: Element | None, path: str) -> list[Element]:
    return [] if el is None else el.findall(path, NS)


def text(el: Element | None, path: str = ".") -> str | None:
    """Whitespace-normalised text content of the element at ``path``, or None if empty."""
    target = find(el, path) if path != "." else el
    if target is None:
        return None
    value = " ".join("".join(target.itertext()).split())
    return value or None


def attr(el: Element | None, name: str, path: str = ".") -> str | None:
    target = find(el, path) if path != "." else el
    return None if target is None else target.get(name)


def coding(el: Element | None) -> Coding | None:
    """A CD/CE/CV element as a Coding; None for missing elements and nullFlavors."""
    if el is None or el.get("code") is None:
        return None
    display = el.get("displayName")
    return Coding(
        code=el.get("code", ""),
        system=el.get("codeSystem"),
        display=display.strip() if display else None,
        system_name=el.get("codeSystemName"),
    )


def identifier(el: Element | None) -> Identifier | None:
    """An II element as an Identifier; None for missing elements and nullFlavors."""
    if el is None or el.get("root") is None:
        return None
    ext = el.get("extension")
    if ext == MASKED:
        return Identifier(system=el.get("root", ""), value=None, masked=True)
    return Identifier(system=el.get("root", ""), value=ext)


def template_ids(el: Element) -> tuple[str, ...]:
    return tuple(t.get("root", "") for t in findall(el, "h:templateId"))


_TS = re.compile(
    r"^(\d{4})(\d{2})?(\d{2})?"  # date: YYYY[MM[DD]]
    r"(?:(\d{2})(\d{2})?(\d{2})?(?:\.(\d+))?)?"  # time: HH[MM[SS[.fff]]]
    r"([+-]\d{4})?$"  # offset: ±HHMM
)


def ts_to_fhir(value: str | None, default_tz: tzinfo = HELSINKI) -> str | None:
    """Convert an HL7 v3 TS (e.g. ``20241218125527``) to a FHIR date/dateTime.

    Precision is kept: ``2024`` → ``2024``, ``20241218`` → ``2024-12-18``. Values with a time
    get seconds and an offset, as FHIR requires; a missing offset means Finnish local time.
    """
    if not value:
        return None
    m = _TS.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, fraction, offset = m.groups()
    if month is None:
        return year
    if day is None:
        return f"{year}-{month}"
    if hour is None:
        return f"{year}-{month}-{day}"

    tz: tzinfo = default_tz
    if offset:
        sign = 1 if offset[0] == "+" else -1
        delta = timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5]))
        tz = UTC if not delta else timezone(sign * delta)
    try:
        dt = datetime(
            int(year), int(month), int(day), int(hour), int(minute or 0), int(second or 0)
        ).replace(tzinfo=tz)
    except ValueError:
        return None
    out = dt.isoformat(timespec="seconds")  # 2024-12-18T12:55:27+02:00
    if fraction:
        out = f"{out[:19]}.{fraction}{out[19:]}"
    return out


def period(el: Element | None) -> Period | None:
    """An IVL_TS (``low``/``high``) or a single TS ``value`` as a Period."""
    if el is None or el.get("nullFlavor") is not None:
        return None
    if el.get("value") is not None:
        point = ts_to_fhir(el.get("value"))
        return Period(start=point, end=point) if point else None
    start = ts_to_fhir(attr(el, "value", "h:low"))
    end = ts_to_fhir(attr(el, "value", "h:high"))
    return Period(start=start, end=end) if (start or end) else None


def human_name(el: Element | None) -> HumanName | None:
    if el is None:
        return None
    given: list[str] = []
    calling_name = None
    for g in findall(el, "h:given"):
        value = text(g)
        if not value:
            continue
        if g.get("qualifier") == "CL":
            calling_name = value
        elif value not in given:
            given.append(value)
    family = tuple(v for f in findall(el, "h:family") if (v := text(f)))
    prefix = tuple(v for p in findall(el, "h:prefix") if (v := text(p)))
    suffix = tuple(v for s in findall(el, "h:suffix") if (v := text(s)))
    if not (family or given or calling_name):
        return None
    return HumanName(
        family=family, given=tuple(given), calling_name=calling_name, prefix=prefix, suffix=suffix
    )


def organization(el: Element | None) -> Organization | None:
    """Any organization-like element with ``id`` and ``name`` children."""
    if el is None:
        return None
    ident = identifier(find(el, "h:id"))
    name = text(el, "h:name")
    return Organization(identifier=ident, name=name) if (ident or name) else None


def person(assigned: Element | None) -> Person | None:
    """An assignedAuthor/assignedEntity as a Person (id + assignedPerson/name)."""
    if assigned is None:
        return None
    ident = identifier(find(assigned, "h:id"))
    name = human_name(find(assigned, "h:assignedPerson/h:name"))
    return Person(identifier=ident, name=name) if (ident or name) else None
