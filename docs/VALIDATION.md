# Validation results

Final validation (milestone 8, decision D11) on 2026-11-18:

- HL7 FHIR Validator 7.0.6, FHIR 4.0.1
- Terminology server: `https://tx.fhir.org` (D13)
- Packages: `hl7.fhir.eu.eps#1.0.0-ballot`, `hl7.fhir.eu.laboratory#2.1.0`, `hl7.fhir.eu.hdr#1.0.0`
- Inputs: the Kanta test-environment export (`real`, 276 documents, one test patient) and the synthetic inpatient export (`synthetic`, `tests/fixtures/synthetic/inpatient.ndjson`)

**Result: all 6 documents validate with 0 errors.** Every warning falls into one of the accepted categories below. There are no unreviewed warnings.

## How to reproduce

```bash
uv run kanta2fhir kanta_terveystiedot_….ndjson --out out/final/real --validate --tx https://tx.fhir.org
uv run kanta2fhir tests/fixtures/synthetic/inpatient.ndjson --out out/final/synthetic --validate --tx https://tx.fhir.org
uv run python tools/validation_summary.py out/final/real out/final/synthetic
```

`tools/validation_summary.py` exits with code 1 if there are errors, or warnings that match none of the accepted categories, so new problems show up.

Only code system URIs, codes and displays are sent to the terminology server. With real (non-test) exports, use a local terminology server instead of tx.fhir.org.

## Results

| File | Errors | Warnings | Info |
|---|---|---|---|
| real/eps/f39b27dbe100f951.json | 0 | 376 | 344 |
| real/lab/1.2.246.10.1.20241218125532.93.2009.1132917519295184.json | 0 | 7 | 7 |
| real/lab/1.2.246.10.1.20241218125615.93.2009.1132917519546134.json | 0 | 55 | 20 |
| synthetic/eps/34351364f12ac771.json | 0 | 18 | 25 |
| synthetic/hdr/1.2.246.10.99999999.1.2025.100.2.json | 0 | 17 | 18 |
| synthetic/lab/1.2.246.10.99999999.1.2025.101.json | 0 | 12 | 7 |

| Accepted warning category | Count | Reason |
|---|---|---|
| Finnish code system unknown | 459 | Kanta code systems (urn:oid:1.2.246…) are not published as FHIR CodeSystems; the original Finnish codes are kept by design and international codes are added next to them. |
| eHDSI value set not available | 18 | The EU (eHDSI) value sets that EPS/HDR bind to are not served by tx.fhir.org; the bindings are preferred, not required. |
| LOINC panel used for a single result | 4 | FinOMOP maps two Finnish tests (2522 protein electrophoresis, 1270 EKG) to LOINC panel codes while the Finnish result is one text value; a mapping-granularity limitation. |
| Ambiguous profile choice (validator note) | 4 | The validator cannot pick between a base profile and a derived one for a reference; the resource conforms to both. |

The real export has no inpatient stays, so it produces no discharge report.

## Accepted warnings, in more detail

- **Finnish code system unknown.** Kanta's code systems are identified by OIDs and are not available as FHIR CodeSystems on tx.fhir.org, so their codes cannot be checked there. By design (plan §2.4), the Finnish coding is always kept. A LOINC, WHO ICD-10, ATC or SNOMED CT coding is added where a mapping exists, and those international codings *are* checked and pass.
- **eHDSI value set not available.** The EPS and HDR profiles bind conditions, allergies, vaccines and target diseases to EU eHDSI value sets (preferred bindings). tx.fhir.org does not serve them. Checking against them would need the eHDSI terminology server (MTC/CTS).
- **LOINC panel used for a single result.** This is a property of the FinOMOP mapping (plan §2.5): Kuntaliitto codes 2522 (protein electrophoresis) and 1270 (12-lead EKG) are mapped to LOINC panel codes, while the Kanta result is one text statement. The LOINC coding is kept, because it identifies the test. A future option is to leave out LOINC panel codes when the result has a direct value.
- **Ambiguous profile choice.** A validator note about references (Composition ↔ DiagnosticReport, vital-sign Observations): the referenced resource matches both the base and a derived profile.
