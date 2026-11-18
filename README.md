# kanta2fhir

Converts Kanta health record exports into European FHIR documents. The input is a `*.ndjson` file of FHIR `DocumentReference`s with embedded HL7 CDA R2 documents. The output is:

| Document | Implementation guide | One per |
|---|---|---|
| European Patient Summary | `hl7.fhir.eu.eps` 1.0.0-ballot | patient |
| European Laboratory Report | `hl7.fhir.eu.laboratory` 2.1.0 | source lab document |
| European Hospital Discharge Report | `hl7.fhir.eu.hdr` 1.0.0 | inpatient stay |

All generated documents validate with 0 errors against these guides, both offline and with the tx.fhir.org terminology server. See [docs/VALIDATION.md](docs/VALIDATION.md) for the results and the accepted warnings. The design, decisions (D1–D15) and milestones are in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Optional, for validation: Java 17+ and the HL7 FHIR Validator.

```bash
uv run python tools/fetch_validator.py
```

## Usage

```bash
uv run kanta2fhir path/to/export.ndjson --out out/
```

| Option | Meaning |
|---|---|
| `--targets eps,lab,hdr` | Which documents to produce (default: all) |
| `--validate` | Run the HL7 FHIR Validator on the generated documents |
| `--tx URL` | Terminology server for `--validate` (default `n/a`: no terminology checks) |
| `--timestamp T` | Fixed document timestamp, for reproducible output |

Output:

```
out/eps/<patient pseudonym>.json       Patient Summary (Bundle, type document)
out/lab/<source document id>.json      Laboratory Reports
out/hdr/<encounter id>.json            Discharge Reports (inpatient stays only)
out/report.json                        coverage report
out/validation/<target>.json           validator output (with --validate)
```

The exit code is 0 on success. It is 1 if no document could be read or validation found errors, and 2 if the validator is not available.

**Privacy.** The FHIR documents contain the patient's data, as they should. `report.json` and the terminal output do not: no names, no identity codes and no free text. The patient appears only as a pseudonym (a hash of the identity code), and identity codes in file names are masked. Conversion makes no network calls. Only the optional tools below send codes (never patient data) to a terminology server.

## What is converted

| Kanta (CDA) | FHIR |
|---|---|
| Diagnoses (ICD-10 FI) | Condition: active problems vs past problems in the Patient Summary; discharge diagnoses in the Discharge Report |
| Risk information | AllergyIntolerance (with a causative agent or a drug-reaction type), otherwise Flag |
| Immunisations (ATC, VNR) | Immunization, with SNOMED CT target diseases |
| Procedures | Procedure |
| Lab orders and results (Kuntaliitto codes) | ServiceRequest, Observation (+ LOINC via FinOMOP), Specimen, DiagnosticReport |
| Imaging studies and statements | Observation (imaging) |
| Physiological measurements (FinLOINC) | Observation (vital signs or exam) |
| Health and care plan | CarePlan, Goal, CareTeam |
| Section narratives | Section texts; in the Discharge Report, routed by Kanta heading |

Original Finnish codes are always kept. International codes (LOINC, WHO ICD-10, ATC, SNOMED CT) are added next to them, and English names are added as translations. Summary (Kooste) documents are used only for content whose original document is not in the export. Older document versions are ignored.

## Limitations

- Kanta exports contain no structured medication, so the medication sections are empty, with the reason "unavailable". The care plan's free-text medication list is shown as text.
- No real inpatient data was available. The Discharge Report is tested with synthetic data (`tools/make_synthetic_inpatient.py`). Kanta encounter type 1 (Osastohoitojakso) marks an inpatient period, as listed in the national code server.
- The small Finnish code tables (vaccination route and site, vaccine target disease, interpretation, result status, gender) cover the complete code lists from THL Koodistopalvelu, read 2026-11-18 (see `kanta2fhir/terminology/data/kanta_codes.md`). "Other" codes and a few with no equivalent keep only their Finnish coding.
- FinOMOP maps a few Finnish lab codes to LOINC panel codes; see [docs/VALIDATION.md](docs/VALIDATION.md).

## Terminology data

The committed tables in `kanta2fhir/terminology/data/` are built from FinOMOP and an OHDSI Athena LOINC download in `vocab/athena/`:

```bash
uv run python tools/build_terminology.py
```

English titles of WHO ICD-10, ATC and LOINC codes are not redistributed. You can fetch them for your exports into the git-ignored `vocab/tx_titles.csv`; without them, the international codings simply have no display text:

```bash
uv run python tools/fetch_titles.py path/to/export.ndjson
```

To check the hand-made mapping tables, units and the LOINC codes an export uses against tx.fhir.org:

```bash
uv run python tools/verify_terminology.py path/to/export.ndjson
```

See [NOTICE](NOTICE) for attributions (FinOMOP, LOINC).

## Development

```bash
uv run pytest                     # fast tests, including golden files
uv run pytest --run-validator     # also the (slow) validator tests
uv run ruff check . && uv run ruff format .
```

| Tool | Purpose |
|---|---|
| `tools/update_golden.py` | Regenerate `tests/golden/` after an intended output change (review the diff) |
| `tools/validation_summary.py OUT…` | Group validator warnings into accepted categories and flag new ones |
| `tools/make_synthetic_inpatient.py` | Regenerate the synthetic inpatient fixture |
| `tools/validate_shared.py EXPORT` | Validate only the shared resources against EU base |

Code layout:

```
kanta2fhir/reader.py         ndjson → DocumentReference + CDA bytes
kanta2fhir/cda/              CDA header, sections, entry extractors, narrative → XHTML
kanta2fhir/record.py         documents → patients, encounters, versions
kanta2fhir/extract.py        entries → clinical model (model.py)
kanta2fhir/consolidate.py    de-duplication, Kooste fallback
kanta2fhir/terminology/      code mappings, English names, UCUM
kanta2fhir/fhir/             FHIR datatypes, shared resources, eps.py, lab.py, hdr.py
kanta2fhir/validate.py       HL7 FHIR Validator wrapper
kanta2fhir/cli.py            command line
```

Test fixtures in `tests/fixtures/real/` are documents from Kanta's test environment, about a test patient whose identity code is in the test range (900–999). `tests/fixtures/synthetic/` is generated. Real exports (`*.ndjson` in the repository root), `out/`, `vocab/` and `.tools/` are git-ignored.
