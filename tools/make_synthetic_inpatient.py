"""Generate a synthetic Kanta export with an inpatient stay (D3: no real inpatient data exists).

The documents follow the structure of the real Kanta test documents (CDA R2 with the
hl7fi local header, view → care-process phase → heading sections, the same entry patterns
and code systems). Everything is invented:
- the patient has a test-range personal identity code (individual number 912);
- all organisation and document OIDs are under 1.2.246.10.99999999 / 1.2.246.99.9999999;
- clinical codes are real code system codes, but procedure codes are illustrative only.

The inpatient service event uses encompassingEncounterCode 1, which is *assumed* to mean an
inpatient period (osastohoitojakso); only code 2 (outpatient visit) occurs in real data.

Output: tests/fixtures/synthetic/inpatient.ndjson (deterministic).
Usage: uv run python tools/make_synthetic_inpatient.py
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "synthetic" / "inpatient.ndjson"

HETU = "150550-9121"
PATIENT = ("Synteettinen", "Saara")  # family, given
BIRTH = "19500515"
BASE = "1.2.246.10.99999999.1.2025"
ORG = ("1.2.246.99.9999999.900.9", "Synteettinen sairaala, sisätautien osasto")
DOCTOR = ("Lääkäri", "Lauri", "LL")
ENCOUNTER_ID = f"{BASE}.100.2"
ADMISSION, DISCHARGE = "20250310143000", "20250317110000"

# Code systems
VIEWS = "1.2.246.537.6.12.2002"
PHASES = "1.2.246.537.6.13.2006"
HEADINGS = "1.2.246.537.6.14.2006"
KANTA = "1.2.246.537.6.12.999.2003"
LAB_SUB = "1.2.246.537.6.12.2002.103"
ICD10 = "1.2.246.537.6.1.1999"
LAB = "1.2.246.537.6.3.2006"
VITALS = "1.2.246.537.6.96.2008"
PROCEDURES = "1.2.246.537.6.2.2007"

XSI = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'


def code(c: str, system: str, display: str, tag: str = "code", extra: str = "") -> str:
    return f'<{tag} code="{c}" codeSystem="{system}" displayName="{display}"{extra}/>'


def header(
    doc_id: str,
    title: str,
    time: str,
    doc_type: tuple[str, str],
    view: str | None,
    encounter_time: str,
    encounter_code: str | None,
) -> str:
    toc = (
        f"<hl7fi:tableOfContents>{code(view[0], VIEWS, view[1], 'hl7fi:contentsCode')}"
        "</hl7fi:tableOfContents>"
        if view
        else ""
    )
    enc_code = (
        code(
            encounter_code,
            "1.2.246.537.5.40156.2008",
            "Osastohoitojakso" if encounter_code == "1" else "Avohoitokäyntitieto",
            "hl7fi:encompassingEncounterCode",
        )
        if encounter_code
        else ""
    )
    family, given = PATIENT
    dfam, dgiven, dsuffix = DOCTOR
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ClinicalDocument xmlns="urn:hl7-org:v3" xmlns:hl7fi="urn:hl7finland" {XSI}>
<realmCode code="FI"/>
<typeId extension="POCD_HD000040" root="2.16.840.1.113883.1.3"/>
<templateId extension="2018.10.4" root="1.2.246.777.5.1"/>
<templateId root="1.2.246.777.11.2015.36"/>
<templateId root="1.2.246.777.11.2015.38"/>
<templateId root="1.2.246.777.11.2020.6"/>
<id root="{doc_id}"/>
{code("2", "1.2.246.537.5.40150.2009", "Julkinen terveydenhuolto")}
<title>{title}</title>
<effectiveTime value="{time}"/>
{code("5", "1.2.246.777.5.99902.2006", "Terveydenhuollon salassapidettävä", "confidentialityCode")}
<languageCode code="fi"/>
<setId root="{doc_id}"/>
<versionNumber value="1"/>
<recordTarget><patientRole><id extension="****" root="1.2.246.21"/><patient>
<name><given>{given}</given><given qualifier="CL">{given}</given><family>{family}</family></name>
{code("2", "1.2.246.537.5.1.1997", "Nainen", "administrativeGenderCode")}
<birthTime value="{BIRTH}"/>
</patient></patientRole></recordTarget>
<author><time value="{time}"/><assignedAuthor><id extension="****" root="1.2.246.21"/>
<assignedPerson><name><given>{dgiven}</given><family>{dfam}</family><suffix>{dsuffix}</suffix></name></assignedPerson>
<representedOrganization><id root="{ORG[0]}"/><name>{ORG[1]}</name></representedOrganization>
</assignedAuthor></author>
<custodian><assignedCustodian><representedCustodianOrganization><id root="{ORG[0]}"/><name>{ORG[1]}</name>
</representedCustodianOrganization></assignedCustodian></custodian>
<componentOf><encompassingEncounter><id root="{ENCOUNTER_ID}"/>{encounter_time}
<responsibleParty><assignedEntity><id nullFlavor="NA"/><representedOrganization><id root="{ORG[0]}"/>
<name>{ORG[1]}</name></representedOrganization></assignedEntity></responsibleParty>
</encompassingEncounter></componentOf>
<hl7fi:localHeader>{toc}
{code("1", "1.2.246.537.5.40179.2008", "CDA R2", "hl7fi:fileFormat")}
{code(doc_type[0], "1.2.246.537.5.5001.2011", doc_type[1], "hl7fi:documentType")}
{code("06.03", "1.2.246.537.6.300.2010", "Potilaan hoito", "hl7fi:functionCode")}
{code("3", "1.2.246.537.5.40154.2008", "Arkistointivalmis", "hl7fi:recordStatus")}
{enc_code}
</hl7fi:localHeader>"""


