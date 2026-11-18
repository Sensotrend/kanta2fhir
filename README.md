# kanta2fhir

Converts Kanta health record exports (`*.ndjson` files of FHIR `DocumentReference`s with embedded HL7 CDA R2 documents) into European FHIR documents:

- European Patient Summary (`hl7.fhir.eu.eps` 1.0.0-ballot)
- European Laboratory Report (`hl7.fhir.eu.laboratory` 2.1.0)
- European Hospital Discharge Report (`hl7.fhir.eu.hdr` 1.0.0)

The design, decisions and milestones are in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

**Status:** milestones 1-5 are done: reading, CDA parsing, patient/encounter assembly, extraction of all clinical entries (diagnoses, risks, immunisations, procedures, lab and imaging orders and results, vital signs, care plan, narratives), de-duplication, a coverage report, and the terminology layer (LOINC for Finnish lab codes, WHO ICD-10/ATC/SNOMED CT equivalents, English names, UCUM units), shared FHIR resource factories with a validator wrapper, and **European Laboratory Report** documents. The Patient Summary and Discharge Report builders are next. No FHIR documents are produced yet.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Usage

```bash
uv run kanta2fhir path/to/export.ndjson --out out/
```

Documents are written to `out/<target>/` (currently `out/lab/`). Add `--validate` to run the HL7 FHIR Validator on them (no terminology checks by default; `--tx https://tx.fhir.org` for a terminology server), and `--timestamp` for reproducible output.

It also writes `out/report.json`, a coverage report of what the export contains and what has been mapped, and prints a short summary. The report contains no names or personal identity codes; the patient is identified by a pseudonym (a hash of the identity code).

## Terminology data

The committed tables in `kanta2fhir/terminology/data/` are built with:

```bash
uv run python tools/build_terminology.py   # needs an Athena LOINC bundle in vocab/athena/
```

English titles of WHO ICD-10, ATC and LOINC codes are not redistributed. Fetch them for your exports into the git-ignored `vocab/tx_titles.csv` (only codes are sent to the terminology server):

```bash
uv run python tools/fetch_titles.py path/to/export.ndjson
```

To check the hand-made mapping tables, units and LOINC codes against tx.fhir.org:

```bash
uv run python tools/verify_terminology.py path/to/export.ndjson
```

See [NOTICE](NOTICE) for attributions (FinOMOP, LOINC).

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

Validation needs Java 17+ and the HL7 FHIR Validator:

```bash
uv run python tools/fetch_validator.py
uv run pytest --run-validator          # includes the (slow) validator tests
uv run python tools/validate_shared.py path/to/export.ndjson
```

Test fixtures in `tests/fixtures/real/` are documents from Kanta's test environment, about a test patient whose identity code is in the test range. Real exports (`*.ndjson` in the repository root) and generated output (`out/`) are git-ignored.
