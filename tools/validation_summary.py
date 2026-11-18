"""Summarise validator output: group warnings into reviewed categories, flag anything new.

Reads the OperationOutcome files written by ``kanta2fhir --validate`` (``<out>/validation/*.json``)
and prints a Markdown summary. Messages that match no accepted category are listed as
UNREVIEWED, so new problems stand out. Exit code 1 if there are errors or unreviewed warnings.

Usage: uv run python tools/validation_summary.py OUT_DIR [OUT_DIR ...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from kanta2fhir.validate import parse_output

# (pattern, short name, why it is accepted) — see docs/VALIDATION.md
ACCEPTED: list[tuple[str, str, str]] = [
    (
        r"definition for (the )?[Cc]ode ?[Ss]ystem 'urn:oid:",
        "Finnish code system unknown",
        "Kanta code systems (urn:oid:1.2.246…) are not published as FHIR CodeSystems; the "
        "original Finnish codes are kept by design and international codes are added next to them.",
    ),
    (
        r"ValueSet 'http://terminology\.ehdsi\.eu/",
        "eHDSI value set not available",
        "The EU (eHDSI) value sets that EPS/HDR bind to are not served by tx.fhir.org; the "
        "bindings are preferred, not required.",
    ),
    (
        r"is a panel \(Panel\): its results go in hasMember or component",
        "LOINC panel used for a single result",
        "FinOMOP maps two Finnish tests (2522 protein electrophoresis, 1270 EKG) to LOINC panel "
        "codes while the Finnish result is one text value; a mapping-granularity limitation.",
    ),
    (
        r"Found multiple matching profiles for .* among choices",
        "Ambiguous profile choice (validator note)",
        "The validator cannot pick between a base profile and a derived one for a reference; the "
        "resource conforms to both.",
    ),
    (
        r"Unable to validate code .* without terminology services|"
        r"could not be validated in the absence of a terminology server|"
        r"Unable to validate code without using server",
        "No terminology server (offline run)",
        "Only in offline runs (-tx n/a); disappears with a terminology server.",
    ),
]


def categorise(text: str) -> str | None:
    for pattern, name, _ in ACCEPTED:
        if re.search(pattern, text):
            return name
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dirs", nargs="+", type=Path)
    args = parser.parse_args()

    files: list[tuple[str, dict[str, int]]] = []
    accepted: Counter[str] = Counter()
    unreviewed: Counter[tuple[str, str]] = Counter()
    errors: list[str] = []
    for out in args.out_dirs:
        for path in sorted((out / "validation").glob("*.json")):
            for r in parse_output(json.loads(path.read_text(encoding="utf-8"))):
                files.append((f"{out.name}/{path.stem}/{Path(r.file).name}", r.counts))
                for m in r.messages:
                    if m.severity in ("error", "fatal"):
                        errors.append(f"{Path(r.file).name}: {m.location}: {m.text}")
                    elif m.severity == "warning":
                        name = categorise(m.text)
                        if name:
                            accepted[name] += 1
                        else:
                            unreviewed[(m.location.split("/")[0][:60], m.text[:200])] += 1

    print("| File | Errors | Warnings | Info |\n|---|---|---|---|")
    for name, c in files:
        print(f"| {name} | {c['error'] + c['fatal']} | {c['warning']} | {c['information']} |")
    print("\n| Accepted warning category | Count | Reason |\n|---|---|---|")
    reasons = {name: why for _, name, why in ACCEPTED}
    for name, count in accepted.most_common():
        print(f"| {name} | {count} | {reasons[name]} |")
    if unreviewed:
        print("\nUNREVIEWED warnings:")
        for (loc, text), count in unreviewed.most_common():
            print(f"- {count} x {loc}: {text}")
    if errors:
        print("\nERRORS:")
        for e in errors:
            print(f"- {e}")
    sys.exit(1 if errors or unreviewed else 0)


if __name__ == "__main__":
    main()
