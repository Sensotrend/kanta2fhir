# kanta2fhir

Converts Kanta health record exports (`*.ndjson` files of FHIR `DocumentReference`s with embedded HL7 CDA R2 documents) into European FHIR documents:

- European Patient Summary (`hl7.fhir.eu.eps` 1.0.0-ballot)
- European Laboratory Report (`hl7.fhir.eu.laboratory` 2.1.0)
- European Hospital Discharge Report (`hl7.fhir.eu.hdr` 1.0.0)

The design, decisions and milestones are in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

**Status:** milestone 1 is done (reader, CDA header parsing, patient/encounter assembly, coverage report). No FHIR documents are produced yet.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Usage

```bash
uv run kanta2fhir path/to/export.ndjson --out out/
```

This writes `out/report.json`, a coverage report of what the export contains and what has been mapped, and prints a short summary. The report contains no names or personal identity codes; the patient is identified by a pseudonym (a hash of the identity code).

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

Test fixtures in `tests/fixtures/real/` are documents from Kanta's test environment, about a test patient whose identity code is in the test range. Real exports (`*.ndjson` in the repository root) and generated output (`out/`) are git-ignored.
