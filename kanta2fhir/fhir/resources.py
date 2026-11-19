"""Shared resource factories: Patient, Organization, Practitioner(Role), Encounter, Provenance.

A ``ResourceSet`` collects the resources of one FHIR document. Each factory returns a
Reference; resources with the same id are added once, so the same organisation or author
mentioned by many entries appears in the document only once.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from kanta2fhir import __version__
from kanta2fhir.fhir import narrative as n
from kanta2fhir.fhir.datatypes import (
    HETU_SYSTEM,
    JSON,
    codeable_concept,
    compact,
    full_url,
    human_names,
    identifier,
    name_text,
    period,
    resource_id,
)
from kanta2fhir.model import Author, Encounter, Identifier, Organization, Patient, Person
from kanta2fhir.terminology import Terminology

V3_ACT_CODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
PARTICIPANT_TYPE = "http://terminology.hl7.org/CodeSystem/provenance-participant-type"

# hl7fi:encompassingEncounterCode, eArkisto - Palvelutapahtuman laji (1.2.246.537.5.40156.2008):
# 1 Osastohoitojakso (inpatient period), 2 Avohoitokäyntitieto (outpatient visit).
ENCOUNTER_CLASS = {
    "1": ("IMP", "inpatient encounter"),
    "2": ("AMB", "ambulatory"),
}


@dataclass(slots=True)
class ResourceSet:
    terminology: Terminology
    profiles: dict[str, str] = field(default_factory=dict)  # resourceType → profile URL
    resources: dict[str, JSON] = field(default_factory=dict)  # fullUrl → resource

    def add(self, resource: JSON) -> JSON:
        """Add a resource (once) and return a Reference to it."""
        url = full_url(resource["id"])
        if url not in self.resources:
            profile = self.profiles.get(resource["resourceType"])
            if profile:
                resource = {
                    "resourceType": resource["resourceType"],
                    "id": resource["id"],
                    "meta": {"profile": [profile]},
                    **{k: v for k, v in resource.items() if k not in ("resourceType", "id")},
                }
            self.resources[url] = resource
        return {"reference": url}

    def entries(self) -> list[tuple[str, JSON]]:
        return list(self.resources.items())

    # --- Patient -------------------------------------------------------------------------

    def patient(self, p: Patient) -> JSON:
        names = human_names(p.name)
        return self.add(
            compact(
                {
                    "resourceType": "Patient",
                    "id": resource_id("Patient", p.pseudonym),
                    "text": n.generated(
                        n.para(name_text(p.name)),
                        n.para(f"Henkilötunnus {p.hetu}"),
                        n.para(p.birth_date),
                    ),
                    "identifier": [{"system": HETU_SYSTEM, "value": p.hetu}],
                    "name": names,
                    "gender": self.terminology.gender(p.gender),
                    "birthDate": p.birth_date[:10] if p.birth_date else None,
                }
            )
        )

    # --- Organization, Practitioner, PractitionerRole -------------------------------------

    def organization(self, org: Organization | None) -> JSON | None:
        if org is None:
            return None
        key = org.identifier.key if org.identifier else f"name:{org.name}"
        return self.add(
            compact(
                {
                    "resourceType": "Organization",
                    "id": resource_id("Organization", key),
                    "text": n.generated(n.para(org.name or key)),
                    "identifier": [i] if (i := identifier(org.identifier)) else [],
                    "name": org.name,
                }
            )
        )

    def practitioner(self, person: Person | None, org: Organization | None = None) -> JSON | None:
        if person is None or person.name is None:
            return None
        # Kanta masks professionals' identity codes, so the name (within the organisation)
        # is the only identity available.
        org_key = org.identifier.key if org and org.identifier else (org.name if org else "")
        name = name_text(person.name) or ""
        return self.add(
            compact(
                {
                    "resourceType": "Practitioner",
                    "id": resource_id("Practitioner", name, org_key or ""),
                    "text": n.generated(n.para(name)),
                    "identifier": [i] if (i := identifier(person.identifier)) else [],
                    "name": human_names(person.name),
                }
            )
        )

    def author(self, a: Author | None) -> JSON | None:
        """A reference for an author: PractitionerRole (person + organisation), or either."""
        if a is None:
            return None
        practitioner = self.practitioner(a.person, a.organization)
        organization = self.organization(a.organization)
        if practitioner and organization:
            return self.add(
                {
                    "resourceType": "PractitionerRole",
                    "id": resource_id(
                        "PractitionerRole", practitioner["reference"], organization["reference"]
                    ),
                    "text": n.generated(
                        n.para(name_text(a.person.name) if a.person else None),
                        n.para(a.organization.name if a.organization else None),
                    ),
                    "practitioner": practitioner,
                    "organization": organization,
                }
            )
        return practitioner or organization

    # --- Encounter -------------------------------------------------------------------------

    def encounter(self, enc: Encounter, patient: JSON) -> JSON:
        type_code = enc.encounter_type.code if enc.encounter_type else None
        class_code, class_display = ENCOUNTER_CLASS.get(type_code or "", ("AMB", "ambulatory"))
        enc_type = codeable_concept(enc.encounter_type, self.terminology)
        status = "finished" if enc.period and enc.period.end else "unknown"
        return self.add(
            compact(
                {
                    "resourceType": "Encounter",
                    "id": resource_id("Encounter", enc.identifier.key),
                    "text": n.generated(
                        n.para(enc.encounter_type.display if enc.encounter_type else class_display),
                        n.para(_period_text(enc)),
                        n.para(enc.service_provider.name if enc.service_provider else None),
                    ),
                    "identifier": [i] if (i := identifier(enc.identifier)) else [],
                    "status": status,
                    "class": {"system": V3_ACT_CODE, "code": class_code, "display": class_display},
                    "type": [enc_type] if enc_type else [],
                    "subject": patient,
                    "period": period(enc.period),
                    "serviceProvider": self.organization(enc.service_provider),
                }
            )
        )

    # --- Provenance ------------------------------------------------------------------------

    def converter_device(self) -> JSON:
        return self.add(
            {
                "resourceType": "Device",
                "id": resource_id("Device", "kanta2fhir"),
                "text": n.generated(n.para(f"kanta2fhir {__version__}")),
                "deviceName": [{"name": "kanta2fhir", "type": "manufacturer-name"}],
                "version": [{"value": __version__}],
            }
        )

    def derived_resources(self) -> list[JSON]:
        """References to everything in the set that was converted from Kanta documents (not the
        converter Device, not Provenance). Used as Provenance.target.

        The Composition is deliberately not a target: the IG Publisher renders no anchor for a
        document bundle's first entry, so a Provenance → Composition reference becomes a broken
        link in the published pages, and the derived resources say more anyway.
        """
        return [
            {"reference": url}
            for url, r in self.resources.items()
            if r["resourceType"] not in ("Device", "Provenance")
        ]

    def provenance(
        self, targets: Iterable[JSON], source_documents: Iterable[str], recorded: str
    ) -> JSON:
        """Provenance: the targets were converted from these Kanta CDA documents."""
        targets = list(targets)
        docs = sorted(set(source_documents))
        return self.add(
            {
                "resourceType": "Provenance",
                "id": resource_id("Provenance", *[t["reference"] for t in targets]),
                "text": n.generated(
                    n.para(
                        f"Converted by kanta2fhir {__version__} from {len(docs)} Kanta document(s)"
                    )
                ),
                "target": targets,
                "recorded": recorded,
                "agent": [
                    {
                        "type": {"coding": [{"system": PARTICIPANT_TYPE, "code": "assembler"}]},
                        "who": self.converter_device(),
                    }
                ],
                "entity": [
                    {
                        "role": "source",
                        "what": {
                            "type": "DocumentReference",
                            "identifier": document_identifier(doc),
                        },
                    }
                    for doc in docs
                ],
            }
        )


def document_identifier(doc_id: str) -> JSON:
    """A Kanta document id (``root`` or ``root/extension``) as a FHIR Identifier."""
    root, _, ext = doc_id.partition("/")
    return identifier(Identifier(system=root, value=ext or None)) or {"value": doc_id}


def _period_text(enc: Encounter) -> str | None:
    if enc.period is None:
        return None
    return " - ".join(x for x in (enc.period.start, enc.period.end) if x) or None