def heading(c: str, display: str, text: str, entries: str = "") -> str:
    return (
        f"<component><section>{code(c, HEADINGS, display)}<title>{display}</title>"
        f"<text>{text}</text>{entries}</section></component>"
    )


def phase(c: str, display: str, *headings: str) -> str:
    return (
        f"<component><section>{code(c, PHASES, display)}<title>{display}</title>"
        f"{''.join(headings)}</section></component>"
    )


def sub(c: str, display: str, value: str, system: str = KANTA, cls: str = "OBS") -> str:
    return (
        f'<entryRelationship typeCode="COMP"><observation classCode="{cls}" moodCode="EVN">'
        f"{code(c, system, display)}{value}</observation></entryRelationship>"
    )


def diagnosis(n: int, icd: str, name: str, primary: bool, permanent: bool) -> str:
    q = ("PAA", "Päädiagnoosi tai päätoimenpide") if primary else ("SIVU", "Sivudiagnoosi")
    perm = ("PYS", "Pysyväisluonteinen") if permanent else ("KER", "Määräaikainen")
    return f"""<entry><observation classCode="OBS" moodCode="EVN">
<templateId root="{KANTA}.2"/><id root="{BASE}.200.{n}"/>
<code code="2" codeSystem="{KANTA}" displayName="Diagnoosi"><qualifier>
<value code="{q[0]}" codeSystem="1.2.246.537.5.40005.2003" displayName="{q[1]}" xsi:type="CD"/>
</qualifier></code>
<effectiveTime value="20250317"/>
<value code="{icd}" codeSystem="{ICD10}" displayName="{name}" xsi:type="CD"><originalText>{
        name
    }</originalText></value>
{
        sub(
            "2.2",
            "Diagnoosin, käyntisyyn tai riskin varmuusaste",
            '<value code="TOD" codeSystem="1.2.246.537.5.40004.2003" displayName="Todennäköinen tai varma" xsi:type="CV"/>',
        )
    }
{
        sub(
            "2.1",
            "Diagnoosin tai riskin pysyvyys",
            f'<value code="{perm[0]}" codeSystem="1.2.246.537.5.40003.2003" displayName="{perm[1]}" xsi:type="CV"/>',
        )
    }
{
        sub(
            "2.14",
            "Diagnoosin tai käyntisyyn episoditunnus",
            f'<value root="{BASE}.210.{n}" xsi:type="II"/>',
            cls="COND",
        )
    }
</observation></entry>"""


def procedure(n: int, c: str, name: str, time: str) -> str:
    return f"""<entry><procedure classCode="PROC" moodCode="EVN"><id root="{BASE}.300.{n}"/>
<code code="{c}" codeSystem="{PROCEDURES}" displayName="{name}"><originalText>{name}</originalText>
<qualifier><value code="PAA" codeSystem="1.2.246.537.5.40005.2003" displayName="Päädiagnoosi tai päätoimenpide" xsi:type="CD"/></qualifier></code>
<effectiveTime value="{time}"/>
{sub("3.8", "Toimenpiteen yksilöivä tunnus", f'<value root="{BASE}.310.{n}" xsi:type="II"/>', cls="COND")}
</procedure></entry>"""


