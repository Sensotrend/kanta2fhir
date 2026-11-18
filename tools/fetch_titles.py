"""Fetch English titles of international codes used in exports, into the local title cache.

WHO ICD-10, WHO ATC and LOINC titles cannot all be redistributed, so they are fetched from a
terminology server into the git-ignored vocab/tx_titles.csv. Only codes are sent.

Usage: uv run python tools/fetch_titles.py EXPORT.ndjson [...] [--server URL]
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
from collections.abc import Iterator
from pathlib import Path

from kanta2fhir.model import Coding
from kanta2fhir.pipeline import run
from kanta2fhir.terminology import Terminology
from kanta2fhir.terminology.lookup import ATC, ICD10_WHO, LOINC, TITLE_CACHE
from kanta2fhir.terminology.tx import DEFAULT_SERVER, TxClient

FETCHED_SYSTEMS = {ICD10_WHO, ATC, LOINC}


def iter_codings(obj: object) -> Iterator[Coding]:
    """Every Coding inside a (nested) dataclass structure."""
    if isinstance(obj, Coding):
        yield obj
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            yield from iter_codings(getattr(obj, f.name))
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from iter_codings(item)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("exports", nargs="+", type=Path)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--cache", type=Path, default=TITLE_CACHE)
    args = parser.parse_args()

    terminology = Terminology()
    wanted: set[tuple[str, str]] = set()
    for path in args.exports:
        for patient in run(path).patients:
            for coding in iter_codings(patient.clinical):
                for fc in terminology.equivalents(coding):
                    if fc.system in FETCHED_SYSTEMS:
                        wanted.add((fc.system, fc.code))

    cache: dict[tuple[str, str], dict[str, str]] = {}
    if args.cache.is_file():
        with args.cache.open(encoding="utf-8", newline="") as f:
            cache = {(r["system"], r["code"]): r for r in csv.DictReader(f)}

    client = TxClient(args.server)
    todo = sorted(wanted - set(cache))
    print(f"{len(wanted)} codes used, {len(todo)} not cached yet")
    for system, code in todo:
        result = client.lookup(system, code)
        cache[(system, code)] = {
            "system": system,
            "code": code,
            "display": result.display or "",
            "version": result.version or "",
            "found": "1" if result.found else "0",
        }
        status = result.display if result.found else f"NOT FOUND ({result.message})"
        print(f"  {system} {code}: {status}")

    args.cache.parent.mkdir(parents=True, exist_ok=True)
    with args.cache.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["system", "code", "display", "version", "found"])
        w.writeheader()
        w.writerows(sorted(cache.values(), key=lambda r: (r["system"], r["code"])))
    print(f"Cache written: {args.cache}")


if __name__ == "__main__":
    main()
