# Sources of the hand-made tables

The Finnish code lists were read from THL Koodistopalvelu (https://koodistopalvelu.kanta.fi)
on 2026-11-18. Every target code was checked against tx.fhir.org (tools/verify_terminology.py).

| Table | Kanta code system (version OID) | Codes |
|---|---|---|
| snomed.csv | AR/YDIN - Rokotustapa (1.2.246.537.6.111.2007) | ID, IM, IN, PO, SC mapped; MUU (other) not mapped |
| snomed.csv | AR/YDIN - Pistoskohta (1.2.246.537.6.110.2007) | all 6 sides/sites mapped; MUU not mapped |
| snomed.csv, icd10.csv | THL - Rokotussuoja (1.2.246.537.6.609.201501) | 34 of 38 mapped to both SNOMED CT and WHO ICD-10; 34 Lintuinfluenssa (deprecated) and 91/92/99 (other bacterium/virus/vaccine) not mapped. The ICD-10 coding matters for the EU target-disease binding (eHDSIIllnessandDisorder, ICD-10 based): without it the IG Publisher reports thousands of errors from that value set |
| interpretation.csv | AR/LABRA - Poikkeustilanneviestit (1.2.246.537.5.78.1997) | 33 of 35 identical to HL7 v3 ObservationInterpretation; MIK (header line) and TYHJÄ (no limits defined) not mapped |
| result_status.csv | AR/LABRA - Tutkimusvastauksien tulkintakoodit (1.2.246.537.5.85.1997) | all 10 |
| gender.csv | AR/YDIN - Sukupuoli (1.2.246.537.5.1.1997) | all 5 |

Code lists used by rules in kanta2fhir/fhir/eps.py and hdr.py:

- AR/YDIN - Riskitiedon tyyppi (1.2.246.537.5.40034.2006): hierarchical. A (Muut allergiat), L (Lääkereaktiot ja -allergiat) and the deprecated ALLERG and LAAKRE are allergies or intolerances; the other types (E, H, I, K, M, R, S, V …) are alerts.
- AR/YDIN - Riskitiedon aste (1.2.246.537.5.40033.2006): 1 Kriittinen riski → criticality high, 2 Hoidossa huomioitava riski → low.
- AR/YDIN - Varmuusaste (1.2.246.537.5.40004.2003): TOD and VAR (certain) → confirmed; EP (suspected) and others → provisional / unconfirmed.
- AR/YDIN - Pysyvyys (1.2.246.537.5.40003.2003): PYS → active problem; KER and the deprecated ALU → past problems.
- eArkisto - Palvelutapahtuman laji (1.2.246.537.5.40156.2008): 1 Osastohoitojakso → inpatient (IMP), 2 Avohoitokäyntitieto → ambulatory (AMB).
