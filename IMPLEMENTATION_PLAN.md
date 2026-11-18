# Kanta CDA → EU FHIR documents: implementation plan

Status: **draft v2: decisions recorded** (2026-11-18). Nothing is implemented yet. §6 has the decision log, and §7 has the remaining open points.

Goal: read a Kanta export (`*.ndjson` of FHIR `DocumentReference`s with embedded documents) and produce three kinds of document, each as a separate FHIR `Bundle` (type `document`) JSON file:

1. **European Patient Summary**: one per patient
2. **European Laboratory Report**: one per source lab document
3. **European Hospital Discharge Report**: one per inpatient stay

Target specifications (FHIR R4 4.0.1):

| Document | Package | Version | Notes |
|---|---|---|---|
| Patient Summary | `hl7.fhir.eu.eps` | `1.0.0-ballot` | Depends on `hl7.fhir.uv.ips` 2.0.0 and `hl7.fhir.eu.base` 2.0.0 |
| Laboratory Report | `hl7.fhir.eu.laboratory` | `2.1.0` | Depends on `hl7.fhir.eu.base` 2.0.1 and IPS 2.0.1 |
| Hospital Discharge Report | `hl7.fhir.eu.hdr` | `1.0.0-alpha` (decided; see §7.1 about 1.0.0) | The alpha is only at `hl7.eu/fhir/hdr/xtehr/package.tgz` and is not in the package registry |

No conformance to the Finnish national profiles (FinCore etc.) is claimed.

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
- `content`: always exactly one attachment, `text/xml`, `language=fi`, base64. **All 276 are HL7 v3 CDA R2** (`ClinicalDocument`, `realmCode=FI`). No other payload formats are expected (decision D9).

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

**Not present in this file:** structured medication (no Kanta prescription or medication-list data), inpatient stays, discharge summaries (epikriisi/loppulausunto), and lab reports carrying LOINC codes.

### Lab documents in detail
- Doc #251 "Laboratorio" (2020.11): one lab order (`103.21` = `…123.22.2`, a **repeating order** valid 2024-12-18 to 2025-12-31 with `repeatNumber=10`) and 10 results, including an EKG ordered through the lab.
- Doc #260 "Laboratorio" (2017.11): a single COVID-19 PCR result **without an order id**.
- Doc #270 "Laboratoriotutkimuskooste": all 11 results again (duplicates).

---

## 2. Architecture

```
ndjson ──► [1 Reader] ──► DocumentReference + decoded CDA
                │
                ▼
         [2 Kanta CDA parser]  (CDA R2 + hl7fi extensions)
                │
                ▼
         Canonical clinical model (per patient)
           Patient, Encounter, Condition, RiskItem, Immunization, Procedure,
           LabOrder, LabResult, Specimen, VitalSign, ImagingResult, CarePlan,
           Narrative blocks, Provenance (source doc id, setId/version)
                │
                ▼
         [3 Consolidation]  de-duplication, versions, Kooste as fallback
                │
                ▼
         [4 Builders]  ─► EPS Bundle   ─► Lab Report Bundles   ─► HDR Bundles
           shared FHIR resource factories + terminology layer (FI + EN)
                │
                ▼
         [5 Validation]  HL7 FHIR Validator: offline first, then with a terminology server
```

Since only CDA payloads are expected (D9), there is no general format-plugin framework. A simple content check rejects anything that is not a Kanta CDA, with a clear error.

### 2.1 Reader
- Streaming line reader. Unwrap `resource`, and tolerate bare resources too.
- Decode `attachment.data` (base64).
- Keep DocumentReference metadata (id, type, category, author, date, related ids, HETU) attached to the payload.

