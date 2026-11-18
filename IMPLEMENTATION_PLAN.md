# Kanta CDA → EU FHIR documents: implementation plan

Status: **draft for discussion** (2026-11-18). Nothing is implemented yet.

Goal: read a Kanta export (`*.ndjson` of FHIR `DocumentReference`s with embedded documents) and produce:

1. **European Patient Summary** documents (one per patient)
2. **European Laboratory Report** documents (one per lab report or order)
3. **European Hospital Discharge Report** documents (one per inpatient stay)

---

## 1. What the input actually contains

Analysis of `kanta_terveystiedot_051001A937S_1791361732438.ndjson` (276 lines, 7.9 MB, one Kanta test patient):

### Envelope
- Each line is `{"resource": {DocumentReference}}`. It is **not** a bare resource, so the wrapper must be unwrapped.
- Profile `https://hrp.kanta.fi/fhir/StructureDefinition/HRPDocumentReference`.
- `subject.identifier` = HETU (`urn:oid:1.2.246.21`). **Inside the CDA the HETU is masked (`****`)**, so patient identity must come from the DocumentReference.
- `type` (`fihrp-cs-documentreferencetype`): `1` Palvelutapahtuma (128), `2` Hoitoasiakirja (140), `3` Kooste (8).
- `category` = view (näkymä, `1.2.246.537.6.12.2002`): 20 Kirurgia (127), 102 Radiologia, 103 Laboratorio, 10 Sisätaudit, 98 Yleislääketiede, 175 Riskitiedot, 201 Rokotukset, 335–345 (care plan) and others.
- `context.related` links documents to the service event (palvelutapahtuma); `context.period` is present on the service event documents.
- `content`: always exactly one attachment, `text/xml`, `language=fi`, base64. **All 276 are HL7 v3 CDA R2** (`ClinicalDocument`, `realmCode=FI`). No other formats appear in this file, but the design keeps the format detection pluggable.

### CDA documents (Kanta "eArkisto" CDA R2 with the `urn:hl7finland` extensions)
| Kind | Count | Templates | Content |
|---|---|---|---|
| Palvelutapahtuma-asiakirja (service event) | 128 | 2015.30 / 2020.6 | Header only: `encompassingEncounter` period, organisations, `hl7fi:localHeader` (all are `encompassingEncounterCode=2` **Avohoitokäyntitieto**, meaning outpatient) |
| Kertomusteksti (patient record entries) | 140 | 2015.30 / 2020.6 / 2020.8 / 2020.11 / 2016.8 / 2017.11 | View → care-process phase → heading section hierarchy with structured entries |
| Kooste (summaries) | 8 | 2018.12 | Generated 2026-10-07: procedure, diagnosis, lab, imaging, immunisation, physiological measurement and risk summaries. **These duplicate data from the original records.** |

Structured entries found (keyed by the Kanta technical structure code system `1.2.246.537.6.12.999.2003` or by the view-specific code systems):

| Clinical content | CDA shape | Code systems | Count (incl. duplicates) |
|---|---|---|---|
| Diagnoses | `observation` code `2` with qualifier PAA/SIVU, value ICD-10; sub-observations 2.1 (permanence PYS/KER), 2.2 (certainty), 2.10 (reason for visit), 2.14/2.15 (episode) | ICD-10 FI `1.2.246.537.6.1.1999` | 8 |
| Risk information (allergies/intolerances, other risks) | `observation` code `13`, value ICD-10; 13.2 agent (ATC), 13.4 note, 13.6 severity, 13.7 risk type (e.g. L9 *other drug reaction*), 13.9 id | ICD-10, ATC, `1.2.246.537.5.40034.2006` | 4 |
| Immunisations | `substanceAdministration` code `19`; ATC + VNR product, lot, route, site, dose; 19.1 protection against (diseases); 19.7 id | ATC `1.2.246.537.6.32.2007`, VNR `1.2.246.537.6.55` | 4 |
| Procedures | `procedure` | THL procedure classification `1.2.246.537.6.2.2007` (all TQW30 Akupunktio, test data) | 254 |
| Lab results | `organizer` 27 (orders, moodCode RQO) + `observation` (EVN) with PQ value, interpretation, reference range, specimen, status qualifier (F = final), 103.x sub-observations (order id, test id, performer, completion time, notes) | Kuntaliitto lab nomenclature `1.2.246.537.6.3.2006`, plus local translations | ~25 |
| Imaging | `organizer` 26 (orders) + `observation` | Procedure classification (GD1QA, EB1BA …) | ~18 |
| Physiological measurements | `observation` with LOINC-subset codes, PQ, reference range, 23.x sub-observations | `1.2.246.537.6.96.2008` (LOINC codes) | 4 |
| Health and care plan | `observation`s 101–605 (needs, goals, target values, planned services, diagnosis list, medication list), mostly ED references to narrative | `1.2.246.537.6.12.2002.345` | 1 doc |

