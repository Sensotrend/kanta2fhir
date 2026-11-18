"""Command line interface: ``kanta2fhir INPUT.ndjson --out OUT/``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from kanta2fhir import __version__, hetu
from kanta2fhir.cda.util import HELSINKI
from kanta2fhir.coverage import build_report, format_summary
from kanta2fhir.fhir.datatypes import JSON
from kanta2fhir.fhir.eps import build_patient_summaries
from kanta2fhir.fhir.hdr import build_discharge_reports
from kanta2fhir.fhir.lab import build_lab_reports
from kanta2fhir.fhir.profiles import PACKAGES
from kanta2fhir.model import Severity
from kanta2fhir.pipeline import PatientResult, run
from kanta2fhir.terminology import Terminology
from kanta2fhir.validate import ValidatorUnavailable, format_results, run_validator

TARGETS = ("eps", "lab", "hdr")

Builder = Callable[[PatientResult, Terminology, str], list[tuple[str, JSON]]]
BUILDERS: dict[str, Builder] = {
    "eps": build_patient_summaries,
    "lab": build_lab_reports,
    "hdr": build_discharge_reports,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kanta2fhir",
        description="Convert a Kanta ndjson export into European FHIR documents.",
    )
    parser.add_argument("input", type=Path, help="Kanta export (.ndjson)")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument(
        "--targets",
        default=",".join(TARGETS),
        help="comma-separated documents to produce: eps, lab, hdr (default: all)",
    )
    parser.add_argument(
        "--validate", action="store_true", help="run the HL7 FHIR Validator on the output"
    )
    parser.add_argument(
        "--tx",
        default="n/a",
        help="terminology server for --validate (default: n/a = no terminology checks)",
    )
    parser.add_argument(
        "--timestamp",
        help="document timestamp to use instead of the current time (for reproducible output)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    unknown = [t for t in targets if t not in TARGETS]
    if unknown:
        parser.error(f"unknown target(s): {', '.join(unknown)}")
    if not args.input.is_file():
        parser.error(f"input file not found: {hetu.redact(str(args.input))}")

    result = run(args.input)
    generated_at = args.timestamp or datetime.now(HELSINKI).isoformat(timespec="seconds")

    args.out.mkdir(parents=True, exist_ok=True)
    report = build_report(args.input.name, result)
    report_path = args.out / "report.json"
    _write_json(report_path, report)
    print(format_summary(report))

    terminology = Terminology()
    written: dict[str, list[Path]] = {}
    for target in targets:
        builder = BUILDERS.get(target)
        if builder is None:
            print(f"Skipping {target}: not implemented yet")
            continue
        files = written.setdefault(target, [])
        for patient in result.patients:
            for stem, bundle in builder(patient, terminology, generated_at):
                path = args.out / target / f"{stem}.json"
                _write_json(path, bundle)
                files.append(path)
        print(f"{target}: {len(files)} document(s) written to {args.out / target}")
    print(f"Report written to {report_path}")

    validation_failed = False
    if args.validate:
        for target, files in written.items():
            if not files:
                continue
            print(f"Validating {target} ({len(files)} files, tx={args.tx}) ...")
            try:
                results = run_validator(
                    files, PACKAGES[target], args.out / "validation" / f"{target}.json", tx=args.tx
                )
            except ValidatorUnavailable as e:
                print(str(e), file=sys.stderr)
                return 2
            print(format_results(results))
            validation_failed |= not all(r.ok for r in results)

    has_errors = any(i["severity"] == Severity.ERROR.value for i in report["issues"])
    if has_errors and not result.parsed:
        return 1
    return 1 if validation_failed else 0


def _write_json(path: Path, data: JSON) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
