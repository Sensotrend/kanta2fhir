"""Convert a CDA narrative block (``section/text``) into FHIR narrative XHTML.

FHIR narrative is a restricted XHTML ``<div>``: no scripts, no forms, no external images. CDA's
narrative elements map closely onto it (paragraph → p, list → ul/ol, table → table, content →
span). Anything unexpected becomes a ``span`` so no text is lost.
"""

from __future__ import annotations

import re

from lxml import etree

from kanta2fhir.cda.util import Element, H

XHTML = "http://www.w3.org/1999/xhtml"
X = f"{{{XHTML}}}"

_TAGS = {
    "paragraph": "p",
    "content": "span",
    "item": "li",
    "table": "table",
    "caption": "caption",
    "thead": "thead",
    "tbody": "tbody",
    "tfoot": "tfoot",
    "tr": "tr",
    "th": "th",
    "td": "td",
    "colgroup": "colgroup",
    "col": "col",
    "br": "br",
    "sub": "sub",
    "sup": "sup",
    "footnote": "span",
    "footnoteRef": "span",
}
_SKIP = {"renderMultiMedia"}  # images are not carried over (FHIR narrative needs them inline)
_TABLE_ATTRS = {"colspan", "rowspan", "align", "valign"}
_WS = re.compile(r"\s+")


def to_xhtml(text_el: Element | None) -> str | None:
    """The narrative as a serialised XHTML ``<div>``, or None when it has no visible text."""
    if text_el is None:
        return None
    div = etree.Element(f"{X}div", nsmap={None: XHTML})
    _copy_children(text_el, div)
    if not "".join(div.itertext()).strip():
        return None
    return etree.tostring(div, encoding="unicode")


def _norm(value: str | None) -> str | None:
    return None if value is None else _WS.sub(" ", value)


def _copy_children(src: Element, dst: Element) -> None:
    dst.text = _norm(src.text)
    for child in src:
        if not isinstance(child.tag, str):  # comment or processing instruction
            _append_text(dst, _norm(child.tail))
            continue
        out = _convert(child)
        if out is None:
            _append_text(dst, _norm(child.tail))
            continue
        dst.append(out)
        out.tail = _norm(child.tail)


def _append_text(dst: Element, value: str | None) -> None:
    if not value:
        return
    if len(dst):
        dst[-1].tail = (dst[-1].tail or "") + value
    else:
        dst.text = (dst.text or "") + value


def _convert(el: Element) -> Element | None:
    name = etree.QName(el).localname if el.tag.startswith(H) else None
    if name in _SKIP:
        return None
    if name == "list":
        tag = "ol" if el.get("listType") == "ordered" else "ul"
    elif name == "linkHtml":
        href = el.get("href", "")
        tag = "a" if href.startswith(("http://", "https://")) else "span"
    else:
        tag = _TAGS.get(name or "", "span")

    out = etree.Element(f"{X}{tag}")
    if el.get("ID"):
        out.set("id", el.get("ID", ""))
    if el.get("styleCode"):
        out.set("class", " ".join(s.lower() for s in el.get("styleCode", "").split()))
    if tag == "a":
        out.set("href", el.get("href", ""))
    if tag in {"td", "th", "col", "colgroup"}:
        for attr in _TABLE_ATTRS & set(el.keys()):
            out.set(attr, el.get(attr, ""))
    if tag in {"br", "col"}:
        return out
    _copy_children(el, out)
    return out
