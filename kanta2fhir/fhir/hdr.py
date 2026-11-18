"""European Hospital Discharge Report (hl7.fhir.eu.hdr 1.0.0): one document per inpatient stay.

An inpatient stay is a service event whose Kanta encounter type (Palvelutapahtuman laji) is
1, Osastohoitojakso. Its content is everything recorded in the documents
of that service event:
- structured entries → Diagnostic summary, Significant procedures, Significant results,
  Vital signs (and the patient's allergies and alerts);
- section narratives → by their Kanta heading: 21 Hoidon tarve → Admission evaluation,
  62 Lausunto → Discharge summary, 55 Lääkehoito → Discharge medications, 75 Suunnitelma →
  Plan of care, other care-delivery (phase 15) narratives → Hospital course.
"""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from kanta2fhir.fhir import narrative as n
from kanta2fhir.fhir.bundle import document_bundle
from kanta2fhir.fhir.datatypes import JSON, compact, fixed_concept, full_url, resource_id
from kanta2fhir.fhir.eps import (
    VITAL_SIGN_CODES,
    PatientSummaryBuilder,
    is_allergy,
)
from kanta2fhir.fhir.profiles import EU_CORE
from kanta2fhir.fhir.resources import ResourceSet, document_identifier
from kanta2fhir.model import ClinicalData, Encounter, SectionNarrative
from kanta2fhir.pipeline import PatientResult
from kanta2fhir.record import instant
from kanta2fhir.terminology import Terminology

HDR = "http://hl7.eu/fhir/hdr/StructureDefinition"
PROFILES = {
    **EU_CORE,
    "Bundle": f"{HDR}/bundle-eu-hdr",
    "Composition": f"{HDR}/composition-eu-hdr",
    "Encounter": f"{HDR}/encounter-eu-hdr",
    "Condition": "http://hl7.eu/fhir/base/StructureDefinition/condition-eu-core",
    "Procedure": "http://hl7.eu/fhir/base/StructureDefinition/procedure-eu-core",
    "AllergyIntolerance": "http://hl7.eu/fhir/base/StructureDefinition/allergyIntolerance-eu-core",
    "Flag": "http://hl7.eu/fhir/base/StructureDefinition/flag-patient-eu-core",
    "Immunization": "http://hl7.eu/fhir/base/StructureDefinition/immunization-eu-core",
}

LOINC = "http://loinc.org"
DIAGNOSIS_ROLE = "http://terminology.hl7.org/CodeSystem/diagnosis-role"
INPATIENT = "1"  # Palvelutapahtuman laji 1 = Osastohoitojakso (inpatient period)

# Kanta heading codes (1.2.246.537.6.14.2006) whose narrative goes to a specific section
HEADING_SECTIONS = {
    "21": "sectionAdmissionEvaluation",  # Hoidon tarve
    "62": "sectionDischargeSummary",  # Lausunto
    "55": "sectionDischargeMedications",  # Lääkehoito
    "75": "sectionPlanOfCare",  # Suunnitelma
}
STRUCTURED_HEADINGS = {"13", "51", "53", "64"}  # shown from structured entries instead
CARE_DELIVERY_PHASE = "15"  # Hoidon toteutus


@dataclass(frozen=True, slots=True)
class HdrSection:
    slice: str
    code: str
    display: str  # LOINC display as served by tx.fhir.org
    title: str


# In the order of the HDR Composition profile.
SECTIONS = [
    HdrSection("sectionAlert", "104605-1", "Alert", "Riskitiedot ja varoitukset"),
    HdrSection("sectionAdmissionEvaluation", "67851-6", "Admission Evaluation Note",
               "Tulotilanne"),
    HdrSection("sectionVitalSigns", "8716-3", "Vital signs note", "Fysiologiset mittaukset"),
    HdrSection("sectionDischargeSummary", "18842-5", "Discharge Summary", "Loppulausunto"),
    HdrSection("sectionHospitalCourse", "8648-8", "Hospital course note", "Hoidon kulku"),
    HdrSection("sectionDiagnosticSummary", "11535-2", "Hospital discharge diagnosis note",
               "Diagnoosit"),
    HdrSection("sectionSignificantProcedures", "10185-7", "Hospital discharge procedure note",
               "Toimenpiteet"),
    HdrSection("sectionSignificantResults", "30954-2",
               "Relevant diagnostic tests/laboratory data note", "Tutkimustulokset"),
    HdrSection("sectionPlanOfCare", "18776-5", "Plan of Care Note", "Jatkohoitosuunnitelma"),
    HdrSection("sectionDischargeMedications", "75311-1", "Discharge medications note",
               "Lääkitys kotiutuessa"),
    HdrSection("sectionAllergies", "48765-2", "Allergies and adverse reactions Document",
               "Allergiat ja intoleranssit"),
]  # fmt: skip


