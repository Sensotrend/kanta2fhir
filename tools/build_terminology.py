"""Build the committed terminology tables from FinOMOP and an OHDSI Athena download.

Outputs (in kanta2fhir/terminology/data/):
- labfi.csv: Kuntaliitto lab codes → English name, FinOMOP mapping status, LOINC code
- icd10fi.csv: Finnish-only ICD-10 codes → Finnish and English names
- sources.json: what the tables were built from

Inputs:
- FinOMOP_mappings at a pinned commit (downloaded from GitHub)
- Athena vocabulary bundle with LOINC, unzipped into vocab/athena/ (CONCEPT.csv, VOCABULARY.csv)

Usage: uv run python tools/build_terminology.py [--athena vocab/athena]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

FINOMOP_REPO = "FinOMOP/FinOMOP_mappings"
FINOMOP_COMMIT = "46594187ee0d84a8e34277dcbbc2697207af4abe"  # 2026-11-12
LABFI_PATH = "VOCABULARIES/LABfi/LABfi.usagi.csv"
ICD10FI_PATH = "VOCABULARIES/ICD10fi/ICD10fi.usagi.csv"

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "kanta2fhir" / "terminology" / "data"


def fetch_finomop(path: str) -> list[dict[str, str]]:
    url = f"https://raw.githubusercontent.com/{FINOMOP_REPO}/{FINOMOP_COMMIT}/{path}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        text = resp.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def read_loinc_concepts(athena: Path, wanted: set[str]) -> dict[str, dict[str, str]]:
    """concept_id → row, for the wanted LOINC concepts (CONCEPT.csv is tab-separated)."""
    csv.field_size_limit(sys.maxsize)
    out = {}
    with (athena / "CONCEPT.csv").open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row["concept_id"] in wanted and row["vocabulary_id"] == "LOINC":
                out[row["concept_id"]] = row
    return out


def athena_versions(athena: Path) -> dict[str, str]:
    csv.field_size_limit(sys.maxsize)
    with (athena / "VOCABULARY.csv").open(encoding="utf-8", newline="") as f:
        rows = {
            r["vocabulary_id"]: r["vocabulary_version"] for r in csv.DictReader(f, delimiter="\t")
        }
    return {"omop": rows.get("None", ""), "loinc": rows.get("LOINC", "")}


def build_labfi(athena: Path) -> dict[str, int]:
    rows = fetch_finomop(LABFI_PATH)
    wanted = {r["conceptId"] for r in rows if r["mappingStatus"] == "APPROVED"}
    concepts = read_loinc_concepts(athena, wanted)

    by_code: dict[str, dict[str, str]] = {}
    stats = {"rows": len(rows), "codes": 0, "approved": 0, "loinc": 0, "loinc_invalid": 0}
    for r in rows:
        code = r["sourceCode"].strip()
        entry = by_code.setdefault(
            code,
            {
                "code": code,
                "name_fi": r.get("ADD_INFO:sourceName_fi", "").strip(),
                "name_en": r["sourceName"].strip(),
                "mapping_status": r["mappingStatus"],
                "equivalence": r["equivalence"],
                "omop_concept_id": "",
                "loinc_code": "",
                "loinc_display": "",
            },
        )
        if r["mappingStatus"] != "APPROVED" or entry["loinc_code"]:
            continue
        entry["mapping_status"] = "APPROVED"
        entry["equivalence"] = r["equivalence"]
        concept = concepts.get(r["conceptId"])
        if concept is None:
            continue
        if concept["invalid_reason"]:
            stats["loinc_invalid"] += 1
            continue
        entry["omop_concept_id"] = r["conceptId"]
        entry["loinc_code"] = concept["concept_code"]
        entry["loinc_display"] = concept["concept_name"]

    stats["codes"] = len(by_code)
    stats["approved"] = sum(1 for e in by_code.values() if e["mapping_status"] == "APPROVED")
    stats["loinc"] = sum(1 for e in by_code.values() if e["loinc_code"])
    _write(OUT / "labfi.csv", list(by_code.values()))
    return stats


def build_icd10fi() -> dict[str, int]:
    rows = fetch_finomop(ICD10FI_PATH)
    by_code: dict[str, dict[str, str]] = {}
    for r in rows:
        code = r["sourceCode"].strip()
        by_code.setdefault(
            code,
            {
                "code": code,
                "name_fi": r.get("ADD_INFO:sourceName_fi", "").strip(),
                "name_en": r["sourceName"].strip(),
            },
        )
    _write(OUT / "icd10fi.csv", list(by_code.values()))
    return {"rows": len(rows), "codes": len(by_code)}


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: r["code"])
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--athena", type=Path, default=ROOT / "vocab" / "athena")
    args = parser.parse_args()
    if not (args.athena / "CONCEPT.csv").is_file():
        sys.exit(f"Athena CONCEPT.csv not found in {args.athena}")

    labfi = build_labfi(args.athena)
    icd10fi = build_icd10fi()
    sources = {
        "built": date.today().isoformat(),
        "finomop": {"repository": FINOMOP_REPO, "commit": FINOMOP_COMMIT},
        "athena": athena_versions(args.athena),
        "labfi": labfi,
        "icd10fi": icd10fi,
    }
    (OUT / "sources.json").write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(sources, indent=2))


if __name__ == "__main__":
    main()
