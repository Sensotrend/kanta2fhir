"""Generated FHIR narrative (XHTML) from plain values. All text is escaped."""

from __future__ import annotations

from html import escape

from kanta2fhir.fhir.datatypes import JSON

XHTML_NS = "http://www.w3.org/1999/xhtml"


def div(*fragments: str) -> str:
    return f'<div xmlns="{XHTML_NS}">{"".join(fragments)}</div>'


def para(text: str | None) -> str:
    return f"<p>{escape(text)}</p>" if text else ""


def table(headers: list[str], rows: list[list[str | None]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(c or '')}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def generated(*fragments: str) -> JSON:
    """A Narrative element with status 'generated'."""
    return {"status": "generated", "div": div(*fragments)}


def empty_section(text: str) -> JSON:
    return generated(para(text))
