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


# --- Clinical content (milestone 2) -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Quantity:
    value: str  # decimal as in the source, to keep precision
    unit: str | None = None  # as in the source; UCUM normalisation happens in the terminology layer


@dataclass(frozen=True, slots=True)
class Range:
    low: Quantity | None = None
    high: Quantity | None = None


@dataclass(frozen=True, slots=True)
class ReferenceRange:
    low: Quantity | None = None
    high: Quantity | None = None
    text: str | None = None


# A typed CDA value (xsi:type PQ, IVL_PQ, CD/CV/CE, ST/ED, BL, TS, II, INT, IVL_TS).
Value = Quantity | Range | Coding | str | bool | int | Identifier | Period


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Where an item came from."""

    document_id: str
    line: int
    section: (
        str  # section path label, e.g. "98 Yleislääketiede / 16 Hoidon arviointi / 13 Diagnoosi"
    )
    entry_id: Identifier | None = None  # the clinical statement's own <id>
    encounter_id: str | None = None
    from_summary: bool = False  # taken from a Kooste document (fallback, D7)
    origin_document: str | None = None  # for summary items: the original document's id


@dataclass(slots=True)
class Condition:
    """A diagnosis (Kanta structure code 2)."""

    code: Coding  # ICD-10 (FI)
    source: SourceRef
    text: str | None = None
    recorded: str | None = None
    primary: bool | None = None  # PAA = main diagnosis, SIVU = secondary
    permanence: Coding | None = None  # 2.1: PYS permanent / KER temporary
    certainty: Coding | None = None  # 2.2
    reason_for_visit: bool | None = None  # 2.10
    episode_id: Identifier | None = None  # 2.14
    episode_name: str | None = None  # 2.15
    author: Author | None = None


@dataclass(slots=True)
class RiskItem:
    """Risk information (Kanta structure code 13): allergies, intolerances and other risks."""

    source: SourceRef
    code: Coding | None = None  # ICD-10 (FI)
    text: str | None = None
    date: str | None = None
    risk_id: Identifier | None = None  # 13.9
    severity: Coding | None = None  # 13.6
    risk_type: Coding | None = None  # 13.7, e.g. L9 other drug reaction
    certainty: Coding | None = None  # 2.2
    permanence: Coding | None = None  # 2.1
    agents: list[Coding] = field(default_factory=list)  # 13.2, e.g. ATC
    note: str | None = None  # 13.4
    author: Author | None = None


@dataclass(slots=True)
class Immunization:
    """A vaccination (Kanta structure code 19)."""

    source: SourceRef
    date: str | None = None
    status: str | None = None
    vaccine: Coding | None = None  # ATC
    product: Coding | None = None  # VNR product
    lot_number: str | None = None
    route: Coding | None = None
    site: Coding | None = None
    dose: Quantity | None = None
    dose_number: int | None = None
    target_diseases: list[Coding] = field(default_factory=list)  # 19.1
    immunization_id: Identifier | None = None  # 19.7
    author: Author | None = None


@dataclass(slots=True)
class Procedure:
    code: Coding  # THL procedure classification
    source: SourceRef
    text: str | None = None
    performed: Period | None = None
    primary: bool | None = None
    additional_codes: list[Coding] = field(default_factory=list)  # 3.7
    procedure_type: Coding | None = None  # 3.9
    body_sites: list[Coding] = field(default_factory=list)  # 3.3 teeth
    procedure_id: Identifier | None = None  # 3.8
    author: Author | None = None


@dataclass(slots=True)
class OrderedTest:
    code: Coding
    specimen: Coding | None = None
    note: str | None = None
    procedure_code: Coding | None = None  # 37 / imaging qualifiers
    qualifiers: list[Coding] = field(default_factory=list)
    reason_codes: list[Coding] = field(default_factory=list)


@dataclass(slots=True)
class Order:
    """A lab (organizer 27) or imaging (organizer 26) request."""

    category: str  # "laboratory" or "imaging"
    source: SourceRef
    order_id: Identifier | None = None
    date: str | None = None
    note: str | None = None
    repeat_period: Period | None = None
    repeat_count: int | None = None
    tests: list[OrderedTest] = field(default_factory=list)
    requester: Author | None = None


@dataclass(slots=True)
class LabResult:
    code: Coding  # Kuntaliitto lab nomenclature
    source: SourceRef
    local_codes: list[Coding] = field(default_factory=list)  # <translation>s
    status: Coding | None = None  # F final, …
    effective: str | None = None
    value: Value | None = None
    interpretation: Coding | None = None
    reference_ranges: list[ReferenceRange] = field(default_factory=list)
    specimen: Coding | None = None
    order_id: Identifier | None = None  # 21
    test_id: Identifier | None = None  # 30
    performer_name: str | None = None  # 28
    method: Coding | None = None  # 26
    issued: str | None = None  # 13
    notes: list[str] = field(default_factory=list)  # 23, 24
    procedure_code: Coding | None = None  # 37
    study_uid: Identifier | None = None  # 36
    statement: str | None = None  # 4
    statement_status: Coding | None = None  # 29
    author: Author | None = None


@dataclass(slots=True)
class VitalSign:
    """A physiological measurement (LOINC-coded, 1.2.246.537.6.96.2008)."""

    code: Coding
    source: SourceRef
    effective: str | None = None
    value: Quantity | None = None
    alternative_values: list[Quantity] = field(default_factory=list)
    measurement_id: Identifier | None = None  # 23.6
    method: Coding | None = None  # 23.1
    reference_ranges: list[ReferenceRange] = field(default_factory=list)
    abnormality: Coding | None = None  # 23.5
    notes: list[str] = field(default_factory=list)  # 23.3
    author: Author | None = None


@dataclass(slots=True)
class ImagingResult:
    """A performed imaging study (22.x) and/or its statement (24.x)."""

    code: Coding
    source: SourceRef
    qualifiers: list[Coding] = field(default_factory=list)  # side, anatomical region …
    effective: str | None = None
    study_uid: Identifier | None = None  # 22.2
    accession: Identifier | None = None  # 22.1
    performers: str | None = None  # 22.4
    diagnoses: list[Coding] = field(default_factory=list)  # 22.5
    procedure_refinements: list[Coding] = field(default_factory=list)  # 22.10
    interruption_reason: Coding | None = None  # 22.7
    radiation_dose: Quantity | None = None  # 22.8
    patient_weight: Quantity | None = None  # 22.9
    body_sites: list[Coding] = field(default_factory=list)  # 3.3 teeth
    order_id: Identifier | None = None  # 26.2
    statement: str | None = None  # 24.2
    statement_status: Coding | None = None  # 24.1
    assessment: Coding | None = None  # 24.3
    author: Author | None = None

    @property
    def has_statement(self) -> bool:
        return self.statement is not None or self.statement_status is not None


@dataclass(slots=True)
class GoalTarget:
    code: Coding
    range: Range | None = None
    note: str | None = None


@dataclass(slots=True)
class PlannedService:
    code: Coding
    start: str | None = None
    content: str | None = None
    note: str | None = None
    status: Coding | None = None
    status_date: str | None = None
    conditions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CareTeamMember:
    role: Coding  # 302 care unit / 501 professional
    organization: str | None = None
    profession: Coding | None = None
    note: str | None = None


@dataclass(slots=True)
class CarePlan:
    """Terveys- ja hoitosuunnitelma (health and care plan, view 345)."""

    source: SourceRef
    date: str | None = None
    needs: list[str] = field(default_factory=list)  # 101
    functional_needs: list[str] = field(default_factory=list)  # 102
    reasons: list[Coding] = field(default_factory=list)  # 111
    coordinators: list[str] = field(default_factory=list)  # 114, 117
    goals: list[str] = field(default_factory=list)  # 201
    functional_goals: list[str] = field(default_factory=list)  # 202
    goal_setters: list[str] = field(default_factory=list)  # 211
    targets: list[GoalTarget] = field(default_factory=list)  # 212-214
    means: list[str] = field(default_factory=list)  # 301
    care_team: list[CareTeamMember] = field(default_factory=list)  # 302, 501
    planned_services: list[PlannedService] = field(default_factory=list)
    diagnosis_list: str | None = None  # 603 (text only)
    medication_list: str | None = None  # 605 (text only)
    additional_info: str | None = None  # 601
    author: Author | None = None


@dataclass(frozen=True, slots=True)
class SectionNarrative:
    """A section's human-readable text, converted to FHIR XHTML."""

    source: SourceRef
    view: Coding | None
    title: str | None
    xhtml: str


@dataclass(slots=True)
class ClinicalData:
    """All clinical content of one patient, after consolidation."""

    conditions: list[Condition] = field(default_factory=list)
    risks: list[RiskItem] = field(default_factory=list)
    immunizations: list[Immunization] = field(default_factory=list)
    procedures: list[Procedure] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    lab_results: list[LabResult] = field(default_factory=list)
    vital_signs: list[VitalSign] = field(default_factory=list)
    imaging_results: list[ImagingResult] = field(default_factory=list)
    care_plans: list[CarePlan] = field(default_factory=list)
    narratives: list[SectionNarrative] = field(default_factory=list)
