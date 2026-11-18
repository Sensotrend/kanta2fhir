"""Check the hand-made mapping tables against a terminology server.

- every SNOMED CT target in snomed.csv exists and has the stated display
- every interpretation target exists in v3-ObservationInterpretation
- every UCUM unit produced from ucum.csv, and from the units in the given exports, is valid
- every LOINC code that the given exports map to exists

Only codes are sent. Exit code 1 if anything fails.

Usage: uv run python tools/verify_terminology.py [EXPORT.ndjson ...] [--server URL]
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from collections.abc import Iterator
from pathlib import Path

from kanta2fhir.model import Quantity
from kanta2fhir.pipeline import run
from kanta2fhir.terminology import Terminology
from kanta2fhir.terminology.lookup import (
    DATA,
    LOINC,
    SNOMED,
    UCUM,
    V3_INTERPRETATION,
    _read,
)
from kanta2fhir.terminology.tx import DEFAULT_SERVER, TxClient

sys.path.insert(0, str(Path(__file__).parent))
from fetch_titles import iter_codings


def iter_quantities(obj: object) -> Iterator[Quantity]:
    if isinstance(obj, Quantity):
        yield obj
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            yield from iter_quantities(getattr(obj, f.name))
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from iter_quantities(item)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("exports", nargs="*", type=Path)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    args = parser.parse_args()

    client = TxClient(args.server)
    terminology = Terminology()
    failures = 0

    def report(ok: bool, what: str, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} {what}{f'  ({detail})' if detail else ''}")

    print("SNOMED CT targets (snomed.csv)")
    for row in _read("snomed.csv", DATA):
        r = client.validate(SNOMED, row["snomed_code"], row["snomed_display"])
        report(r.valid, f"{row['snomed_code']} {row['snomed_display']}", r.message or "")

    print("Interpretation targets (interpretation.csv)")
    for row in _read("interpretation.csv", DATA):
        r = client.validate(V3_INTERPRETATION, row["target_code"], row["target_display"])
        report(r.valid, f"{row['target_code']} {row['target_display']}", r.message or "")

    units = {row["ucum"] for row in _read("ucum.csv", DATA)}
    loinc: dict[str, str | None] = {}
    for path in args.exports:
        for patient in run(path).patients:
            for q in iter_quantities(patient.clinical):
                if q.unit and (u := terminology.ucum(q.unit)):
                    units.add(u)
            for coding in iter_codings(patient.clinical):
                for fc in terminology.equivalents(coding):
                    if fc.system == LOINC:
                        loinc[fc.code] = fc.display

    print("UCUM units")
    for unit in sorted(units):
        r = client.validate(UCUM, unit)
        report(r.valid, unit, r.message or "")

    if loinc:
        print("LOINC codes used by the exports")
        for code, display in sorted(loinc.items()):
            r = client.validate(LOINC, code, display)
            report(r.valid, f"{code} {display or ''}".strip(), r.message or "")

    print(f"{failures} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
