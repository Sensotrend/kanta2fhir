"""Command line interface: ``kanta2fhir INPUT.ndjson --out OUT/``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kanta2fhir import __version__, hetu
from kanta2fhir.coverage import build_report, format_summary
from kanta2fhir.model import Severity
from kanta2fhir.pipeline import run

TARGETS = ("eps", "lab", "hdr")
IMPLEMENTED_TARGETS: tuple[str, ...] = ()  # builders arrive in milestones 5-7


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
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    unknown = [t for t in targets if t not in TARGETS]
    if unknown:
        parser.error(f"unknown target(s): {', '.join(unknown)}")
    if not args.input.is_file():
        parser.error(f"input file not found: {hetu.redact(str(args.input))}")

    result = run(args.input)

    args.out.mkdir(parents=True, exist_ok=True)
    report = build_report(args.input.name, result)
    report_path = args.out / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(format_summary(report))
    for target in targets:
        if target not in IMPLEMENTED_TARGETS:
            print(f"Skipping {target}: not implemented yet")
    print(f"Report written to {report_path}")

    has_errors = any(i["severity"] == Severity.ERROR.value for i in report["issues"])
    return 1 if has_errors and not result.parsed else 0


if __name__ == "__main__":
    sys.exit(main())
