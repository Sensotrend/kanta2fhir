"""European Patient Summary (hl7.fhir.eu.eps 1.0.0-ballot): one document per patient.

Sections follow the order of the EPS Composition profile (D6). Required sections without data
get an ``emptyReason``. Active problems go to the Problems section and all other diagnoses to
an IPS Past Problems section (11348-0), placed at its IPS position (D12).
"""

from __future__ import annotations

from dataclasses import dataclass

from kanta2fhir.fhir import narrative as n
from kanta2fhir.fhir.bundle import document_bundle
from kanta2fhir.fhir.datatypes import (
    JSON,
    codeable_concept,
    codeable_concepts,
    compact,
    fixed_concept,
    full_url,
    identifier,
    period,
    quantity,
    range_,
    reference_range,
    resource_id,
)
from kanta2fhir.fhir.lab import LabReportBuilder, results_table
from kanta2fhir.fhir.profiles import EU_BASE
from kanta2fhir.fhir.resources import ResourceSet
from kanta2fhir.model import (
    CarePlan,
    Coding,
    Condition,
    Identifier,
    ImagingResult,
    Immunization,
    LabResult,
    Organization,
    Procedure,
    RiskItem,
    SourceRef,
    VitalSign,
)
from kanta2fhir.pipeline import PatientResult
from kanta2fhir.terminology import Terminology

EPS = "http://hl7.eu/fhir/eps/StructureDefinition"
PROFILES = {
    "Bundle": f"{EPS}/bundle-eu-eps",
    "Composition": f"{EPS}/composition-eu-eps",
    "Patient": f"{EPS}/patient-eu-eps",
    "Organization": f"{EPS}/organization-obl-eu-eps",
    "Practitioner": f"{EPS}/practitioner-obl-eu-eps",
    "PractitionerRole": f"{EPS}/practitionerrole-obl-eu-eps",
    "Condition": f"{EPS}/condition-obl-eu-eps",
    "AllergyIntolerance": f"{EPS}/allergyintolerance-obl-eu-eps",
    "Immunization": f"{EPS}/immunization-obl-eu-eps",
    "Flag": f"{EPS}/flag-alert-obl-eu-eps",
    "Procedure": f"{EPS}/procedure-eu-eps",
}
MEDICAL_TEST_RESULT = f"{EU_BASE}/medicalTestResult-eu-core"
VITAL_SIGNS = "http://hl7.org/fhir/StructureDefinition/vitalsigns"

LOINC = "http://loinc.org"
OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
CONDITION_CLINICAL = "http://terminology.hl7.org/CodeSystem/condition-clinical"
CONDITION_VERIFICATION = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
CONDITION_CATEGORY = "http://terminology.hl7.org/CodeSystem/condition-category"
ALLERGY_CLINICAL = "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical"
ALLERGY_VERIFICATION = "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification"
LIST_EMPTY_REASON = "http://terminology.hl7.org/CodeSystem/list-empty-reason"
PERFORMER_FUNCTION = "http://terminology.hl7.org/CodeSystem/v2-0443"

# Kanta code values used in the mapping rules
PERMANENT = "PYS"  # 2.1 Pysyväisluonteinen
# Code lists from THL Koodistopalvelu, see kanta2fhir/terminology/data/kanta_codes.md
CERTAIN = {"TOD", "VAR"}  # Varmuusaste: Todennäköinen tai varma, Varma (EP = epäilty)
RISK_CRITICALITY = {"1": "high", "2": "low"}  # Riskitiedon aste: kriittinen, huomioitava
# Riskitiedon tyyppi: A Muut allergiat, L Lääkereaktiot ja -allergiat (+ child codes such as
# L9), and the deprecated top-level codes ALLERG (Allergia) and LAAKRE (Lääkereaktio).
ALLERGY_RISK_TYPE_PREFIXES = ("A", "L")
ALLERGY_RISK_TYPES = {"ALLERG", "LAAKRE"}

# The core vital-signs profiles require a "magic" LOINC code; more specific codes from Kanta
# get it as an additional coding (e.g. measured body weight 3141-9 → body weight 29463-7).
VITAL_SIGN_PARENT = {"3141-9": ("29463-7", "Body weight"), "3142-7": ("29463-7", "Body weight")}

