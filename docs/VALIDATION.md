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
| Ambiguous profile choice (validator note) | 4 | The validator cannot pick between a base profile and a derived one for a reference; the resource conforms to both. |

The real export has no inpatient stays, so it produces no discharge report.

## Accepted warnings, in more detail

- **Finnish code system unknown.** Kanta's code systems are identified by OIDs and are not available as FHIR CodeSystems on tx.fhir.org, so their codes cannot be checked there. By design (plan §2.4), the Finnish coding is always kept. A LOINC, WHO ICD-10, ATC or SNOMED CT coding is added where a mapping exists, and those international codings *are* checked and pass.
- **eHDSI value set not available.** The EPS and HDR profiles bind conditions, allergies, vaccines and target diseases to EU eHDSI value sets (preferred bindings). tx.fhir.org does not serve them. Checking against them would need the eHDSI terminology server (MTC/CTS).
- **LOINC panel used for a single result** (fixed 2026-11-19). FinOMOP maps 48 Kuntaliitto codes to LOINC panel codes, among them 2522 (protein electrophoresis) and 1270 (12-lead EKG); the Kanta result is one value. The build script now flags panels: Athena records them as concepts with "Panel contains" relationships. A result Observation leaves out a LOINC panel code, while a ServiceRequest keeps it, since ordering a panel is what panel codes are for. The category has been removed from `tools/validation_summary.py`, so a recurrence shows up as unreviewed.
- **Ambiguous profile choice.** A validator note about references (Composition ↔ DiagnosticReport, vital-sign Observations): the referenced resource matches both the base and a derived profile.

## IG Publisher check (2026-11-19)

The examples were also checked with the HL7 IG Publisher (3.0.4) in a local test IG (`ig/`, dependencies `hl7.fhir.eu.eps#current`, `hl7.fhir.uv.ips`, `hl7.fhir.eu.base`, `hl7.fhir.fi.base`). Unlike the validator CLI, the Publisher uses the HL7 terminology ecosystem. The ecosystem resolves the eHDSI value sets from **tx.hl7europe.eu**.

- **Problem found:** 13,620 errors in the Patient Summary. All came from the EU target-disease binding (`eHDSIIllnessandDisorder|0.2.0`, an additional binding in EU base). That value set includes ICD-10 codes that are not in WHO ICD-10 (e.g. `I70.20`, `M00.00`), so it fails to expand and every check against it errors. It was triggered by Immunization target diseases coded only with Finnish and SNOMED CT codes. Conditions were not affected, because they carry a WHO ICD-10 coding.
- **Fix:** vaccine target diseases now also get a WHO ICD-10 coding (`kanta2fhir/terminology/data/icd10.csv`, all 34 codes verified on tx.fhir.org). Tests with the Publisher confirmed it: target diseases without codings, or with an ICD-10 coding, give 0 errors; SNOMED CT alone gives the 13,620 errors.
- **Result:** 0 validation errors for all four examples. The remaining warnings are the accepted categories above, plus "No definition could be found for URL value 'urn:oid:…'" for Kanta OIDs used as identifier systems.
- **4 broken links** (fixed): the Publisher's rendering of each document's Provenance linked to the Composition, and the Publisher creates no anchor for a document bundle's first entry. Provenance now targets the resources converted from the Kanta documents (diagnoses, results, immunisations …) instead of the Composition. That also states more precisely what was derived from the sources. The IG now builds with 0 errors, 0 build errors and 0 broken links.