def inpatient_stays(patient: PatientResult) -> list[Encounter]:
    stays = [
        e
        for e in patient.record.encounters.values()
        if e.encounter_type is not None and e.encounter_type.code == INPATIENT
    ]
    return sorted(stays, key=lambda e: instant(e.period.start if e.period else None))


def _inner(xhtml: str) -> str:
    """The children of a narrative ``<div>``, serialised (to merge several narratives)."""
    div = etree.fromstring(xhtml)
    out = div.text or ""
    for child in div:
        out += etree.tostring(child, encoding="unicode")
    return out


class DischargeReportBuilder:
    def __init__(self, terminology: Terminology, generated_at: str) -> None:
        self.t = terminology
        self.generated_at = generated_at

    def build(self, patient: PatientResult, stay: Encounter) -> JSON:
        rs = ResourceSet(self.t, profiles=PROFILES)
        # Entry factories are shared with the Patient Summary builder.
        entries = PatientSummaryBuilder(self.t, self.generated_at)
        entries.rs = rs
        subject = entries.subject = rs.patient(patient.record.patient)

        docs = {stay.service_event_document, *stay.documents} - {None}
        c = _stay_data(patient.clinical, docs, stay.identifier.key)
        record_entries = [d for d in patient.record.documents if d.id in stay.documents]
        latest = max(record_entries, key=lambda d: instant(d.header.effective_time), default=None)

        encounter_ref = rs.encounter(stay, subject)
        # The diagnoses of the stay were all treated during it, so they are active here.
        conditions = [entries._condition(x, active=True) for x in c.conditions]
        self._add_diagnoses(rs, encounter_ref, c, conditions)

        narratives = _route_narratives(c.narratives)
        content: dict[str, tuple[list[JSON], str]] = {}
        allergies = [r for r in patient.clinical.risks if is_allergy(r)]
        alerts = [r for r in patient.clinical.risks if not is_allergy(r)]
        if alerts:
            content["sectionAlert"] = entries._alerts(alerts)
        if allergies:
            content["sectionAllergies"] = entries._allergies(allergies)
        vitals = [v for v in c.vital_signs if v.code.code in VITAL_SIGN_CODES]
        if vitals:
            content["sectionVitalSigns"] = entries._vital_signs(vitals)
        if c.conditions:
            _, table = entries._conditions(c.conditions, active=True)
            content["sectionDiagnosticSummary"] = (conditions, table)
        if c.procedures:
            content["sectionSignificantProcedures"] = entries._procedures(c.procedures)
        others = [v for v in c.vital_signs if v.code.code not in VITAL_SIGN_CODES]
        if c.lab_results or c.imaging_results or others:
            content["sectionSignificantResults"] = entries._results(
                c.lab_results, c.imaging_results, others
            )
        for slice_name, texts in narratives.items():
            refs, text = content.get(slice_name, ([], ""))
            content[slice_name] = (refs, text + "".join(texts))
        hospital_course = n.para(_stay_text(stay))
        refs, text = content.get("sectionHospitalCourse", ([], ""))
        content["sectionHospitalCourse"] = (refs, hospital_course + text)

        sections = []
        for sd in SECTIONS:
            if sd.slice not in content:
                continue
            refs, text = content[sd.slice]
            section = compact(
                {
                    "title": sd.title,
                    "code": fixed_concept(LOINC, sd.code, sd.display),
                    "text": n.generated(text or n.para("Ei tietoja.")),
                    "entry": refs,
                }
            )
            sections.append(section)

        key = stay.identifier.key
        composition_id = resource_id("Composition", "hdr", key)
        header = latest.header if latest else None
        author = rs.author(header.authors[0] if header and header.authors else None)
        custodian = rs.organization(header.custodian if header else stay.service_provider)
        date = (header.effective_time if header else None) or self.generated_at
        composition = compact(
            {
                "resourceType": "Composition",
                "id": composition_id,
                "meta": {"profile": [PROFILES["Composition"]]},
                "language": "fi",
                "text": n.generated(
                    n.para("Hoitojakson loppuyhteenveto"), n.para(_stay_text(stay)), lang="fi"
                ),
                "identifier": document_identifier(latest.id)
                if latest
                else {"system": "urn:ietf:rfc:3986", "value": full_url(composition_id)},
                "status": "final",
                "type": fixed_concept(LOINC, "34105-7", "Hospital Discharge Summary"),
                "subject": subject,
                "encounter": encounter_ref,
                "date": date,
                "author": [author or custodian or rs.converter_device()],
                "title": "Hoitojakson loppuyhteenveto",
                "custodian": custodian,
                "section": sections,
            }
        )
        rs.provenance([{"reference": full_url(composition_id)}], docs, self.generated_at)
        bundle = document_bundle(
            f"hdr|{key}", self.generated_at, composition, rs.entries(), PROFILES["Bundle"]
        )
        return bundle

    def _add_diagnoses(
        self, rs: ResourceSet, encounter_ref: JSON, c: ClinicalData, refs: list[JSON]
    ) -> None:
        """Encounter.diagnosis: the stay's diagnoses as discharge diagnoses (main = rank 1)."""
        encounter = rs.resources[encounter_ref["reference"]]
        diagnoses = []
        for cond, ref in zip(c.conditions, refs, strict=True):
            diagnoses.append(
                compact(
                    {
                        "condition": ref,
                        "use": fixed_concept(DIAGNOSIS_ROLE, "DD", "Discharge diagnosis"),
                        "rank": 1 if cond.primary else None,
                    }
                )
            )
        if diagnoses:
            encounter["diagnosis"] = diagnoses


