"""A minimal FHIR terminology server client ($lookup, $validate-code).

Only code system URIs, codes and displays are sent, never patient data.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_SERVER = "https://tx.fhir.org/r4"


@dataclass(frozen=True, slots=True)
class LookupResult:
    found: bool
    display: str | None = None
    version: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    display: str | None = None
    message: str | None = None


class TxClient:
    def __init__(self, server: str = DEFAULT_SERVER, timeout: float = 30) -> None:
        self.server = server.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        url = f"{self.server}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url, headers={"Accept": "application/fhir+json", "User-Agent": "kanta2fhir"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                return json.load(e)
            except ValueError:
                return {"resourceType": "OperationOutcome", "issue": [{"diagnostics": str(e)}]}

    @staticmethod
    def _params(d: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for p in d.get("parameter", []):
            for key, value in p.items():
                if key.startswith("value"):
                    out[p["name"]] = value
        return out

    @staticmethod
    def _message(d: dict[str, Any]) -> str | None:
        for issue in d.get("issue", []):
            text = (issue.get("details") or {}).get("text") or issue.get("diagnostics")
            if text:
                return str(text)
        return None

    def lookup(self, system: str, code: str) -> LookupResult:
        d = self._get("CodeSystem/$lookup", {"system": system, "code": code})
        if d.get("resourceType") != "Parameters":
            return LookupResult(found=False, message=self._message(d))
        p = self._params(d)
        return LookupResult(found=True, display=p.get("display"), version=p.get("version"))

    def validate(self, system: str, code: str, display: str | None = None) -> ValidationResult:
        params = {"url": system, "code": code}
        if display:
            params["display"] = display
        d = self._get("CodeSystem/$validate-code", params)
        if d.get("resourceType") != "Parameters":
            return ValidationResult(valid=False, message=self._message(d))
        p = self._params(d)
        return ValidationResult(
            valid=bool(p.get("result")), display=p.get("display"), message=p.get("message")
        )