def lab(
    n: int, c: str, name: str, value: str, unit: str, low: str, high: str, flag: str, time: str
) -> str:
    flags = {"H": "Yli viitearvon ylärajan", "N": "Normaali arvo", "L": "Alle viitearvon alarajan"}
    return f"""<entry><observation classCode="OBS" moodCode="EVN"><id root="{BASE}.400.{n}"/>
<code code="{c}" codeSystem="{LAB}" displayName="{name}"><qualifier>
<value code="F" codeSystem="1.2.246.537.5.85.1997" displayName="Lopullinen tulos"/></qualifier></code>
<effectiveTime value="{time}"/>
<value unit="{unit}" value="{value}" xsi:type="PQ"/>
{code(flag, "1.2.246.537.5.78.1997", flags[flag], "interpretationCode")}
<specimen><specimenRole><specimenPlayingEntity>{code("S", "1.2.246.537.6.17.2004", "seerumi")}
</specimenPlayingEntity></specimenRole></specimen>
{
        sub(
            "30",
            "Laboratoriotutkimuksen tunniste",
            f'<value root="{BASE}.410.{n}" xsi:type="II"/>',
            LAB_SUB,
            "COND",
        )
    }
{
        sub(
            "13",
            "Laboratoriotutkimustuloksen valmistumisaika",
            f'<value value="{time}" xsi:type="TS"/>',
            LAB_SUB,
        )
    }
<referenceRange><observationRange><value xsi:type="IVL_PQ"><low unit="{unit}" value="{low}"/>
<high unit="{unit}" value="{high}"/></value></observationRange></referenceRange>
</observation></entry>"""


def weight(n: int, value: str, time: str) -> str:
    return f"""<entry><observation classCode="OBS" moodCode="EVN"><id root="{BASE}.500.{n}"/>
{code("3141-9", VITALS, "Paino, mitattu")}<effectiveTime value="{time}"/>
<value unit="kg" value="{value}" xsi:type="PQ"/>
{sub("23.6", "Fysiologisen mittauksen tunniste", f'<value root="{BASE}.510.{n}" xsi:type="II"/>', cls="COND")}
</observation></entry>"""


def body(view: tuple[str, str], *phases: str) -> str:
    return (
        f"<component><structuredBody><component><section>{code(view[0], VIEWS, view[1])}"
        f"<title>{view[1]}</title><text><paragraph>{ORG[1]}</paragraph>"
        f"<paragraph>{DOCTOR[2]} {DOCTOR[1]} {DOCTOR[0]}</paragraph></text>"
        f"{''.join(phases)}</section></component></structuredBody></component></ClinicalDocument>"
    )


def service_event() -> str:
    doc_id = f"{BASE}.100"
    enc_time = (
        f'<effectiveTime><low value="{ADMISSION}"/><high value="{DISCHARGE}"/></effectiveTime>'
    )
    return header(
        doc_id,
        "Palvelutapahtuma-asiakirja",
        DISCHARGE,
        ("4", "Palvelutapahtuma-asiakirja"),
        None,
        enc_time,
        "1",
    ) + (
        "<component><structuredBody><component><section><text>Osastohoitojakso</text>"
        "</section></component></structuredBody></component></ClinicalDocument>"
    )


