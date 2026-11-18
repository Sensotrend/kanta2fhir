"""Regenerate the golden files used by tests/test_golden.py.

Golden files are the expected FHIR documents for the committed test fixtures, built with a
fixed timestamp and *without* the local title cache (so they do not depend on vocab/).
Review the diff (git diff tests/golden) before committing regenerated files.

Usage: uv run python tools/update_golden.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from kanta2fhir.cli import TARGETS, build_documents
from kanta2fhir.pipeline import run
from kanta2fhir.terminology import Terminology

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
GOLDEN = ROOT / "tests" / "golden"
TIMESTAMP = "2026-01-01T12:00:00+02:00"
INPUTS = {
    "sample": FIXTURES / "real" / "sample.ndjson",
    "results": FIXTURES / "real" / "results.ndjson",
    "careplan": FIXTURES / "real" / "careplan.ndjson",
    "inpatient": FIXTURES / "synthetic" / "inpatient.ndjson",
}


def golden_terminology() -> Terminology:
    return Terminology(title_cache=GOLDEN / "no-title-cache.csv")  # deliberately missing


def build(name: str) -> dict[str, dict]:
    """Relative path → document, for one fixture."""
    docs = build_documents(run(INPUTS[name]), list(TARGETS), golden_terminology(), TIMESTAMP)
    return {
        f"{name}/{target}/{stem}.json": bundle
        for target, items in docs.items()
        for stem, bundle in items
    }


def main() -> None:
    shutil.rmtree(GOLDEN, ignore_errors=True)
    for name in INPUTS:
        for rel, bundle in build(name).items():
            path = GOLDEN / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", "utf-8")
            print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