def _stay_data(clinical: ClinicalData, docs: set[str], encounter_key: str) -> ClinicalData:
    """The part of the patient's clinical data recorded in the documents of one stay."""

    def in_stay(item: object) -> bool:
        source = item.source  # type: ignore[attr-defined]
        doc = source.origin_document if source.from_summary else source.document_id
        return doc in docs or source.encounter_id == encounter_key

    return ClinicalData(
        conditions=[x for x in clinical.conditions if in_stay(x)],
        risks=[x for x in clinical.risks if in_stay(x)],
        immunizations=[x for x in clinical.immunizations if in_stay(x)],
        procedures=[x for x in clinical.procedures if in_stay(x)],
        orders=[x for x in clinical.orders if in_stay(x)],
        lab_results=[x for x in clinical.lab_results if in_stay(x)],
        vital_signs=[x for x in clinical.vital_signs if in_stay(x)],
        imaging_results=[x for x in clinical.imaging_results if in_stay(x)],
        care_plans=[x for x in clinical.care_plans if in_stay(x)],
        narratives=[x for x in clinical.narratives if in_stay(x)],
    )


def _route_narratives(narratives: list[SectionNarrative]) -> dict[str, list[str]]:
    """Section narratives → HDR sections, by Kanta heading code (see module docstring)."""
    out: dict[str, list[str]] = {}
    for nar in narratives:
        if len(nar.codes) < 3:  # view/phase level: signatures, dates
            continue
        heading = nar.codes[-1]
        if heading in STRUCTURED_HEADINGS:
            continue
        target = HEADING_SECTIONS.get(heading)
        if target is None and nar.codes[1] == CARE_DELIVERY_PHASE:
            target = "sectionHospitalCourse"
        if target is None:
            continue
        out.setdefault(target, []).append(_inner(nar.xhtml))
    return out


def _stay_text(stay: Encounter) -> str:
    start = stay.period.start[:10] if stay.period and stay.period.start else "?"
    end = stay.period.end[:10] if stay.period and stay.period.end else "?"
    where = stay.service_provider.name if stay.service_provider else None
    return f"Osastohoitojakso {start} - {end}" + (f", {where}" if where else "")


def build_discharge_reports(
    patient: PatientResult, terminology: Terminology, generated_at: str
) -> list[tuple[str, JSON]]:
    builder = DischargeReportBuilder(terminology, generated_at)
    return [
        (stay.identifier.key.replace("/", "_"), builder.build(patient, stay))
        for stay in inpatient_stays(patient)
    ]
