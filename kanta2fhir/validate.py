"""Run the HL7 FHIR Validator on generated files and summarise the results (plan §2.7).

Phase 1 (development): ``tx="n/a"``, no terminology checks, offline once packages are cached.
Phase 2 (final): a terminology server, e.g. ``https://tx.fhir.org`` (D13).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kanta2fhir.fhir.profiles import FHIR_VERSION

ROOT = Path(__file__).resolve().parent.parent
VALIDATOR_JAR = ROOT / ".tools" / "validator_cli.jar"
FILE_EXTENSION = "http://hl7.org/fhir/StructureDefinition/operationoutcome-file"


class ValidatorUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class Message:
    severity: str  # fatal, error, warning, information
    location: str
    text: str


@dataclass(slots=True)
class FileResult:
    file: str
    messages: list[Message] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        c = Counter(m.severity for m in self.messages)
        return {s: c.get(s, 0) for s in ("fatal", "error", "warning", "information")}

    @property
    def ok(self) -> bool:
        return self.counts["fatal"] == 0 and self.counts["error"] == 0


def validator_available(jar: Path = VALIDATOR_JAR) -> bool:
    return jar.is_file() and shutil.which("java") is not None


def run_validator(
    files: Sequence[Path],
    packages: Sequence[str],
    output: Path,
    tx: str = "n/a",
    jar: Path = VALIDATOR_JAR,
    timeout: int = 1800,
) -> list[FileResult]:
    """Validate ``files`` against ``packages``; the raw OperationOutcome(s) go to ``output``."""
    if not validator_available(jar):
        raise ValidatorUnavailable(
            f"FHIR validator not found ({jar}) or java not on PATH; "
            "run: uv run python tools/fetch_validator.py"
        )
    if not files:
        return []
    cmd = ["java", "-jar", str(jar), *map(str, files), "-version", FHIR_VERSION]
    for pkg in packages:
        cmd += ["-ig", pkg]
    cmd += ["-tx", tx, "-output", str(output)]
    output.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if not output.is_file():
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-20:])
        raise RuntimeError(f"Validator produced no output (exit {proc.returncode}):\n{tail}")
    return parse_output(json.loads(output.read_text(encoding="utf-8")))


def parse_output(data: dict[str, Any]) -> list[FileResult]:
    """Parse the validator's output: one OperationOutcome, or a Bundle of them."""
    if data.get("resourceType") == "Bundle":
        outcomes = [e["resource"] for e in data.get("entry", [])]
    else:
        outcomes = [data]
    results = []
    for oo in outcomes:
        name = next(
            (
                e.get("valueString")
                for e in oo.get("extension", [])
                if e.get("url") == FILE_EXTENSION
            ),
            "?",
        )
        result = FileResult(file=name)
        for issue in oo.get("issue", []):
            text = (issue.get("details") or {}).get("text") or issue.get("diagnostics") or ""
            if text == "All OK":
                continue
            location = ", ".join(issue.get("expression") or issue.get("location") or [])
            result.messages.append(Message(issue.get("severity", "?"), location, text))
        results.append(result)
    return results


def format_results(results: list[FileResult]) -> str:
    lines = []
    for r in results:
        c = r.counts
        lines.append(
            f"{'OK  ' if r.ok else 'FAIL'} {Path(r.file).name}: {c['error'] + c['fatal']} errors, "
            f"{c['warning']} warnings, {c['information']} info"
        )
    return "\n".join(lines)
