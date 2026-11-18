from lxml import etree

from kanta2fhir.cda.values import DocContext, SubObservations, reference_ranges, typed_value
from kanta2fhir.model import Coding, Identifier, Period, Quantity, Range

NS = 'xmlns="urn:hl7-org:v3" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'


def doc(body: str) -> etree._Element:
    return etree.fromstring(f"<ClinicalDocument {NS}>{body}</ClinicalDocument>")


def value(snippet: str, extra: str = "") -> object:
    root = doc(f"{extra}<observation>{snippet}</observation>")
    obs = root.find("{urn:hl7-org:v3}observation")
    return typed_value(obs.find("{urn:hl7-org:v3}value"), DocContext(root))


def test_typed_values() -> None:
    assert value('<value xsi:type="PQ" value="5.2" unit="mmol/l"/>') == Quantity("5.2", "mmol/l")
    assert value('<value xsi:type="IVL_PQ"><low value="1" unit="kg"/></value>') == Range(
        low=Quantity("1", "kg")
    )
    assert value('<value xsi:type="ST">negat</value>') == "negat"
    assert value('<value xsi:type="BL" value="false"/>') is False
    assert value('<value xsi:type="TS" value="20241218"/>') == "2024-12-18"
    assert value('<value xsi:type="II" root="1.2.3"/>') == Identifier("1.2.3")
    assert value('<value xsi:type="INT" value="10"/>') == 10
    assert value('<value xsi:type="IVL_TS"><low value="20241218"/></value>') == Period(
        start="2024-12-18"
    )
    assert value('<value xsi:type="CV" nullFlavor="NA"/>') is None


def test_coded_value_uses_original_text_when_display_missing() -> None:
    v = value(
        '<value xsi:type="CD" code="J46" codeSystem="1.2">'
        "<originalText>Astma</originalText></value>"
    )
    assert v == Coding(code="J46", system="1.2", display="Astma")


def test_ed_reference_is_resolved_from_narrative() -> None:
    narrative = '<text><paragraph ID="p1">Sokeri  huonossa\n tasapainossa</paragraph></text>'
    v = value('<value xsi:type="ED"><reference value="#p1"/></value>', extra=narrative)
    assert v == "Sokeri huonossa tasapainossa"


def test_sub_observations_and_reference_ranges() -> None:
    root = doc(
        """<observation>
          <entryRelationship><observation>
            <code code="19.1" codeSystem="K"/>
            <value xsi:type="CV" code="2" codeSystem="D" displayName="Kurkkumätä"/>
            <value xsi:type="CV" code="7" codeSystem="D" displayName="Jäykkäkouristus"/>
          </observation></entryRelationship>
          <entryRelationship><observation>
            <code code="13.9" codeSystem="OTHER"/><value xsi:type="ST">ignored</value>
          </observation></entryRelationship>
          <referenceRange><observationRange>
            <value xsi:type="IVL_PQ">
              <low value="15" unit="U/l"/><high value="45" unit="U/l"/>
            </value>
          </observationRange></referenceRange>
        </observation>"""
    )
    obs = root[0]
    ctx = DocContext(root)
    subs = SubObservations(obs, ctx, ("K",))
    assert [c.code for c in subs.codings("19.1")] == ["2", "7"]
    assert subs.value("13.9") is None  # other code systems are not indexed
    [rr] = reference_ranges(obs, ctx, "Normaalisti näin")
    assert (rr.low, rr.high, rr.text) == (
        Quantity("15", "U/l"),
        Quantity("45", "U/l"),
        "Normaalisti näin",
    )
