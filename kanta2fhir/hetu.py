"""Finnish personal identity code (henkilötunnus, HETU) helpers."""

from __future__ import annotations

import hashlib
import re
from datetime import date

HETU_OID = "1.2.246.21"

_CENTURY = {"+": 1800, "-": 1900, "Y": 1900, "X": 1900, "W": 1900, "V": 1900, "U": 1900}
_CENTURY.update({c: 2000 for c in "ABCDEF"})
_CHECK_CHARS = "0123456789ABCDEFHJKLMNPRSTUVWXY"
_PATTERN = re.compile(r"^(\d{2})(\d{2})(\d{2})([-+A-FU-Y])(\d{3})([0-9A-Y])$")


def is_valid(hetu: str) -> bool:
    """Check format, date and check character."""
    m = _PATTERN.match(hetu)
    if not m:
        return False
    dd, mm, yy, sign, num, check = m.groups()
    try:
        date(_CENTURY[sign] + int(yy), int(mm), int(dd))
    except ValueError:
        return False
    return _CHECK_CHARS[int(dd + mm + yy + num) % 31] == check


def birth_date(hetu: str) -> str | None:
    """Birth date as ``YYYY-MM-DD``, or None if the HETU is not valid."""
    if not is_valid(hetu):
        return None
    dd, mm, yy, sign = hetu[0:2], hetu[2:4], hetu[4:6], hetu[6]
    return f"{_CENTURY[sign] + int(yy):04d}-{mm}-{dd}"


def sex(hetu: str) -> str | None:
    """``"male"`` or ``"female"`` from the individual number, or None if not valid."""
    if not is_valid(hetu):
        return None
    return "male" if int(hetu[7:10]) % 2 else "female"


def is_test_hetu(hetu: str) -> bool:
    """Individual numbers 900-999 are reserved for test use."""
    return is_valid(hetu) and int(hetu[7:10]) >= 900


_ANYWHERE = re.compile(r"\d{6}[-+A-FU-Y]\d{3}[0-9A-Y]")


def redact(text: str) -> str:
    """Replace anything that looks like a valid HETU with ``<hetu>``.

    Kanta export file names contain the patient's HETU, so names and paths must be
    redacted before they go into reports or logs.
    """
    return _ANYWHERE.sub(lambda m: "<hetu>" if is_valid(m.group(0)) else m.group(0), text)


def pseudonym(hetu: str) -> str:
    """A stable, non-reversible-in-practice id for reports and logs."""
    return hashlib.sha256(f"kanta2fhir:{hetu}".encode()).hexdigest()[:16]