**Not present in this file:** structured medication (no Kanta prescription or medication-list data), inpatient stays, discharge summaries (epikriisi/loppulausunto), lab reports as separate documents with LOINC codes, and non-CDA formats.

---

## 2. Architecture

A three-stage pipeline, so that input formats and output document types vary independently:

```
ndjson ──► [1 Reader] ──► DocumentReference + raw payload
                │
                ▼
         [2 Format parsers]  (registry by contentType / root element / templateId)
           • KantaCdaParser (CDA R2 + hl7fi extensions)   ← implemented first
           • (later: FHIR JSON, PDF passthrough, …)
                │
                ▼
         Canonical clinical model (format-neutral, per patient)
           Patient, Encounter, Condition, RiskItem/Allergy, Immunization,
           Procedure, LabOrder, LabResult, Specimen, VitalSign, ImagingStudy,
           CarePlan, Narrative blocks, Provenance (source doc id, setId/version)
                │
                ▼
         [3 Consolidation]  de-duplication, version handling, Kooste vs. original
                │
                ▼
         [4 Builders]  ─► EPS Bundle   ─► Lab Report Bundle(s)   ─► HDR Bundle(s)
           shared FHIR resource factories + terminology mapping layer
                │
                ▼
         [5 Validation]  HL7 FHIR Validator against the EU IG packages
```

### 2.1 Reader
- Streaming line reader. Unwrap `resource`, tolerate bare resources too.
- Decode `attachment.data` (base64), or fetch `attachment.url` if it is ever used (not in this file).
- Keep DocumentReference metadata (type, category, author, date, related ids) attached to the payload.

### 2.2 Kanta CDA parser
- Header: patient (name, `CL` = calling name, gender `1.2.246.537.5.1.1997`, birthTime), HETU from the DocumentReference, author, custodian, `encompassingEncounter`, `hl7fi:localHeader` (document type, encounter type, record status, function code).
- Body: walk view → phase → heading sections. Record the section path on every entry, because it is the clinical context (for example "Hoidon arviointi / Diagnoosi").
- Entry dispatch by `(element, code system, code)` and by `templateId`, with one small extractor per entry type. Unknown entries are logged and kept as narrative only.
- Sub-observations (`entryRelationship`) are read through a helper that maps code to value, since Kanta packs attributes there (certainty, permanence, ids, notes).
- CDA narrative (`section/text`) is converted to FHIR XHTML (table/list/paragraph/content mapping, ID references resolved) for Composition section narratives and ED `reference` values.
- Handles both template generations (2015.x and 2020.x). They differ mainly in templateIds and some optional details.

### 2.3 Consolidation
- **Kooste documents duplicate the originals.** Prefer the original records and use Kooste only for items not found elsewhere.
- Deduplicate by Kanta unique ids: 2.14 diagnosis episode id, 13.9 risk id, 19.7 immunisation id, 23.6 measurement id, 30 lab test id, 21 lab order id, entry `id/@root`. Fall back to a content hash of (code, date, value).
- Document versions: `setId` + `versionNumber` and `relatedDocument` RPLC mean only the latest version counts.
- Diagnosis status: `PYS` (permanent) → active problem; `KER` (temporary) → active/resolved depending on the date (rule to agree, see §5).

