"""European Laboratory Report (hl7.fhir.eu.laboratory 2.1.0) documents.

One document per source lab document (D5). Results taken from Kooste documents (because
their original is not in the export) are grouped by the original document they came from.
Each requested test of an order becomes a ServiceRequest; the tests of one order share the
order id as ``requisition``, so a repeating order that produced several reports stays
recognisable as one order.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from kanta2fhir.fhir import narrative as n
from kanta2fhir.fhir.bundle import document_bundle
from kanta2fhir.fhir.datatypes import (
    JSON,
    codeable_concept,
    compact,
    fixed_concept,
    identifier,
    period,
    quantity,
    reference_range,
    resource_id,
)
from kanta2fhir.fhir.datatypes import coding as fhir_coding
from kanta2fhir.fhir.profiles import EU_CORE
from kanta2fhir.fhir.resources import ResourceSet, document_identifier
from kanta2fhir.model import (
    Coding,
    LabResult,
    Order,
    OrderedTest,
    Quantity,
    Range,
)
from kanta2fhir.pipeline import PatientResult
from kanta2fhir.record import ParsedDocument, instant
from kanta2fhir.terminology import Terminology

LAB = "http://hl7.eu/fhir/laboratory/StructureDefinition"
PROFILES = {
    **EU_CORE,
    "Bundle": f"{LAB}/Bundle-eu-lab",
    "Composition": f"{LAB}/Composition-eu-lab",
    "DiagnosticReport": f"{LAB}/DiagnosticReport-eu-lab",
    "Observation": f"{LAB}/Observation-resultslab-eu-lab",
    "ServiceRequest": f"{LAB}/ServiceRequest-eu-lab",
    "Specimen": f"{LAB}/Specimen-eu-lab",
}

LOINC = "http://loinc.org"
REPORT_TYPE = fixed_concept(LOINC, "11502-2", "Laboratory report")
STUDY_TYPE = fixed_concept(LOINC, "26436-6", "Laboratory studies (set)")
OBS_CATEGORY = fixed_concept(
    "http://terminology.hl7.org/CodeSystem/observation-category", "laboratory", "Laboratory"
)
DR_COMPOSITION_EXT = (
    "http://hl7.org/fhir/5.0/StructureDefinition/extension-DiagnosticReport.composition"
)
COMPOSITION_DR_EXT = (
    "http://hl7.eu/fhir/extensions/StructureDefinition/composition-diagnosticReportReference"
)
DATA_ABSENT = "http://terminology.hl7.org/CodeSystem/data-absent-reason"


@dataclass(slots=True)
class LabReportInput:
    key: str  # source document id (the original document for Kooste results)
    document: ParsedDocument | None  # None when only Kooste copies of the results exist
    results: list[LabResult] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)


def report_inputs(patient: PatientResult) -> list[LabReportInput]:
    """Group the patient's lab results into reports: one per source document."""
    docs = {d.id: d for d in patient.record.documents}
    groups: dict[str, LabReportInput] = {}
    for r in patient.clinical.lab_results:
        key = r.source.origin_document if r.source.from_summary else r.source.document_id
        key = key or r.source.document_id
        group = groups.get(key)
        if group is None:
            doc = docs.get(key) if not r.source.from_summary else None
            group = groups[key] = LabReportInput(key=key, document=doc)
        group.results.append(r)

    lab_orders = [o for o in patient.clinical.orders if o.category == "laboratory"]
    for group in groups.values():
        order_ids = {r.order_id.key for r in group.results if r.order_id}
        for o in lab_orders:
            same_order = o.order_id is not None and o.order_id.key in order_ids
            same_doc = o.source.document_id == group.key
            if same_order or same_doc:
                group.orders.append(o)
    return sorted(groups.values(), key=lambda g: instant(_report_date(g)))


def _report_date(group: LabReportInput) -> str | None:
    if group.document and group.document.header.effective_time:
        return group.document.header.effective_time
    dates = [r.issued or r.effective for r in group.results if r.issued or r.effective]
    return max(dates, key=instant) if dates else None


