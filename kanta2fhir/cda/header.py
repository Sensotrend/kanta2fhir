"""CDA header: document metadata, patient, authors, custodian, service event, local header."""

from __future__ import annotations

from dataclasses import dataclass

from kanta2fhir.cda.util import (
    Element,
    attr,
    coding,
    find,
    findall,
    human_name,
    identifier,
    organization,
    period,
    person,
    template_ids,
    text,
    ts_to_fhir,
)
from kanta2fhir.model import Author, Coding, Demographics, Identifier, Organization, Period


@dataclass(frozen=True, slots=True)
class EncounterHeader:
    """``componentOf/encompassingEncounter``: the service event the document belongs to."""

    identifier: Identifier | None
    period: Period | None
    responsible_organization: Organization | None
    participant_organizations: tuple[Organization, ...]


@dataclass(frozen=True, slots=True)
class LocalHeader:
    """Kanta's ``hl7fi:localHeader`` extension."""

    document_type: Coding | None  # 1 Kertomusteksti, 4 Palvelutapahtuma-asiakirja …
    function_code: Coding | None
    record_status: Coding | None
    encounter_type: Coding | None  # encompassingEncounterCode: outpatient/inpatient …
    encounter_master: Coding | None  # primary/secondary
    contents_codes: tuple[Coding, ...]  # tableOfContents: views in the document


@dataclass(frozen=True, slots=True)
class RelatedDocument:
    type_code: str  # RPLC, APND, XFRM
    identifier: Identifier | None
    set_id: Identifier | None
    version: int | None


@dataclass(frozen=True, slots=True)
class CdaHeader:
    document_id: Identifier | None
    set_id: Identifier | None
    version: int | None
    code: Coding | None
    title: str | None
    effective_time: str | None
    template_ids: tuple[str, ...]
    confidentiality: Coding | None
    language: str | None
    patient: Demographics
    authors: tuple[Author, ...]
    custodian: Organization | None
    encounter: EncounterHeader | None
    local: LocalHeader
    related_documents: tuple[RelatedDocument, ...]


def parse_header(root: Element) -> CdaHeader:
    version = attr(root, "value", "h:versionNumber")
    return CdaHeader(
        document_id=identifier(find(root, "h:id")),
        set_id=identifier(find(root, "h:setId")),
        version=int(version) if version and version.isdigit() else None,
        code=coding(find(root, "h:code")),
        title=text(root, "h:title"),
        effective_time=ts_to_fhir(attr(root, "value", "h:effectiveTime")),
        template_ids=template_ids(root),
        confidentiality=coding(find(root, "h:confidentialityCode")),
        language=attr(root, "code", "h:languageCode"),
        patient=_demographics(find(root, "h:recordTarget/h:patientRole/h:patient")),
        authors=tuple(author(a) for a in findall(root, "h:author")),
        custodian=organization(
            find(root, "h:custodian/h:assignedCustodian/h:representedCustodianOrganization")
        ),
        encounter=_encounter(find(root, "h:componentOf/h:encompassingEncounter")),
        local=_local_header(find(root, "fi:localHeader")),
        related_documents=tuple(_related(r) for r in findall(root, "h:relatedDocument")),
    )


def _demographics(patient: Element | None) -> Demographics:
    return Demographics(
        name=human_name(find(patient, "h:name")),
        gender=coding(find(patient, "h:administrativeGenderCode")),
        birth_date=ts_to_fhir(attr(patient, "value", "h:birthTime")),
    )


def author(el: Element) -> Author:
    """An ``author`` element (header or section/entry level)."""
    assigned = find(el, "h:assignedAuthor")
    return Author(
        function=coding(find(el, "h:functionCode")),
        time=ts_to_fhir(attr(el, "value", "h:time")),
        person=person(assigned),
        organization=organization(find(assigned, "h:representedOrganization")),
    )


def _encounter(el: Element | None) -> EncounterHeader | None:
    if el is None:
        return None
    participants = tuple(
        org
        for p in findall(el, "h:encounterParticipant")
        if (org := organization(find(p, "h:assignedEntity/h:representedOrganization")))
    )
    return EncounterHeader(
        identifier=identifier(find(el, "h:id")),
        period=period(find(el, "h:effectiveTime")),
        responsible_organization=organization(
            find(el, "h:responsibleParty/h:assignedEntity/h:representedOrganization")
        ),
        participant_organizations=participants,
    )


def _local_header(el: Element | None) -> LocalHeader:
    return LocalHeader(
        document_type=coding(find(el, "fi:documentType")),
        function_code=coding(find(el, "fi:functionCode")),
        record_status=coding(find(el, "fi:recordStatus")),
        encounter_type=coding(find(el, "fi:encompassingEncounterCode")),
        encounter_master=coding(find(el, "fi:encompassingEncounterMasterCode")),
        contents_codes=tuple(
            c for el_ in findall(el, "fi:tableOfContents/fi:contentsCode") if (c := coding(el_))
        ),
    )


def _related(el: Element) -> RelatedDocument:
    parent = find(el, "h:parentDocument")
    version = attr(parent, "value", "h:versionNumber")
    return RelatedDocument(
        type_code=el.get("typeCode", ""),
        identifier=identifier(find(parent, "h:id")),
        set_id=identifier(find(parent, "h:setId")),
        version=int(version) if version and version.isdigit() else None,
    )