### 2.2 Kanta CDA parser
- Header: patient (name, `CL` = calling name, gender `1.2.246.537.5.1.1997`, birthTime), HETU from the DocumentReference, author, custodian, `encompassingEncounter`, `hl7fi:localHeader` (document type, encounter type, record status, function code).
- Body: walk view → phase → heading sections. Record the section path on every entry, because it is the clinical context (for example "Hoidon arviointi / Diagnoosi").
- Entry dispatch by `(element, code system, code)` and by `templateId`, with one small extractor per entry type. Unknown entries are logged and kept as narrative only.
- Sub-observations (`entryRelationship`) are read through a helper that maps code to value, since Kanta packs attributes there (certainty, permanence, ids, notes).
- CDA narrative (`section/text`) is converted to FHIR XHTML (table/list/paragraph/content mapping, ID references resolved) for Composition section narratives and ED `reference` values.
- Handles both template generations (2015.x and 2020.x).

### 2.3 Consolidation
- **Kooste documents are a fallback only (D7).** Items are taken from the original records first. A Kooste item is used only when no original carries the same identifier or content key, and in that case it is flagged in the coverage report.
- Deduplicate by Kanta unique ids: 2.14 diagnosis episode id, 13.9 risk id, 19.7 immunisation id, 23.6 measurement id, 103.30 lab test id, 103.21 lab order id, entry `id/@root`. Fall back to a content hash of (code, date, value).
- Document versions: `setId` + `versionNumber` and `relatedDocument` RPLC mean only the latest version counts.

### 2.4 Terminology layer (`kanta2fhir/terminology/`, data-driven tables)

**Principle:** keep every original Finnish coding, and *add* international codings (as further `coding`s) wherever a mapping exists. **Displays:** the Finnish display stays primary. An English display is added when one is available (D8), in one of two ways:
- for international code systems (LOINC, ATC, SNOMED CT, UCUM), the coding's own `display` is English;
- for Finnish code systems, the English name is attached with the standard `translation` extension on `Coding.display` (`lang=en`).

| Kanta OID | FHIR system(s) | English source |
|---|---|---|
| `1.2.246.537.6.1.1999` ICD-10 FI | `urn:oid:1.2.246.537.6.1.1999` **plus** `http://hl7.org/fhir/sid/icd-10` when the code is a WHO code | WHO ICD-10 English titles. Finnish 5-character codes (Q32.11) get the parent WHO code's title only as a translation hint, or none |
| `1.2.246.537.6.96.2008` physiological measurements | `http://loinc.org` | LOINC display |
| `1.2.246.537.6.32.2007` ATC | `http://www.whocc.no/atc` | WHO ATC names |
| `1.2.246.537.6.55` VNR | `urn:oid:1.2.246.537.6.55` | Product names are language-neutral |
| `1.2.246.537.6.3.2006` lab nomenclature | `urn:oid:1.2.246.537.6.3.2006` **plus LOINC via the FinOMOP LABfi mapping** (§2.5) | LABfi English `sourceName` (e.g. "P -Creatinine") |
| `1.2.246.537.6.2.2007` procedure classification | `urn:oid:1.2.246.537.6.2.2007` | THL code server, if it provides English |
| `1.2.246.537.5.78.1997` interpretation | `v3-ObservationInterpretation` (H, L, N …) | HL7 display |
| `1.2.246.537.5.85.1997` result status | `Observation.status` (F → final …) | n/a |
| `1.2.246.537.5.1.1997` gender | `administrative-gender` | n/a |
| `1.2.246.537.6.111.2007` / `.110.2007` route and site | `urn:oid:…` + EDQM route / SNOMED site where mappable | EDQM / SNOMED |
| `1.2.246.537.6.609.201501` vaccine target disease | `urn:oid:…` + SNOMED target-disease codes | SNOMED |
| Units | UCUM normalisation (`U/l` → `U/L`, `umol/l` → `umol/L`, `l/min` → `L/min`) | n/a |

Mapping tables are CSV files in the repository, each recording its source and version. Tables that are small or hand-curated (interpretation, status, units, route/site, target disease) are written by hand. Large tables (ICD-10 English titles, ATC names, the LABfi→LOINC map) are produced by build scripts in `tools/`.

