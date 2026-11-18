"""FHIR datatypes from model values: ids, Coding, CodeableConcept, Quantity, Identifier …"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from kanta2fhir.model import Coding, HumanName, Identifier, Period, Quantity, Range, ReferenceRange
from kanta2fhir.terminology import FhirCoding, Terminology
from kanta2fhir.terminology.lookup import UCUM, system_uri

# Fixed namespace so that the same input always gives the same resource ids.
NAMESPACE = uuid.UUID("c0292c14-3bb1-53dd-b1a2-95f83be3c515")
TRANSLATION = "http://hl7.org/fhir/StructureDefinition/translation"
HETU_SYSTEM = "urn:oid:1.2.246.21"

JSON = dict[str, Any]


def resource_id(*parts: str) -> str:
    """A deterministic UUID for a resource, from stable source identifiers."""
    return str(uuid.uuid5(NAMESPACE, "|".join(parts)))


def full_url(rid: str) -> str:
    return f"urn:uuid:{rid}"


def compact(d: JSON) -> JSON:
    """Drop None values and empty lists/dicts (FHIR does not allow empty elements)."""
    return {k: v for k, v in d.items() if v not in (None, [], {}, "")}


def translation(text: str, lang: str = "en") -> JSON:
    return {
        "extension": [
            {
                "url": TRANSLATION,
                "extension": [
                    {"url": "lang", "valueCode": lang},
                    {"url": "content", "valueString": text},
                ],
            }
        ]
    }


def coding(fc: FhirCoding) -> JSON:
    out = compact({"system": fc.system, "code": fc.code, "display": fc.display})
    if fc.display_en and fc.display_en != fc.display:
        if fc.display:
            out["_display"] = translation(fc.display_en)
        else:
            out["display"] = fc.display_en
    return out


def codeable_concept(
    c: Coding | None, terminology: Terminology, text: str | None = None
) -> JSON | None:
    """All codings for a Kanta coding (original first), plus optional text."""
    if c is None:
        return {"text": text} if text else None
    return compact(
        {"coding": [coding(fc) for fc in terminology.codings(c)], "text": text or c.display}
    )


def codeable_concepts(codes: list[Coding], terminology: Terminology) -> list[JSON]:
    return [cc for c in codes if (cc := codeable_concept(c, terminology))]


def fixed_concept(system: str, code: str, display: str | None = None) -> JSON:
    return {"coding": [compact({"system": system, "code": code, "display": display})]}


def decimal(value: str) -> int | float | None:
    """A JSON number for a decimal string (precision beyond float is not kept)."""
    try:
        d = Decimal(value.replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None
    if not d.is_finite():
        return None
    return int(d) if d == d.to_integral_value() and "." not in value else float(d)


def quantity(q: Quantity | None, terminology: Terminology) -> JSON | None:
    if q is None:
        return None
    value = decimal(q.value)
    if value is None:
        return None
    code = terminology.ucum(q.unit)
    out: JSON = {"value": value}
    if q.unit:
        out["unit"] = q.unit
    if code:
        out["system"] = UCUM
        out["code"] = code
    return out


def range_(r: Range | None, terminology: Terminology) -> JSON | None:
    if r is None:
        return None
    return compact({"low": quantity(r.low, terminology), "high": quantity(r.high, terminology)})


def reference_range(rr: ReferenceRange, terminology: Terminology) -> JSON | None:
    out = compact(
        {
            "low": quantity(rr.low, terminology),
            "high": quantity(rr.high, terminology),
            "text": rr.text,
        }
    )
    return out or None


def period(p: Period | None) -> JSON | None:
    if p is None:
        return None
    return compact({"start": p.start, "end": p.end}) or None


def identifier(i: Identifier | None) -> JSON | None:
    """An HL7 v3 II as a FHIR Identifier.

    ``root`` + ``extension`` → system ``urn:oid:root``, value ``extension``;
    ``root`` alone (an OID that is itself the identifier) → ``urn:ietf:rfc:3986``.
    """
    if i is None or i.masked:
        return None
    if i.value is None:
        return {"system": "urn:ietf:rfc:3986", "value": system_uri(i.system)}
    return {"system": system_uri(i.system), "value": i.value}


def human_names(name: HumanName | None) -> list[JSON]:
    if name is None:
        return []
    official = compact(
        {
            "use": "official",
            "family": " ".join(name.family) or None,
            "given": list(name.given),
            "prefix": list(name.prefix),
            "suffix": list(name.suffix),
        }
    )
    out = [official]
    if name.calling_name and name.calling_name not in name.given:
        out.append({"use": "usual", "given": [name.calling_name]})
    return out


def name_text(name: HumanName | None) -> str | None:
    if name is None:
        return None
    parts = [*name.prefix, *name.given, *name.family, *name.suffix]
    return " ".join(parts) or None