# LOINC codes that the core vitalsigns profile accepts (vital-signs section); other
# physiological measurements go to the Results section.
VITAL_SIGN_CODES = {
    "85353-1", "9279-1", "8867-4", "2708-6", "59408-5", "8310-5", "8302-2", "9843-4",
    "29463-7", "3141-9", "39156-5", "85354-9", "8480-6", "8462-4", "8478-0",
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class SectionDef:
    slice: str
    code: str
    display: str  # LOINC display
    title: str  # Finnish title
    required: bool = False


# In the order of the EPS Composition profile; Past Problems at its IPS position (D12).
# Displays are the LOINC displays as served by tx.fhir.org (checked 2026-11-18).
SECTIONS = [
    SectionDef("sectionProblems", "11450-4", "Problem list - Reported", "Aktiiviset ongelmat",
               True),
    SectionDef("sectionAllergies", "48765-2", "Allergies and adverse reactions Document",
               "Allergiat ja intoleranssit", True),
    SectionDef("sectionMedications", "10160-0", "History of Medication use Narrative", "Lääkitys",
               True),
    SectionDef("sectionImmunizations", "11369-6", "History of Immunization note",
               "Rokotukset"),
    SectionDef("sectionResults", "30954-2", "Relevant diagnostic tests/laboratory data note",
               "Tutkimustulokset"),
    SectionDef("sectionProceduresHx", "47519-4", "History of Procedures Document", "Toimenpiteet",
               True),
    SectionDef("sectionMedicalDevices", "46264-8", "History of medical device use",
               "Lääkinnälliset laitteet", True),
    SectionDef("sectionAdvanceDirectives", "42348-3", "Advance Healthcare Directives",
               "Hoitotahto"),
    SectionDef("sectionAlert", "104605-1", "Alert", "Riskitiedot ja varoitukset"),
    SectionDef("sectionFunctionalStatus", "47420-5", "Functional Status Assessment Note",
               "Toimintakyky"),
    SectionDef("sectionPastProblems", "11348-0", "History of Past illness note",
               "Aiemmat ongelmat"),
    SectionDef("sectionPregnancyHx", "10162-6", "History of pregnancies Narrative", "Raskaudet"),
    SectionDef("sectionPatientStory", "81338-6", "Patient Goals, Preferences, and Priorities for "
               "Care Experience", "Potilaan kertomus"),
    SectionDef("sectionPlanOfCare", "18776-5", "Plan of Care Note", "Hoitosuunnitelma"),
    SectionDef("sectionSocialHistory", "29762-2", "Social history note", "Sosiaalinen tausta"),
    SectionDef("sectionVitalSigns", "8716-3", "Vital signs note", "Fysiologiset mittaukset"),
    SectionDef("sectionTravelHx", "10182-4", "History of Travel note", "Matkustushistoria"),
    SectionDef("sectionPatientHx", "11329-0", "History general Narrative - Reported", "Esitiedot"),
]  # fmt: skip


def is_active(c: Condition) -> bool:
    """Active problem rule (D6, may be revisited): permanent (PYS) diagnoses are active."""
    return c.permanence is not None and c.permanence.code == PERMANENT


def is_allergy(r: RiskItem) -> bool:
    """Allergy/intolerance rule: a risk with a causative agent, or of an allergy or
    drug-reaction risk type. Other risks (infections, implants, care limitations …) are alerts."""
    if r.agents:
        return True
    if r.risk_type is None:
        return False
    code = r.risk_type.code.upper()
    if code in ALLERGY_RISK_TYPES:
        return True
    # Hierarchical codes: "L", "L9", "A2" … but not the other deprecated words (LAAVAI is
    # "Lääkitykseen vaikuttavat asiat", things affecting medication: an alert).
    return code[:1] in ALLERGY_RISK_TYPE_PREFIXES and (len(code) == 1 or code[1:].isdigit())


class PatientSummaryBuilder:
    def __init__(self, terminology: Terminology, generated_at: str) -> None:
        self.t = terminology
        self.generated_at = generated_at
        self.lab = LabReportBuilder(terminology, generated_at)

    def build(self, patient: PatientResult) -> JSON:
        rs = ResourceSet(self.t, profiles=PROFILES)
        self.rs = rs
        self.subject = rs.patient(patient.record.patient)
        c = patient.clinical

        conditions = c.conditions
        active = [x for x in conditions if is_active(x)]
        past = [x for x in conditions if not is_active(x)]
        allergies = [r for r in c.risks if is_allergy(r)]
        alerts = [r for r in c.risks if not is_allergy(r)]
        vitals = [v for v in c.vital_signs if v.code.code in VITAL_SIGN_CODES]
        other_measurements = [v for v in c.vital_signs if v.code.code not in VITAL_SIGN_CODES]
        medication_texts = [p.medication_list for p in c.care_plans if p.medication_list]

        content: dict[str, tuple[list[JSON], str]] = {
            "sectionProblems": self._conditions(active, active=True),
            "sectionAllergies": self._allergies(allergies),
            "sectionMedications": ([], self._medication_text(medication_texts)),
            "sectionImmunizations": self._immunizations(c.immunizations),
            "sectionResults": self._results(c.lab_results, c.imaging_results, other_measurements),
            "sectionProceduresHx": self._procedures(c.procedures),
            "sectionMedicalDevices": ([], n.para("Ei tietoa lääkinnällisistä laitteista.")),
            "sectionAlert": self._alerts(alerts),
            "sectionPastProblems": self._conditions(past, active=False),
            "sectionPlanOfCare": self._care_plans(c.care_plans),
            "sectionVitalSigns": self._vital_signs(vitals),
        }

        sections = []
        for sd in SECTIONS:
            if sd.slice not in content:
                continue
            entries, text = content[sd.slice]
            if not entries and not sd.required:
                continue
            section = {
                "title": sd.title,
                "code": fixed_concept(LOINC, sd.code, sd.display),
                "text": n.generated(text or n.para("Ei tietoja.")),
            }
            if entries:
                section["entry"] = entries
            else:
                section["emptyReason"] = fixed_concept(
                    LIST_EMPTY_REASON, "unavailable", "Unavailable"
                )
            sections.append(section)

        pseudonym = patient.record.patient.pseudonym
        composition_id = resource_id("Composition", "eps", pseudonym)
        author = rs.converter_device()
        composition = {
            "resourceType": "Composition",
            "id": composition_id,
            "meta": {"profile": [PROFILES["Composition"]]},
            "language": "fi",
            "text": n.generated(
                n.para("Potilasyhteenveto"),
                n.para(f"Koottu Kanta-palvelun asiakirjoista {self.generated_at[:10]}"),
                lang="fi",
            ),
            "identifier": {"system": "urn:ietf:rfc:3986", "value": full_url(composition_id)},
            "status": "final",
            "type": fixed_concept(LOINC, "60591-5", "Patient summary Document"),
            "subject": self.subject,
            "date": self.generated_at,
            "author": [author],
            "title": "Potilasyhteenveto",
            "section": sections,
        }
        sources = [d.id for d in patient.record.current_documents()]
        rs.provenance([{"reference": full_url(composition_id)}], sources, self.generated_at)
        return document_bundle(
            f"eps|{pseudonym}", self.generated_at, composition, rs.entries(), PROFILES["Bundle"]
        )

    # --- sections --------------------------------------------------------------------------

    def _conditions(self, conditions: list[Condition], active: bool) -> tuple[list[JSON], str]:
        refs = [self._condition(c, active) for c in conditions]
        rows = [
            [
                c.code.display or c.text,
                c.code.code,
                c.permanence.display if c.permanence else None,
                c.certainty.display if c.certainty else None,
                c.recorded,
            ]
            for c in conditions
        ]
        return refs, n.table(["Diagnoosi", "Koodi", "Pysyvyys", "Varmuus", "Pvm"], rows)

    def _condition(self, c: Condition, active: bool) -> JSON:
        certain = c.certainty is None or c.certainty.code in CERTAIN
        category = "problem-list-item"
        return self.rs.add(
            compact(
                {
                    "resourceType": "Condition",
                    "id": resource_id("Condition", *_key(c.source, c.episode_id, c.code.code)),
                    "text": n.generated(n.para(f"{c.code.code} {c.code.display or c.text or ''}")),
                    "clinicalStatus": fixed_concept(
                        CONDITION_CLINICAL, "active" if active else "inactive"
                    ),
                    "verificationStatus": fixed_concept(
                        CONDITION_VERIFICATION, "confirmed" if certain else "provisional"
                    ),
                    "category": [fixed_concept(CONDITION_CATEGORY, category)],
                    "code": codeable_concept(c.code, self.t, text=c.text),
                    "subject": self.subject,
                    "recordedDate": c.recorded,
                    "asserter": self.rs.author(c.author),
                    "note": [{"text": c.episode_name}]
                    if c.episode_name and c.episode_name != c.text
                    else [],
                }
            )
        )

    def _allergies(self, risks: list[RiskItem]) -> tuple[list[JSON], str]:
        refs = []
        for r in risks:
            substance = (
                codeable_concepts(r.agents, self.t) or [{"text": r.text or "Tuntematon aine"}]
            )[0]
            reaction = compact(
                {
                    "manifestation": [codeable_concept(r.code, self.t, text=r.text)]
                    if (r.code or r.text)
                    else [],
                    "description": r.text,
                }
            )
            criticality = RISK_CRITICALITY.get(r.severity.code) if r.severity else None
            certain = r.certainty is None or r.certainty.code in CERTAIN
            refs.append(
                self.rs.add(
                    compact(
                        {
                            "resourceType": "AllergyIntolerance",
                            "id": resource_id("AllergyIntolerance", *_key(r.source, r.risk_id)),
                            "text": n.generated(n.para(_risk_text(r))),
                            "clinicalStatus": fixed_concept(ALLERGY_CLINICAL, "active"),
                            "verificationStatus": fixed_concept(
                                ALLERGY_VERIFICATION, "confirmed" if certain else "unconfirmed"
                            ),
                            "category": ["medication"] if r.agents else [],
                            "criticality": criticality,
                            "code": substance,
                            "patient": self.subject,
                            "recordedDate": r.date,
                            "recorder": self.rs.author(r.author),
                            "reaction": [reaction] if reaction.get("manifestation") else [],
                            "note": [{"text": r.note}] if r.note else [],
                        }
                    )
                )
            )
        rows = [
            [
                ", ".join(a.display or a.code for a in r.agents) or None,
                r.text or (r.code.display if r.code else None),
                r.severity.display if r.severity else None,
                r.note,
                r.date,
            ]
            for r in risks
        ]
        return refs, n.table(["Aine", "Reaktio", "Vakavuus", "Huomio", "Pvm"], rows)

    def _alerts(self, risks: list[RiskItem]) -> tuple[list[JSON], str]:
        refs = [
            self.rs.add(
                compact(
                    {
                        "resourceType": "Flag",
                        "id": resource_id("Flag", *_key(r.source, r.risk_id)),
                        "text": n.generated(n.para(_risk_text(r))),
                        "status": "active",
                        "code": codeable_concept(r.code, self.t, text=r.text)
                        or {"text": r.note or "Riskitieto"},
                        "subject": self.subject,
                        "period": {"start": r.date} if r.date else None,
                        "author": self.rs.author(r.author),
                    }
                )
            )
            for r in risks
        ]
        rows = [[_risk_text(r), r.note, r.date] for r in risks]
        return refs, n.table(["Riski", "Huomio", "Pvm"], rows)

    def _medication_text(self, lists: list[str]) -> str:
        text = n.para("Kanta-asiakirjoissa ei ole rakenteista lääkitystietoa.")
        for m in lists:
            text += n.para(f"Hoitosuunnitelman lääkityslista (vapaa teksti): {m}")
        return text

    def _immunizations(self, items: list[Immunization]) -> tuple[list[JSON], str]:
        refs = []
        for i in items:
            vaccine = codeable_concept(i.vaccine, self.t)
            if vaccine and i.product:
                vaccine["coding"].extend(codeable_concept(i.product, self.t)["coding"])
            elif i.product:
                vaccine = codeable_concept(i.product, self.t)
            performer = self.rs.author(i.author)
            protocol = compact(
                {
                    "targetDisease": codeable_concepts(i.target_diseases, self.t),
                    "doseNumberPositiveInt": i.dose_number,
                    "doseNumberString": None if i.dose_number else "Tuntematon",
                }
            )
            refs.append(
                self.rs.add(
                    compact(
                        {
                            "resourceType": "Immunization",
                            "id": resource_id("Immunization", *_key(i.source, i.immunization_id)),
                            "text": n.generated(n.para(_immunization_text(i))),
                            "status": "completed",
                            "vaccineCode": vaccine or {"text": "Tuntematon rokote"},
                            "patient": self.subject,
                            "occurrenceDateTime": i.date,
                            "lotNumber": i.lot_number,
                            "site": codeable_concept(i.site, self.t),
                            "route": codeable_concept(i.route, self.t),
                            "doseQuantity": quantity(i.dose, self.t),
                            "performer": [
                                {
                                    "function": fixed_concept(PERFORMER_FUNCTION, "AP"),
                                    "actor": performer,
                                }
                            ]
                            if performer
                            else [],
                            "protocolApplied": [protocol],
                        }
                    )
                )
            )
        rows = [
            [
                i.vaccine.display if i.vaccine else None,
                i.product.display if i.product else None,
                i.date,
                i.lot_number,
                ", ".join(d.display or d.code for d in i.target_diseases) or None,
            ]
            for i in items
        ]
        return refs, n.table(["Rokote", "Valmiste", "Pvm", "Erä", "Suoja"], rows)

    def _results(
        self,
        labs: list[LabResult],
        imaging: list[ImagingResult],
        measurements: list[VitalSign],
    ) -> tuple[list[JSON], str]:
        refs = []
        for r in labs:
            obs = self.lab.observation(
                self.rs, r, self.subject, None, None, {}, profile=MEDICAL_TEST_RESULT
            )
            refs.append(self.rs.add(obs))
        for img in imaging:
            refs.append(self._imaging(img))
        for v in measurements:
            refs.append(self._measurement(v, vital=False))
        text = ""
        if labs:
            text += n.para("Laboratoriotutkimukset") + results_table(labs)
        if imaging:
            rows = [
                [
                    i.code.display or i.code.code,
                    i.statement or ("Tutkimus tehty" if not i.has_statement else None),
                    i.assessment.display if i.assessment else None,
                    i.effective,
                ]
                for i in imaging
            ]
            text += n.para("Kuvantamistutkimukset") + n.table(
                ["Tutkimus", "Lausunto", "Arvio", "Aika"], rows
            )
        if measurements:
            text += n.para("Muut mittaukset") + _measurement_table(measurements)
        return refs, text

    def _imaging(self, i: ImagingResult) -> JSON:
        notes = [
            x
            for x in (
                f"Arvio: {i.assessment.display}" if i.assessment else None,
                f"Keskeytetty: {i.interruption_reason.display}" if i.interruption_reason else None,
            )
            if x
        ]
        return self.rs.add(
            compact(
                {
                    "resourceType": "Observation",
                    "id": resource_id("Observation", "imaging", *_key(i.source)),
                    "meta": {"profile": [MEDICAL_TEST_RESULT]},
                    "text": n.generated(n.para(i.code.display or i.code.code), n.para(i.statement)),
                    "identifier": [x for x in (identifier(i.accession),) if x],
                    "status": "final",
                    "category": [fixed_concept(OBS_CATEGORY, "imaging", "Imaging")],
                    "code": codeable_concept(i.code, self.t),
                    "subject": self.subject,
                    "effectiveDateTime": i.effective,
                    "performer": [p for p in [self.rs.author(i.author)] if p],
                    "valueString": i.statement,
                    "note": [{"text": x} for x in notes],
                }
            )
        )

    def _procedures(self, items: list[Procedure]) -> tuple[list[JSON], str]:
        refs = []
        for p in items:
            performer = self.rs.author(p.author)
            performed = period(p.performed)
            single = performed and performed.get("start") == performed.get("end")
            refs.append(
                self.rs.add(
                    compact(
                        {
                            "resourceType": "Procedure",
                            "id": resource_id("Procedure", *_key(p.source, p.procedure_id)),
                            "text": n.generated(n.para(p.text or p.code.display or p.code.code)),
                            "status": "completed",
                            "code": codeable_concept(p.code, self.t, text=p.text),
                            "subject": self.subject,
                            "performedDateTime": performed.get("start") if single else None,
                            "performedPeriod": performed if performed and not single else None,
                            "performer": [{"actor": performer}] if performer else [],
                            "bodySite": codeable_concepts(p.body_sites, self.t),
                        }
                    )
                )
            )
        rows = [
            [p.text or p.code.display, p.code.code, p.performed.start if p.performed else None]
            for p in items
        ]
        return refs, n.table(["Toimenpide", "Koodi", "Pvm"], rows)

    def _vital_signs(self, items: list[VitalSign]) -> tuple[list[JSON], str]:
        refs = [self._measurement(v, vital=True) for v in items]
        return refs, _measurement_table(items)

    def _measurement(self, v: VitalSign, vital: bool) -> JSON:
        category = "vital-signs" if vital else "exam"
        notes = [*v.notes, *([f"Poikkeavuus: {v.abnormality.display}"] if v.abnormality else [])]
        return self.rs.add(
            compact(
                {
                    "resourceType": "Observation",
                    "id": resource_id("Observation", "vital", *_key(v.source, v.measurement_id)),
                    "meta": {"profile": [VITAL_SIGNS if vital else MEDICAL_TEST_RESULT]},
                    "text": n.generated(n.para(_measurement_text(v))),
                    "status": "final",
                    "category": [fixed_concept(OBS_CATEGORY, category)],
                    "code": self._measurement_code(v, vital),
                    "subject": self.subject,
                    "effectiveDateTime": v.effective,
                    "performer": [p for p in [self.rs.author(v.author)] if p],
                    "valueQuantity": quantity(v.value, self.t),
                    "method": codeable_concept(v.method, self.t),
                    "referenceRange": [
                        rr for x in v.reference_ranges if (rr := reference_range(x, self.t))
                    ],
                    "note": [{"text": x} for x in notes],
                }
            )
        )

    def _measurement_code(self, v: VitalSign, vital: bool) -> JSON | None:
        code = codeable_concept(v.code, self.t)
        parent = VITAL_SIGN_PARENT.get(v.code.code) if vital else None
        if code is not None and parent:
            code["coding"].append({"system": LOINC, "code": parent[0], "display": parent[1]})
        return code

    def _care_plans(self, plans: list[CarePlan]) -> tuple[list[JSON], str]:
        refs = [self._care_plan(p) for p in plans]
        text = "".join(_care_plan_html(p) for p in plans)
        return refs, text

    def _care_plan(self, p: CarePlan) -> JSON:
        key = p.source.document_id
        goals = []
        for i, g in enumerate(p.goals or ["Hoidon tavoite"]):
            targets = (
                [
                    compact(
                        {
                            "measure": codeable_concept(t.code, self.t),
                            "detailRange": range_(t.range, self.t),
                        }
                    )
                    for t in p.targets
                ]
                if i == 0
                else []
            )
            goals.append(
                self.rs.add(
                    compact(
                        {
                            "resourceType": "Goal",
                            "id": resource_id("Goal", key, str(i)),
                            "text": n.generated(n.para(g)),
                            "lifecycleStatus": "active",
                            "description": {"text": g},
                            "subject": self.subject,
                            "target": targets,
                        }
                    )
                )
            )
        team = None
        if p.care_team:
            team = self.rs.add(
                compact(
                    {
                        "resourceType": "CareTeam",
                        "id": resource_id("CareTeam", key),
                        "text": n.generated(
                            *[
                                n.para(
                                    m.organization
                                    or (m.profession.display if m.profession else None)
                                )
                                for m in p.care_team
                            ]
                        ),
                        "status": "active",
                        "subject": self.subject,
                        "participant": [
                            compact(
                                {
                                    "role": [r]
                                    if (r := codeable_concept(m.profession, self.t))
                                    else [],
                                    "member": self.rs.organization(_org(m.organization)),
                                }
                            )
                            for m in p.care_team
                        ],
                    }
                )
            )
        activities = [
            {
                "detail": compact(
                    {
                        "code": codeable_concept(s.code, self.t),
                        "status": _service_status(s.status),
                        "scheduledPeriod": {"start": s.start} if s.start else None,
                        "description": "; ".join(x for x in (s.content, s.note, *s.conditions) if x)
                        or None,
                    }
                )
            }
            for s in p.planned_services
        ]
        notes = [
            *(f"Hoidon tarve: {x}" for x in p.needs),
            *(f"Toimintakykyyn liittyvä tarve: {x}" for x in p.functional_needs),
            *(f"Toimintakykyyn liittyvä tavoite: {x}" for x in p.functional_goals),
            *(f"Tavoitteen asettajat: {x}" for x in p.goal_setters),
            *(f"Hoidon toteutus ja keinot: {x}" for x in p.means),
            *(f"Koordinoiva taho: {x}" for x in p.coordinators),
            *([f"Diagnoosilista: {p.diagnosis_list}"] if p.diagnosis_list else []),
            *([f"Lääkityslista: {p.medication_list}"] if p.medication_list else []),
            *([f"Lisätiedot: {p.additional_info}"] if p.additional_info else []),
        ]
        reasons = ", ".join(f"{r.code} {r.display or ''}".strip() for r in p.reasons)
        return self.rs.add(
            compact(
                {
                    "resourceType": "CarePlan",
                    "id": resource_id("CarePlan", key),
                    "text": n.generated(_care_plan_html(p)),
                    "status": "active",
                    "intent": "plan",
                    "title": "Terveys- ja hoitosuunnitelma",
                    "description": f"Hoidon syy: {reasons}" if reasons else None,
                    "subject": self.subject,
                    "period": {"start": p.date} if p.date else None,
                    "created": p.date,
                    "author": self.rs.author(p.author),
                    "careTeam": [team] if team else [],
                    "goal": goals,
                    "activity": activities,
                    "note": [{"text": x} for x in notes],
                }
            )
        )


# --- helpers ---------------------------------------------------------------------------------


def _key(source: SourceRef, *ids: Identifier | str | None) -> tuple[str, ...]:
    """Stable key parts for a resource id: Kanta unique ids first, then the entry id."""
    for i in ids:
        if i is None:
            continue
        return (i.key,) if isinstance(i, Identifier) else (i,)
    if source.entry_id is not None:
        return (source.entry_id.key,)
    return (source.document_id, source.section)


def _org(name: str | None) -> Organization | None:
    return Organization(name=name) if name else None


def _risk_text(r: RiskItem) -> str:
    parts = [
        r.risk_type.display if r.risk_type else None,
        r.text or (r.code.display if r.code else None),
        ", ".join(a.display or a.code for a in r.agents) or None,
    ]
    return "; ".join(p for p in parts if p) or "Riskitieto"


def _immunization_text(i: Immunization) -> str:
    name = (i.product.display if i.product else None) or (i.vaccine.display if i.vaccine else "")
    return f"{name} {i.date or ''}".strip()


def _measurement_text(v: VitalSign) -> str:
    value = f"{v.value.value} {v.value.unit or ''}".strip() if v.value else ""
    return f"{v.code.display or v.code.code}: {value}".strip(": ")


def _measurement_table(items: list[VitalSign]) -> str:
    rows = [
        [
            v.code.display or v.code.code,
            f"{v.value.value} {v.value.unit or ''}".strip() if v.value else None,
            v.effective,
        ]
        for v in items
    ]
    return n.table(["Mittaus", "Arvo", "Aika"], rows)


def _service_status(c: Coding | None) -> str:
    # Kanta planned service status 6 "Varattu" (booked) → scheduled
    if c is not None and c.code == "6":
        return "scheduled"
    return "not-started"


def _care_plan_html(p: CarePlan) -> str:
    out = n.para(f"Terveys- ja hoitosuunnitelma {p.date[:10] if p.date else ''}".strip())
    for label, values in (
        ("Hoidon tarve", p.needs),
        ("Hoidon tavoitteet", p.goals),
        ("Hoidon toteutus ja keinot", p.means),
    ):
        for v in values:
            out += n.para(f"{label}: {v}")
    for s in p.planned_services:
        out += n.para(
            f"Suunniteltu palvelu: {s.code.display or s.code.code}"
            f"{f' {s.start}' if s.start else ''}{f' - {s.content}' if s.content else ''}"
        )
    return out


def build_patient_summaries(
    patient: PatientResult, terminology: Terminology, generated_at: str
) -> list[tuple[str, JSON]]:
    builder = PatientSummaryBuilder(terminology, generated_at)
    return [(patient.record.patient.pseudonym, builder.build(patient))]
