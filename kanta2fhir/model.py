"""Canonical, format-neutral clinical model.

The CDA parser fills these classes, and the FHIR builders read them. Code systems are kept
as they appear in the source (OIDs), and translation to FHIR system URIs happens later, in
the terminology layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class Coding:
    """A coded value as found in the source, e.g. ``1.2.246.537.5.1.1997#1 "Mies"``."""

    code: str
    system: str | None = None  # OID, e.g. "1.2.246.537.5.1.1997"
    display: str | None = None
    system_name: str | None = None


@dataclass(frozen=True, slots=True)
class Identifier:
    """An HL7 v3 instance identifier: ``root`` (OID) plus optional ``extension``."""

    system: str  # the II root
    value: str | None = None  # the II extension
    masked: bool = False  # True when the source replaced the value with '****'

    @property
    def key(self) -> str:
        """A string usable as a dictionary key, e.g. ``1.2.3`` or ``1.2.3/abc``."""
        return self.system if self.value is None else f"{self.system}/{self.value}"


@dataclass(frozen=True, slots=True)
class Period:
    """Start and end as FHIR ``dateTime`` strings (either may be missing)."""

    start: str | None = None
    end: str | None = None


@dataclass(frozen=True, slots=True)
class HumanName:
    family: tuple[str, ...] = ()
    given: tuple[str, ...] = ()
    calling_name: str | None = None  # Finnish "kutsumanimi" (given qualifier="CL")
    prefix: tuple[str, ...] = ()
    suffix: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Organization:
    identifier: Identifier | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Person:
    """A healthcare professional (author, performer …)."""

    identifier: Identifier | None = None
    name: HumanName | None = None


@dataclass(frozen=True, slots=True)
class Author:
    function: Coding | None = None
    time: str | None = None
    person: Person | None = None
    organization: Organization | None = None


@dataclass(frozen=True, slots=True)
class Demographics:
    """Patient demographics as stated in one document."""

    name: HumanName | None = None
    gender: Coding | None = None
    birth_date: str | None = None


@dataclass(slots=True)
class Patient:
    """The patient, consolidated over all documents."""

    hetu: str = field(repr=False)  # Finnish personal identity code; never log it
    pseudonym: str  # stable hash of the HETU, safe for reports and logs
    name: HumanName | None = None
    gender: Coding | None = None
    birth_date: str | None = None


class DocumentKind(StrEnum):
    SERVICE_EVENT = "service_event"  # Palvelutapahtuma-asiakirja
    RECORD_ENTRY = "record_entry"  # Hoitoasiakirja / Kertomusteksti
    SUMMARY = "summary"  # Kooste (generated summary; fallback only, D7)
    UNKNOWN = "unknown"


@dataclass(slots=True)
class Encounter:
    """A service event (palvelutapahtuma)."""

    identifier: Identifier
    period: Period | None = None
    encounter_type: Coding | None = None  # hl7fi:encompassingEncounterCode (outpatient/inpatient)
    service_provider: Organization | None = None
    participants: list[Organization] = field(default_factory=list)
    service_event_document: str | None = None  # document id of the Palvelutapahtuma-asiakirja
    documents: list[str] = field(default_factory=list)  # ids of record entries in this event


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Issue:
    """Something worth reporting about the input. Must never contain personal data."""

    severity: Severity
    code: str  # short machine-readable id, e.g. "invalid-json"
    message: str
    line: int | None = None
    document_id: str | None = None
