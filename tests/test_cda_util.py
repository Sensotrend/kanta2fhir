import pytest
from lxml import etree

from kanta2fhir.cda.util import (
    NotCdaError,
    coding,
    human_name,
    identifier,
    parse_cda,
    period,
    ts_to_fhir,
)
from kanta2fhir.model import Coding, Identifier


def xml(snippet: str) -> etree._Element:
    return etree.fromstring(f'<x xmlns="urn:hl7-org:v3">{snippet}</x>')[0]


@pytest.mark.parametrize(
    ("ts", "expected"),
    [
        ("2024", "2024"),
        ("202412", "2024-12"),
        ("20241218", "2024-12-18"),
        ("20241218125527", "2024-12-18T12:55:27+02:00"),  # winter: EET
        ("20240618125527", "2024-06-18T12:55:27+03:00"),  # summer: EEST
        ("202412181255", "2024-12-18T12:55:00+02:00"),
        ("20241218125527.123", "2024-12-18T12:55:27.123+02:00"),
        ("20241218125527+0000", "2024-12-18T12:55:27+00:00"),
        ("20241218125527-0500", "2024-12-18T12:55:27-05:00"),
        ("20241318", "2024-13-18"),  # date-only values are passed through by format
        ("2024121812", "2024-12-18T12:00:00+02:00"),
        ("not a date", None),
        ("", None),
        (None, None),
    ],
)
def test_ts_to_fhir(ts: str | None, expected: str | None) -> None:
    assert ts_to_fhir(ts) == expected


def test_ts_to_fhir_invalid_datetime() -> None:
    assert ts_to_fhir("20241232120000") is None


def test_coding_and_null_flavor() -> None:
    el = xml('<code code="1" codeSystem="1.2.246.537.5.1.1997" displayName=" Mies "/>')
    assert coding(el) == Coding(code="1", system="1.2.246.537.5.1.1997", display="Mies")
    assert coding(xml('<code nullFlavor="NA"/>')) is None
    assert coding(None) is None


def test_identifier_masked() -> None:
    assert identifier(xml('<id root="1.2.246.21" extension="****"/>')) == Identifier(
        system="1.2.246.21", value=None, masked=True
    )
    assert identifier(xml('<id root="1.2.3"/>')) == Identifier(system="1.2.3")
    assert identifier(xml('<id nullFlavor="NA"/>')) is None


def test_human_name_calling_name() -> None:
    name = human_name(
        xml(
            "<name><given>Testi</given><given qualifier='CL'>Testi</given>"
            "<family>Potilas</family><suffix>LL</suffix></name>"
        )
    )
    assert name is not None
    assert name.given == ("Testi",)
    assert name.calling_name == "Testi"
    assert name.family == ("Potilas",)
    assert name.suffix == ("LL",)


def test_period_low_high_and_null() -> None:
    p = period(
        xml('<effectiveTime><low value="20241218090000"/><high value="20241219"/></effectiveTime>')
    )
    assert p is not None
    assert (p.start, p.end) == ("2024-12-18T09:00:00+02:00", "2024-12-19")
    assert period(xml('<effectiveTime nullFlavor="NA"/>')) is None


def test_parse_cda_rejects_other_xml_and_entities() -> None:
    with pytest.raises(NotCdaError):
        parse_cda(b"<html/>")
    with pytest.raises(NotCdaError):
        parse_cda(b"not xml")
    # External entities are not resolved.
    doc = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        b'<ClinicalDocument xmlns="urn:hl7-org:v3"><title>&e;</title></ClinicalDocument>'
    )
    root = parse_cda(doc)
    assert "root:" not in etree.tostring(root).decode()
