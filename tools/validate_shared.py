"""Build the shared resources (Patient, Organization, Practitioner(Role), Encounter, Provenance)
of an export into a collection Bundle and validate it against the EU base profiles.

This checks the shared factories before the document builders exist (milestone 4).

Usage: uv run python tools/validate_shared.py EXPORT.ndjson [--out out/] [--tx n/a]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kanta2fhir.fhir.datatypes import resource_id
from kanta2fhir.fhir.profiles import EU_CORE, PACKAGES
from kanta2fhir.fhir.resources import ResourceSet
from kanta2fhir.pipeline import run
from kanta2fhir.terminology import Terminology
from kanta2fhir.validate import format_results, run_validator

RECORDED = "2026-01-01T00:00:00+02:00"


def build(path: Path) -> list[dict]:
    bundles = []
    terminology = Terminology()
    for p in run(path).patients:
        rs = ResourceSet(terminology, profiles=EU_CORE)
        patient = rs.patient(p.record.patient)
        encounters = [rs.encounter(e, patient) for e in p.record.encounters.values()]
        authors = [rs.author(a) for doc in p.record.current_documents() for a in doc.header.authors]
        rs.provenance(
            [patient, *encounters],
            [d.id for d in p.record.current_documents()],
            RECORDED,
        )
        bundles.append(
            {
                "resourceType": "Bundle",
                "id": resource_id("Bundle", "shared", p.record.patient.pseudonym),
                "type": "collection",
                "entry": [{"fullUrl": url, "resource": r} for url, r in rs.entries()],
            }
        )
        print(f"{len(rs.resources)} resources, {sum(1 for a in authors if a)} author references")
    return bundles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--tx", default="n/a")
    args = parser.parse_args()

    files = []
    for i, bundle in enumerate(build(args.export)):
        f = args.out / "shared" / f"shared-{i}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        files.append(f)
    results = run_validator(
        files, PACKAGES["base"], args.out / "validation" / "shared.json", tx=args.tx
    )
    print(format_results(results))
    for r in results:
        for m in r.messages:
            if m.severity in ("fatal", "error", "warning"):
                print(f"  {m.severity}: {m.location}: {m.text}")


if __name__ == "__main__":
    main()