def discharge_record() -> str:
    doc_id = f"{BASE}.101"
    view = ("10", "Sisätaudit")
    return header(
        doc_id,
        "Sisätaudit",
        DISCHARGE,
        ("1", "Kertomusteksti"),
        view,
        '<effectiveTime nullFlavor="NA"/>',
        None,
    ) + body(
        view,
        phase(
            "14",
            "Hoidon suunnittelu",
            heading(
                "21",
                "Hoidon tarve",
                "<paragraph>Potilas saapui päivystykseen rintakivun vuoksi 10.3.2025. "
                "EKG:ssä ST-laskuja, troponiini koholla. Otettiin osastolle "
                "jatkotutkimuksiin ja hoitoon.</paragraph>",
            ),
        ),
        phase(
            "15",
            "Hoidon toteutus",
            heading(
                "76",
                "Muu merkintä",
                "<paragraph>Hoidon kulku: aloitettu kaksoisantitromboottinen lääkitys. "
                "Sepelvaltimoiden varjoainekuvauksessa yhden suonen tauti, johon "
                "pallolaajennus ja stentti 11.3.2025. Toipuminen komplikaatioitta.</paragraph>",
            ),
            heading(
                "51",
                "Toimenpiteet",
                "<paragraph>Sepelvaltimoiden pallolaajennus</paragraph>",
                procedure(1, "FNG05", "Sepelvaltimon pallolaajennus ja stentti", "20250311"),
            ),
            heading(
                "53",
                "Tutkimukset",
                "<paragraph>Laboratoriotulokset</paragraph>",
                lab(1, "4278", "S -Troponiini T", "412", "ng/l", "0", "14", "H", "20250310150000")
                + lab(
                    2,
                    "1216",
                    "S -C-reaktiivinen proteiini",
                    "6",
                    "mg/l",
                    "0",
                    "10",
                    "N",
                    "20250310150000",
                )
                + lab(
                    3, "1552", "B -Hemoglobiini", "128", "g/l", "117", "155", "N", "20250316080000"
                ),
            ),
            heading(
                "64",
                "Fysiologiset mittaukset",
                "<paragraph>Paino 71 kg</paragraph>",
                weight(1, "71", "20250310160000"),
            ),
            heading(
                "55",
                "Lääkehoito",
                "<list><item>Asetyylisalisyylihappo 100 mg 1 x 1</item>"
                "<item>Tikagrelori 90 mg 1 x 2 (12 kk)</item>"
                "<item>Atorvastatiini 80 mg 1 x 1</item>"
                "<item>Bisoprololi 5 mg 1 x 1</item></list>",
            ),
        ),
        phase(
            "16",
            "Hoidon arviointi",
            heading(
                "13",
                "Diagnoosi",
                "<paragraph>Dg: I21.4 Akuutti sydäninfarkti ilman ST-nousuja</paragraph>"
                "<paragraph>Dg: E11.9 Aikuistyypin diabetes</paragraph>",
                diagnosis(1, "I21.4", "Akuutti sydäninfarkti ilman ST-nousuja", True, False)
                + diagnosis(2, "E11.9", "Aikuistyypin diabetes ilman komplikaatioita", False, True),
            ),
            heading(
                "62",
                "Lausunto",
                "<paragraph>Loppulausunto: 75-vuotias nainen, jolla ST-nousuton "
                "sydäninfarkti. Hoidettu pallolaajennuksella. Kotiutetaan hyvävointisena "
                "17.3.2025.</paragraph>",
            ),
            heading(
                "75",
                "Suunnitelma",
                "<paragraph>Kontrolli terveyskeskuksessa 2 viikon kuluttua. "
                "Sydänkuntoutus. Lipidit 3 kk kuluttua.</paragraph>",
            ),
        ),
    )


def document_reference(
    doc_id: str,
    type_code: str,
    type_display: str,
    view: str | None,
    xml: str,
    period: tuple[str, str] | None,
) -> dict:
    resource = {
        "resourceType": "DocumentReference",
        "meta": {"profile": ["https://hrp.kanta.fi/fhir/StructureDefinition/HRPDocumentReference"]},
        "identifier": [{"system": "urn:ietf:rfc:3986", "value": doc_id}],
        "status": "current",
        "type": {
            "coding": [
                {
                    "system": "https://hrp.kanta.fi/fihrp-cs-documentreferencetype",
                    "code": type_code,
                    "display": type_display,
                }
            ]
        },
        "subject": {
            "identifier": {"system": "urn:oid:1.2.246.21", "value": HETU},
            "display": f"{PATIENT[0]}, {PATIENT[1]}",
        },
        "date": "2025-03-17T11:00:00+02:00",
        "author": [
            {"identifier": {"system": "urn:ietf:rfc:3986", "value": ORG[0]}, "display": ORG[1]}
        ],
        "content": [
            {
                "attachment": {
                    "contentType": "text/xml",
                    "language": "fi",
                    "data": base64.b64encode(xml.encode()).decode(),
                }
            }
        ],
        "context": {
            "related": [{"identifier": {"system": "urn:ietf:rfc:3986", "value": ENCOUNTER_ID}}]
        },
    }
    if view:
        resource["category"] = [{"coding": [{"system": f"urn:oid:{VIEWS}", "code": view}]}]
    if period:
        resource["context"]["period"] = {"start": period[0], "end": period[1]}
    return {"resource": resource}


def main() -> None:
    lines = [
        document_reference(
            f"{BASE}.100",
            "1",
            "Palvelutapahtuma",
            None,
            service_event(),
            ("2025-03-10T14:30:00+02:00", "2025-03-17T11:00:00+02:00"),
        ),
        document_reference(f"{BASE}.101", "2", "Hoitoasiakirja", "10", discharge_record(), None),
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8"
    )
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