class LabReportBuilder:
    def __init__(self, terminology: Terminology, generated_at: str) -> None:
        self.t = terminology
        self.generated_at = generated_at

    def build(self, patient: PatientResult, group: LabReportInput) -> JSON:
        rs = ResourceSet(self.t, profiles=PROFILES)
        subject = rs.patient(patient.record.patient)
        doc = group.document

        encounter = None
        enc_key = (
            doc.header.encounter.identifier.key
            if doc and doc.header.encounter and doc.header.encounter.identifier
            else group.results[0].source.encounter_id
        )
        if enc_key and enc_key in patient.record.encounters:
            encounter = rs.encounter(patient.record.encounters[enc_key], subject)

        header_author = doc.header.authors[0] if doc and doc.header.authors else None
        fallback_author = header_author or next((r.author for r in group.results if r.author), None)
        author = rs.author(fallback_author)
        custodian = rs.organization(doc.header.custodian if doc else None)
        if author is None:
            author = custodian

        requests = self._service_requests(rs, group.orders, subject, encounter)
        results = [
            self.observation(rs, r, subject, encounter, author, requests) for r in group.results
        ]
        specimens = sorted(
            {s["reference"] for o in results for s in [o.get("specimen")] if s},
        )

        composition_id = resource_id("Composition", "lab", group.key)
        report_id = resource_id("DiagnosticReport", "lab", group.key)
        doc_identifier = document_identifier(group.key)
        date = _report_date(group) or self.generated_at
        status = self._status(results)
        effective = [o.get("effectiveDateTime") for o in results if o.get("effectiveDateTime")]
        issued = [o.get("issued") for o in results if o.get("issued")]

        report = rs.add(
            compact(
                {
                    "resourceType": "DiagnosticReport",
                    "id": report_id,
                    "text": self.section_text(group.results),
                    "extension": [
                        {
                            "url": DR_COMPOSITION_EXT,
                            "valueReference": {"reference": f"urn:uuid:{composition_id}"},
                        }
                    ],
                    "identifier": [doc_identifier],
                    "basedOn": _unique([ref for refs in requests.values() for ref in refs]),
                    "status": status,
                    "category": [STUDY_TYPE],
                    "code": REPORT_TYPE,
                    "subject": subject,
                    "encounter": encounter,
                    "effectiveDateTime": min(effective, key=instant) if effective else date,
                    "issued": max(issued, key=instant) if issued else None,
                    "performer": [p for p in [author] if p],
                    "specimen": [{"reference": s} for s in specimens],
                    "result": [rs.add(o) for o in results],
                }
            )
        )

        composition = compact(
            {
                "resourceType": "Composition",
                "id": composition_id,
                "meta": {"profile": [PROFILES["Composition"]]},
                "text": n.generated(
                    n.para(f"Laboratoriotulokset {date[:10]}"),
                    n.para(f"{len(results)} tutkimustulosta"),
                    lang="fi",
                ),
                "language": "fi",
                "extension": [{"url": COMPOSITION_DR_EXT, "valueReference": report}],
                "identifier": doc_identifier,
                "status": status if status in ("preliminary", "final", "amended") else "final",
                "type": REPORT_TYPE,
                "category": [STUDY_TYPE],
                "subject": subject,
                "encounter": encounter,
                "date": date,
                "author": [author] if author else [{"display": "Tuntematon"}],
                "title": f"Laboratoriotulokset {date[:10]}",
                "custodian": custodian,
                "section": [
                    {
                        "title": "Laboratoriotutkimukset",
                        "code": STUDY_TYPE,
                        "text": self.section_text(group.results),
                        "entry": [{"reference": f"urn:uuid:{o['id']}"} for o in results],
                    }
                ],
            }
        )

        sources = {group.key} | {r.source.document_id for r in group.results}
        rs.provenance(rs.derived_resources(), sources, self.generated_at)
        return document_bundle(
            f"lab|{group.key}", self.generated_at, composition, rs.entries(), PROFILES["Bundle"]
        )

    # --- parts -----------------------------------------------------------------------------

    def _service_requests(
        self, rs: ResourceSet, orders: list[Order], subject: JSON, encounter: JSON | None
    ) -> dict[str, list[JSON]]:
        """ServiceRequests per test; returns order id → references (and test code → refs)."""
        refs: dict[str, list[JSON]] = defaultdict(list)
        for order in orders:
            order_key = order.order_id.key if order.order_id else order.source.document_id
            requester = rs.author(order.requester)
            for test in order.tests or [OrderedTest(code=Coding("?", None, "Laboratoriotutkimus"))]:
                sr = self._service_request(
                    rs, order, order_key, test, subject, encounter, requester
                )
                refs[order_key].append(sr)
                refs[f"{order_key}#{test.code.code}"].append(sr)
        return refs

    def _service_request(
        self,
        rs: ResourceSet,
        order: Order,
        order_key: str,
        test: OrderedTest,
        subject: JSON,
        encounter: JSON | None,
        requester: JSON | None,
    ) -> JSON:
        requisition = identifier(order.order_id) if order.order_id else None
        notes = [x for x in (order.note, test.note) if x]
        timing = None
        if order.repeat_period or order.repeat_count:
            timing = {
                "repeat": compact(
                    {"boundsPeriod": period(order.repeat_period), "count": order.repeat_count}
                )
            }
        return rs.add(
            compact(
                {
                    "resourceType": "ServiceRequest",
                    "id": resource_id("ServiceRequest", order_key, test.code.code),
                    "text": n.generated(n.para(test.code.display or test.code.code)),
                    "identifier": [
                        {"system": f"urn:oid:{order_key.split('/')[0]}", "value": test.code.code}
                    ],
                    "requisition": requisition,
                    "status": "completed",
                    "intent": "order",
                    "category": [STUDY_TYPE],
                    "code": codeable_concept(test.code, self.t),
                    "subject": subject,
                    "encounter": encounter,
                    "occurrenceTiming": timing,
                    "authoredOn": order.date,
                    "requester": requester,
                    "specimen": [self._specimen(rs, test.specimen, subject)]
                    if test.specimen
                    else [],
                    "note": [{"text": x} for x in notes],
                }
            )
        )

    def _specimen(self, rs: ResourceSet, code: Coding, subject: JSON) -> JSON:
        patient_key = subject["reference"]
        return rs.add(
            compact(
                {
                    "resourceType": "Specimen",
                    "id": resource_id("Specimen", patient_key, code.system or "", code.code),
                    "text": n.generated(n.para(code.display or code.code)),
                    "type": codeable_concept(code, self.t),
                    "subject": subject,
                }
            )
        )

    def observation(
        self,
        rs: ResourceSet,
        r: LabResult,
        subject: JSON,
        encounter: JSON | None,
        report_author: JSON | None,
        requests: dict[str, list[JSON]],
        profile: str = PROFILES["Observation"],
    ) -> JSON:
        """A lab result Observation (also used by the Patient Summary with another profile)."""
        code = codeable_concept(r.code, self.t)
        if code is not None:
            for local in r.local_codes:
                code["coding"].append(fhir_coding(self.t.codings(local)[0]))
        performer = [p for p in [rs.author(r.author) or report_author] if p]
        if r.performer_name:
            performer.append({"display": r.performer_name})
        order_key = r.order_id.key if r.order_id else None
        based_on = requests.get(f"{order_key}#{r.code.code}") or requests.get(order_key or "", [])

        obs: JSON = {
            "resourceType": "Observation",
            "id": resource_id("Observation", "lab", *_result_key(r)),
            "meta": {"profile": [profile]},
            "text": n.generated(n.para(_result_text(r))),
            "identifier": [i] if (i := identifier(r.test_id)) else [],
            "basedOn": based_on,
            "status": self.t.result_status(r.status),
            "category": [OBS_CATEGORY, STUDY_TYPE],
            "code": code,
            "subject": subject,
            "encounter": encounter,
            "effectiveDateTime": r.effective,
            "issued": r.issued,
            "performer": performer,
        }
        obs |= self._value(r)
        obs |= compact(
            {
                "interpretation": self._interpretation(r.interpretation),
                "note": [{"text": t} for t in r.notes],
                "method": codeable_concept(r.method, self.t),
                "specimen": self._specimen(rs, r.specimen, subject) if r.specimen else None,
                "referenceRange": [
                    rr for x in r.reference_ranges if (rr := reference_range(x, self.t))
                ],
            }
        )
        return compact(obs)

    def _value(self, r: LabResult) -> JSON:
        v = r.value
        if isinstance(v, Quantity) and (q := quantity(v, self.t)):
            return {"valueQuantity": q}
        if isinstance(v, Range):
            return {
                "valueRange": compact(
                    {"low": quantity(v.low, self.t), "high": quantity(v.high, self.t)}
                )
            }
        if isinstance(v, Coding):
            return {"valueCodeableConcept": codeable_concept(v, self.t)}
        if isinstance(v, bool):
            return {"valueBoolean": v}
        if isinstance(v, int):
            return {"valueInteger": v}
        if isinstance(v, str):
            return {"valueString": v}
        if r.statement:  # e.g. protein electrophoresis: the statement is the result
            return {"valueString": r.statement}
        return {"dataAbsentReason": fixed_concept(DATA_ABSENT, "unknown", "Unknown")}

    def _interpretation(self, c: Coding | None) -> list[JSON]:
        if c is None:
            return []
        codings = []
        if mapped := self.t.interpretation(c):
            codings.append(fhir_coding(mapped))
        cc = codeable_concept(c, self.t)
        if cc:
            codings.extend(cc["coding"])
        return [{"coding": codings, "text": c.display}] if codings else []

    @staticmethod
    def _status(observations: list[JSON]) -> str:
        statuses = {o["status"] for o in observations}
        if statuses <= {"final"}:
            return "final"
        if "preliminary" in statuses:
            return "partial"
        if statuses <= {"final", "corrected", "amended"}:
            return "amended"
        return "final" if "final" in statuses else "unknown"

    def section_text(self, results: list[LabResult]) -> JSON:
        return n.generated(results_table(results))