### 2.4 Terminology layer (`terminology/` mapping tables, data-driven)
| Kanta OID | FHIR system | Notes |
|---|---|---|
| `1.2.246.537.6.1.1999` ICD-10 FI | `urn:oid:1.2.246.537.6.1.1999` (FinCore style) **plus** a `http://hl7.org/fhir/sid/icd-10` coding when the code is a WHO code | Finnish 5-character codes (Q32.11) are not WHO codes |
| `1.2.246.537.6.96.2008` physiological measurements | `http://loinc.org` | The codes are LOINC |
| `1.2.246.537.6.32.2007` ATC | `http://www.whocc.no/atc` | |
| `1.2.246.537.6.55` VNR | `urn:oid:1.2.246.537.6.55` | Product code |
| `1.2.246.537.6.3.2006` lab nomenclature | `urn:oid:1.2.246.537.6.3.2006` | **No LOINC mapping in source**, see §5 |
| `1.2.246.537.6.2.2007` procedure classification | `urn:oid:1.2.246.537.6.2.2007` | |
| `1.2.246.537.5.78.1997` interpretation | `v3-ObservationInterpretation` (H, L, N …) | Map table |
| `1.2.246.537.5.85.1997` result status | `Observation.status` (F → final, …) | |
| `1.2.246.537.5.1.1997` gender | `administrative-gender` | |
| `1.2.246.537.6.111.2007` / `.110.2007` route and site | `urn:oid:…` + EDQM / SNOMED where mappable | |
| `1.2.246.537.6.609.201501` vaccine target disease | `urn:oid:…` + SNOMED target-disease codes | Required binding area in EPS |
| Units | UCUM normalisation (`U/l` → `U/L`, `umol/l` → `umol/L`, `l/min` → `L/min`) | |

All original codings are kept. Mapped codings are added as additional `coding`s, never substituted, so nothing is lost.

### 2.5 Builders

**Shared:** Patient (EU core plus HETU identifier `urn:oid:1.2.246.21`), Organization/Practitioner/PractitionerRole from authors, Encounter from service events, Provenance pointing to the source DocumentReference ids, deterministic resource ids (UUIDv5 from Kanta ids) so reruns are stable, and Composition section narratives generated from the resources, with the original CDA narrative optionally appended.

**A. European Patient Summary (`hl7.fhir.eu.eps`)** — one `Bundle(type=document)` per patient, built from the consolidated model across all documents.

| EPS section | Source | Notes |
|---|---|---|
| Allergies and intolerances (required) | Risk items whose risk type is in the drug/allergy family (e.g. L9 + ATC agent) → `AllergyIntolerance` | Otherwise `emptyReason` |
| Alerts | Other risk items (critical risks) → `Flag` | |
| Problem list (required) | Diagnoses → `Condition` (PAA/SIVU → category, PYS/KER → clinicalStatus/verification) | |
| Medication summary (required) | None structured in this data → `emptyReason` = unavailable; care-plan medication list as narrative only | |
| Immunisations | `Immunization` (vaccine ATC + VNR, lot, route, site, dose, targetDisease via protocolApplied) | |
| History of procedures | `Procedure` | Deduplicated |
| Diagnostic results | Latest lab results (Observation-resultslab) + imaging results | Recent window, see §5 |
| Vital signs | Physiological measurements (LOINC) → vital-signs Observations | |
| Plan of care | Health and care plan → `CarePlan` (+ goals) | |
| Medical devices, history of pregnancy, social history, functional status, advance directives | Not in source → omitted | |

**B. European Laboratory Report (`hl7.fhir.eu.laboratory` 2.1.0)** — one `Bundle(type=document)` per lab report, with grouping key = lab order id (103.21) or else source document.
- `Composition` (lab report type, section per study/specialty), `DiagnosticReport-eu-lab` (status from result statuses, `basedOn` ServiceRequest), `ServiceRequest` from organizer 27 (requester, reason/note "Oireeton potilas", repeat period), `Observation` result profile (value PQ/ST/CD, interpretation, referenceRange incl. text 103.27, performer from 103.28, issued from 103.13, note 103.24), `Specimen` from `specimenPlayingEntity` (system abbreviation `1.2.246.537.6.17.2004`).
- The EKG ordered through the lab (1270 / FP1B5) is kept as a non-lab Observation in the report, or excluded (see §5).

**C. European Hospital Discharge Report (`hl7.fhir.eu.hdr`)** — one `Bundle(type=document)` per **inpatient** episode.
- Trigger: a service event whose encounter type is inpatient (osastohoitojakso in `hl7fi:encompassingEncounterCode`), together with the record entries linked through `context.related` / encounter id.
- Content: Encounter-eu-hdr (admission/discharge, period, service provider), admission reason / discharge diagnoses (PAA/SIVU), procedures, significant results, medication at discharge, allergies, plan of care / follow-up, and the narrative "Hospital course" from the Kertomusteksti sections.
- **This file has no inpatient episodes**, so the builder will produce zero documents. See §5 for how to develop and test it.

