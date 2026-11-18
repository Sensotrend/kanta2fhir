from lxml import etree

from kanta2fhir.cda.narrative import to_xhtml


def narrative(inner: str) -> etree._Element:
    return etree.fromstring(f'<text xmlns="urn:hl7-org:v3">{inner}</text>')


def test_paragraphs_content_and_whitespace() -> None:
    out = to_xhtml(
        narrative(
            '<paragraph ID="a1"><content styleCode="Bold">Dg:\n\t\t</content>'
            "<content>Q32.11;</content></paragraph><br/>"
        )
    )
    assert out == (
        '<div xmlns="http://www.w3.org/1999/xhtml"><p id="a1"><span class="bold">Dg: </span>'
        "<span>Q32.11;</span></p><br/></div>"
    )


def test_lists_tables_and_links() -> None:
    out = to_xhtml(
        narrative(
            '<list listType="ordered"><item>yksi</item></list>'
            '<table><tbody><tr><td colspan="2">x</td></tr></tbody></table>'
            '<linkHtml href="https://example.org">ok</linkHtml>'
            '<linkHtml href="javascript:alert(1)">bad</linkHtml>'
            '<renderMultiMedia referencedObject="img1"/>tail'
        )
    )
    assert out is not None
    assert "<ol><li>yksi</li></ol>" in out
    assert '<td colspan="2">x</td>' in out
    assert '<a href="https://example.org">ok</a>' in out
    assert "<span>bad</span>" in out and "javascript" not in out
    assert out.endswith("tail</div>")


def test_unknown_elements_keep_text_and_empty_gives_none() -> None:
    out = to_xhtml(narrative("<somethingElse>teksti</somethingElse>"))
    assert out is not None and "<span>teksti</span>" in out
    assert to_xhtml(narrative("  \n\t ")) is None
    assert to_xhtml(None) is None