def results_table(results: list[LabResult]) -> str:
    """An XHTML table of lab results (shared with the Patient Summary)."""
    rows = []
    for r in results:
        rr = r.reference_ranges[0] if r.reference_ranges else None
        ref = None
        if rr:
            ref = " - ".join(x for x in (_q(rr.low), _q(rr.high)) if x) or rr.text
        rows.append(
            [
                r.code.display or r.code.code,
                _value_text(r),
                ref,
                r.interpretation.display if r.interpretation else None,
                r.effective,
            ]
        )
    return n.table(["Tutkimus", "Tulos", "Viitearvot", "Tulkinta", "Aika"], rows)


def _q(q: Quantity | None) -> str | None:
    return None if q is None else f"{q.value} {q.unit or ''}".strip()


def _value_text(r: LabResult) -> str | None:
    v = r.value
    if isinstance(v, Quantity):
        return _q(v)
    if isinstance(v, Coding):
        return v.display or v.code
    if v is None:
        return r.statement
    return str(v)


def _result_text(r: LabResult) -> str:
    value = _value_text(r)
    return f"{r.code.display or r.code.code}: {value}" if value else (r.code.display or r.code.code)


def _result_key(r: LabResult) -> tuple[str, ...]:
    if r.test_id:
        return ("test", r.test_id.key)
    if r.source.entry_id:
        return ("entry", r.source.entry_id.key)
    return ("content", r.source.document_id, r.code.code, r.effective or "")


def _unique(refs: list[JSON]) -> list[JSON]:
    seen: set[str] = set()
    out = []
    for ref in refs:
        if ref["reference"] not in seen:
            seen.add(ref["reference"])
            out.append(ref)
    return out


def build_lab_reports(
    patient: PatientResult, terminology: Terminology, generated_at: str
) -> list[tuple[str, JSON]]:
    """(file stem, Bundle) for every lab report of the patient."""
    builder = LabReportBuilder(terminology, generated_at)
    return [(g.key.replace("/", "_"), builder.build(patient, g)) for g in report_inputs(patient)]