### 2.6 Validation and tests
- Download the IG packages (`hl7.fhir.eu.eps`, `hl7.fhir.eu.laboratory`, `hl7.fhir.eu.hdr`, `hl7.fhir.eu.base`, IPS 2.0.x) and pin versions in a lockfile.
- Run `validator_cli.jar -ig …` on every generated bundle in CI. A terminology server is optional; run it offline with `-tx n/a` first.
- Unit tests per extractor using small CDA fixtures cut from this file.
- Golden-file tests: whole ndjson → expected bundles (stable ids make this possible).
- Report: per input document, a list of what was mapped, skipped or not understood (coverage log).

### 2.7 CLI and packaging
```
kanta2fhir INPUT.ndjson --out OUT/ --targets eps,lab,hdr [--validate] [--keep-narrative] [--lang fi]
```
Output: `OUT/eps/<patient>.json`, `OUT/lab/<report-id>.json`, `OUT/hdr/<episode-id>.json`, `OUT/report.json`.

Privacy: real exports contain HETUs and health data. No PHI in logs (ids hashed), no network calls with data (validator and terminology run locally), and output is written only to the target directory.

---

## 3. Proposed project layout (assuming Python, see §5)

```
kanta2fhir/
  reader.py                  ndjson + DocumentReference unwrapping
  formats/registry.py        format detection
  formats/kanta_cda/         header.py, sections.py, entries/{diagnosis,risk,immunization,
                             procedure,lab,imaging,vitals,careplan}.py, narrative.py
  model.py                   canonical dataclasses
  consolidate.py             dedup, versions, Kooste handling
  terminology/               mapping tables (CSV/YAML) + lookup
  fhir/common.py             Patient, Org, Practitioner, Provenance, ids
  fhir/eps.py  fhir/lab.py  fhir/hdr.py
  cli.py
tests/ fixtures/ igs/ (package lock)
```

## 4. Milestones

1. Reader, format registry, CDA header parsing, canonical Patient/Encounter. Dump a coverage report for the whole file.
2. Entry extractors (diagnosis, risk, immunisation, procedure, lab, vitals, imaging, care plan) + narrative conversion + consolidation/dedup.
3. Terminology layer + shared FHIR factories.
4. **Lab Report** builder + validation (the best-structured source data, so it is the quickest path to a validated document).
5. **EPS** builder + validation.
6. **HDR** builder (against synthetic inpatient fixtures) + validation.
7. CLI polish, golden tests, documentation.

---

## 5. Open questions to discuss

1. **Language/stack.** Python (lxml + `fhir.resources` or plain dicts + the Java validator) is my suggestion. TypeScript or Java/HAPI are alternatives if this needs to fit an existing Sensotrend codebase.
2. **IG versions.** EPS `1.0.0-ballot` (package `hl7.fhir.eu.eps`; the older `hl7.fhir.eu.ps` is superseded?), Lab `2.1.0`, HDR `0.1.0-ballot` vs `1.0.0-alpha`? Should the output also claim the **FinCore** / Finnish national profiles?
3. **Discharge Reports.** The data has no inpatient stays. Options: (a) build the HDR builder and test it with synthetic Kanta CDA fixtures; (b) produce an "encounter report" for outpatient visits (not conformant to HDR's intent); (c) defer HDR until real inpatient data is available. Do you have other exports with osastohoito / epikriisi documents?
4. **Lab codes.** Finnish lab nomenclature codes have no LOINC in the source. The EU lab IG prefers LOINC/NPU. Is there a mapping table we can use (THL/Kuntaliitto → LOINC), or do we ship national codes only?
5. **Grouping of lab reports.** Per lab order (103.21), per source document, or per day/encounter?
6. **EPS scope.** Include all history or a time window (e.g. last N results, active problems only)? How should KER (temporary) diagnoses be handled? Which risk types count as allergies vs. alerts?
7. **Kooste documents.** Use them only as a fallback (my proposal), or treat them as the primary source?
8. **Narrative language.** Keep Finnish displays and narrative only, or also add English displays where mapped?
9. **Other input formats.** Are other payloads expected in future exports (FHIR resources, PDFs, Kanta prescription data)? This decides how much effort goes into the format registry now.
10. **Output.** Separate JSON files per document, or also an ndjson/transaction bundle for loading into a FHIR server?