### 2.5 Finnish lab codes → LOINC via FinOMOP (D4)
- Source: FinOMOP [`FinOMOP_mappings`](https://github.com/FinOMOP/FinOMOP_mappings), file `VOCABULARIES/LABfi/LABfi.usagi.csv`, with 4,274 rows keyed by the **Kuntaliitto numeric code**. It has columns for the English and Finnish names, `mappingStatus` (APPROVED / UNCHECKED …), `equivalence` and the target OMOP `conceptId`.
- All lab codes in our data are mapped with status APPROVED, for example 4591 P-ASAT → OMOP 3013721 *Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma*, 4600 P-Krea → 3020564, 6466 COVID-19 NAA → 706163, 1270 EKG → 3044889 *12 lead EKG panel*.
- **OMOP concept ids are not LOINC codes.** To get the LOINC code, join with the OMOP `CONCEPT.csv` (vocabulary `LOINC`), which comes from an OHDSI Athena vocabulary download. A one-time script `tools/build_labfi_loinc.py` joins the two and writes `terminology/labfi_loinc.csv` (`kuntaliitto_code, name_fi, name_en, loinc_code, loinc_display, mapping_status, equivalence, source_version`). The derived CSV is committed, but Athena downloads are not.
- Use: add the LOINC coding to `Observation.code` only when `mappingStatus = APPROVED`. The Finnish code remains the first coding. The FinOMOP `equivalence` is mostly `UNREVIEWED`, so this is a best-effort mapping, and the coverage report says so.
- The LABfi English names give the English display for the Finnish code itself, whether or not a LOINC mapping exists.
- Caveat: OMOP mappings are analyte-level, so method, specimen or unit nuances of the Finnish code may be lost. The original code stays in the resource.

### 2.6 Builders

**Shared:** Patient (EU core plus HETU identifier `urn:oid:1.2.246.21`), Organization/Practitioner/PractitionerRole from authors, Encounter from service events, Provenance pointing to the source DocumentReference ids, deterministic resource ids (UUIDv5 from Kanta ids) so reruns are stable, and Composition section narratives generated from the resources, with the original CDA narrative optionally appended.

#### A. European Patient Summary (`hl7.fhir.eu.eps` 1.0.0-ballot)
One `Bundle(type=document)` per patient with **all** history included (D6). Sections are emitted **in the order the Composition profile defines them**, as below. Sections marked *required* are always emitted, with `emptyReason` when there is no data; other sections are emitted only when they have content.

| # | Slice (EPS order) | LOINC | Card. | Content from this data |
|---|---|---|---|---|
| 1 | sectionProblems | 11450-4 | **1..1** | **Active** problems: diagnoses with permanence PYS that are not resolved |
| 2 | sectionAllergies | 48765-2 | **1..1** | Risk items of the allergy/intolerance kind (risk type L* with an agent, e.g. ketoprofen) → AllergyIntolerance; else `emptyReason` |
| 3 | sectionMedications | 10160-0 | **1..1** | No structured data → `emptyReason` = unavailable. Care-plan medication list only as narrative |
| 4 | sectionImmunizations | 11369-6 | 0..1 | Immunization |
| 5 | sectionResults | 30954-2 | 0..1 | Lab results (all, latest first) + imaging results |
| 6 | sectionProceduresHx | 47519-4 | **1..1** (EPS is stricter than IPS here) | Procedure, deduplicated |
| 7 | sectionMedicalDevices | 46264-8 | **1..1** (EPS is stricter than IPS here) | No data → `emptyReason` |
| 8 | sectionAdvanceDirectives | 42348-3 | 0..1 | — |
| 9 | sectionAlert | 104605-1 | 0..1 | Other (non-allergy) risk items → Flag |
| 10 | sectionFunctionalStatus | 47420-5 | 0..1 | — |
| 10b | **Past problems** (IPS `sectionPastProblems`) | 11348-0 | 0..1 | **All other diagnoses**: temporary (KER) and non-active ones. See §7.2 |
| 11 | sectionPregnancyHx | 10162-6 | 0..1 | — |
| 12 | sectionPatientStory | 81338-6 | 0..1 | — |
| 13 | sectionPlanOfCare | 18776-5 | 0..1 | Health and care plan → CarePlan + Goals |
| 14 | sectionSocialHistory | 29762-2 | 0..1 | — |
| 15 | sectionVitalSigns | 8716-3 | 0..1 | Physiological measurements (weight, PEF …) → vital-sign Observations |
| 16 | sectionTravelHx | 10182-4 | 0..1 | — |
| 17 | sectionPatientHx | 11329-0 | 0..1 | — |

The order above is EPS's own order, read from `StructureDefinition-composition-eu-eps.json`. It matches IPS 2.0.0, with EPS adding Travel and Patient History at the end. The order is generated from the profile file rather than hard-coded, so it follows the profile if the profile changes.

Problems vs. past problems (D6, may be revisited): **active** means permanence PYS (pysyväisluonteinen) and not marked resolved. Everything else, including KER (määräaikainen, temporary) diagnoses, goes to past problems with `clinicalStatus` inactive/resolved. The rule lives in one function so it is easy to change.

#### B. European Laboratory Report (`hl7.fhir.eu.laboratory` 2.1.0)
**One `Bundle(type=document)` per source lab document (D5).** The latest version per `setId` is used, and Kooste lab summaries are used only for results missing from the originals.
- `Composition` (lab report type, section per study/specialty), `DiagnosticReport-eu-lab`, `ServiceRequest` per lab order (organizer 27: requester, reason/note "Oireeton potilas", repeat period and count), `Observation` result profile (value PQ/ST/CD, interpretation, referenceRange incl. text 103.27, performer from 103.28, issued from 103.13, note 103.24), `Specimen` from `specimenPlayingEntity` (system abbreviation `1.2.246.537.6.17.2004`).
- ServiceRequest ids are derived from the Kanta order id (103.21). A repeating order that leads to several documents is therefore **one shared ServiceRequest** referenced by several reports, which keeps the order-level view recoverable.
- Results without an order id (doc #260) get a report with no `basedOn`.
- The EKG ordered through the lab (1270 / FP1B5) is kept in the report as an Observation with its LOINC panel code (OMOP 3044889 → LOINC 34534-8). It is listed in the coverage report as non-lab content.

Why per document rather than per order (answer to Q5):
- **A repeating order produces many documents.** Our doc #251 order is valid for a year with up to 10 repetitions, so each sampling round is typically recorded as its own lab document under the same order id. Grouping per order would merge a year of results into one "report".
- **Results of one order arrive at different times.** Fast chemistry comes the same day, while cultures or send-out tests to a reference lab come days later. Each is recorded when it is ready, often as a separate document.
- **Preliminary → final.** A preliminary result (qualifier status P) can later be followed by a final one, either as a new version (same `setId`, which the version handling covers) or as a new document.
- **One document can contain several orders.** The opposite also happens, for example tests ordered by different requesters in the same visit.
- The source document is the unit that was signed and archived. Mapping it 1:1 to a report keeps provenance simple: one source document gives one FHIR document.

#### C. European Hospital Discharge Report (`hl7.fhir.eu.hdr` 1.0.0-alpha)
One `Bundle(type=document)` per **inpatient** episode.
- Trigger: a service event whose encounter type is inpatient (`hl7fi:encompassingEncounterCode` = osastohoitojakso, the exact code to be confirmed from the Kanta code list), together with the record entries linked through `context.related` / encounter id.
- Content: Encounter (admission/discharge, period, service provider), admission reason and discharge diagnoses (PAA/SIVU), procedures, significant results, medication at discharge, allergies, plan of care / follow-up, and the narrative "Hospital course" from the Kertomusteksti sections.
- **Synthetic test data (D3):** no real inpatient data is available. `tests/fixtures/synthetic/` will contain hand-made Kanta-style CDA documents (an inpatient service event, a ward record entry, discharge diagnoses, a discharge summary narrative and medication at discharge) packed into an ndjson that matches the real envelope. They are based on the real documents' structure, with the CDA templates and codes taken from the real file. The real file produces zero HDR documents, which is the expected and tested result.

### 2.7 Validation (D11)
- IG packages are pinned in `igs/packages.lock` and downloaded by `tools/fetch_igs.py`: EPS 1.0.0-ballot, Lab 2.1.0, HDR 1.0.0-alpha (from the hl7.eu xtehr URL), plus their dependencies.
- HL7 FHIR Validator (`validator_cli.jar`, needs Java 17 or newer), run per target with that target's IG.
- **Phase 1 (development):** `-tx n/a`, no terminology checks. This is fast and offline, and it is the default for `make validate` and in tests.
- **Phase 2 (final acceptance):** run with a terminology server: `tx.fhir.org` by default, or a local server (`-tx <url>`) if preferred. Only codes are sent to the server, not patient data. Even so, with real (non-test) exports the run must use a local terminology server. Expect warnings for Finnish `urn:oid` code systems that the server does not know, and record which are accepted.
- Results are stored as validator `OperationOutcome`s plus a summary table of errors and warnings per file, in `out/validation/`.

### 2.8 Tests
- Unit tests per extractor, using small CDA fixtures cut from the real file (it is test data).
- Golden-file tests: whole ndjson → expected bundles, which stable ids make possible.
- Synthetic inpatient fixtures for HDR.
- Coverage report: per input document, what was mapped, skipped, not understood or taken from Kooste.

### 2.9 CLI and output (D10)
```
kanta2fhir INPUT.ndjson --out OUT/ [--targets eps,lab,hdr] [--validate [--tx URL|n/a]] [--no-source-narrative]
```
Output, one JSON Bundle per document:
```
OUT/eps/<patient-id>.json
OUT/lab/<source-document-id>.json
OUT/hdr/<encounter-id>.json
OUT/report.json            (coverage + consolidation log)
OUT/validation/…           (when --validate)
```

Privacy: real exports contain HETUs and health data. No PHI in logs (ids hashed), `*.ndjson` and `out/` are git-ignored, and only codes go to a terminology server.

---

## 3. Stack and project layout (D1: Python)

- Python ≥ 3.12, managed with **uv** (`pyproject.toml`, lockfile).
- `lxml` for CDA (XPath, namespaces, narrative conversion).
- FHIR resources as **`fhir.resources`** (pydantic models, R4B/R4 package) for type safety while learning. The alternative, plain dicts, is simpler but gives no checking. Decide at milestone 1 whether `fhir.resources`' R4 support is good enough; the HL7 validator remains the authority either way.
- `pytest`, `ruff` (lint and format), `mypy` optional.
- Java 17+ only for the validator.

```
pyproject.toml
kanta2fhir/
  reader.py                  ndjson + DocumentReference unwrapping
  cda/                       header.py, sections.py, narrative.py, util.py (sub-observation helper)
  cda/entries/               diagnosis.py, risk.py, immunization.py, procedure.py,
                             lab.py, imaging.py, vitals.py, careplan.py
  model.py                   canonical dataclasses
  consolidate.py             dedup, versions, Kooste fallback
  terminology/               lookup.py + *.csv mapping tables
  fhir/common.py             Patient, Org, Practitioner, Provenance, ids, narrative
  fhir/eps.py  fhir/lab.py  fhir/hdr.py
  validate.py                validator wrapper
  cli.py
tools/                       fetch_igs.py, build_labfi_loinc.py, other table builders
igs/packages.lock
tests/  tests/fixtures/{real,synthetic}/
```

## 4. Milestones

1. Project skeleton (uv, ruff, pytest), reader, CDA header parsing, canonical Patient/Encounter, and a coverage report over the whole file.
2. Entry extractors (diagnosis, risk, immunisation, procedure, lab, vitals, imaging, care plan) + narrative conversion + consolidation/dedup (Kooste fallback, versions).
3. Terminology layer: hand-made tables, ICD-10/ATC English, the LABfi→LOINC build script and table, UCUM normalisation, FI/EN displays.
4. Shared FHIR factories + validator wrapper (`-tx n/a`) + IG fetch.
5. **Lab Report** builder → validates with no errors (offline).
6. **EPS** builder → validates with no errors (offline).
7. Synthetic inpatient fixtures + **HDR** builder → validates with no errors (offline).
8. Final validation **with a terminology server**, fixes, documentation of accepted warnings; CLI polish, golden tests, README.

## 5. Out of scope (for now)
- Other payload formats (D9), Finnish national profile conformance (D2), medication data sources beyond what is in the CDA, and loading the output into a FHIR server.

---

## 6. Decision log

| # | Topic | Decision (2026-11-18) |
|---|---|---|
| D1 | Language | Python |
| D2 | IG versions | EPS 1.0.0-ballot, Lab 2.1.0, HDR 1.0.0-alpha; no Finnish national profile conformance |
| D3 | HDR test data | Synthetic Kanta-style CDA fixtures |
| D4 | Finnish lab codes | Use the FinOMOP LABfi (OMOP) mapping to add LOINC codings (§2.5) |
| D5 | Lab report grouping | One report per source document (reasoning in §2.6 B) |
| D6 | EPS scope | Include everything. Active problems → Problems, all others (including temporary) → Past problems. Sections in profile order. May be revisited |
| D7 | Kooste documents | Fallback only |
| D8 | Language | Finnish primary; add English displays where available |
| D9 | Input formats | Kanta CDA only; no format-plugin framework |
| D10 | Output | Separate JSON Bundle file per document |
| D11 | Validation | Develop without terminology checks; final results checked with a terminology server |

## 7. Open points

1. **HDR version.** `hl7.fhir.eu.hdr` **1.0.0** (STU 1, package dated 2026-10-16) is now in the FHIR package registry and is newer than 1.0.0-alpha (2026-02-25). The alpha depends on `hl7.fhir.eu.base` 2.0.0-gamma, while EPS and Lab use eu.base 2.0.0 / 2.0.1, which may cause dependency clashes in validation. **Proposal: target HDR 1.0.0 instead of 1.0.0-alpha.** Needs your OK.
2. **Past problems section in EPS.** EPS 1.0.0-ballot **does not define** the IPS `sectionPastProblems` (11348-0) slice. Its Composition is based on EU core, not on the IPS Composition. Section slicing is *open*, so an extra section coded 11348-0 is allowed, placed at its IPS position between Functional status and Pregnancy history. The validator may then report it as an unrecognised (non-slice) section, as information or a warning. Alternatives: put past problems into `sectionPatientHx` (11329-0), or keep them in `sectionProblems` with `clinicalStatus` inactive/resolved. **Proposal: emit the 11348-0 section as planned and review the validator output.**
3. **FinOMOP mapping licence.** The `FinOMOP_mappings` repository declares no licence. Before committing the derived `labfi_loinc.csv`, check the terms with FinOMOP, or keep the table out of the repository and generate it locally.
4. **Athena access.** Joining OMOP concept ids to LOINC codes needs an OHDSI Athena vocabulary download (free account; LOINC terms accepted on download). Can you do the download, or is there another source of the OMOP `CONCEPT` table you already use?
5. **Terminology server for final validation.** Is `tx.fhir.org` acceptable for the test data, or should we set up a local one (e.g. Ontoserver/Snowstorm) from the start?
