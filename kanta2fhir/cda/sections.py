"""Walk the CDA body: view → care-process phase → heading sections, and the entries in them.

In milestone 1 this only takes an inventory (for the coverage report). The entry extractors
of milestone 2 use the same walk.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from kanta2fhir.cda.util import Element, H, coding, find, findall, local_name, template_ids, text
from kanta2fhir.model import Coding


@dataclass(frozen=True, slots=True)
class SectionStep:
    """One level of the section path, e.g. ``103 Laboratorio``."""

    code: Coding | None
    title: str | None

    @property
    def label(self) -> str:
        if self.code is not None:
            return f"{self.code.code} {self.code.display or ''}".strip()
        return self.title or "(untitled)"


@dataclass(frozen=True, slots=True)
class EntryRef:
    """An entry's clinical statement, with the section path leading to it."""

    path: tuple[SectionStep, ...]
    element: Element
    entry_template_ids: tuple[str, ...]  # templateIds on the <entry> element itself

    @property
    def kind(self) -> str:
        """The clinical statement element name: observation, procedure, organizer …"""
        return local_name(self.element)

    @property
    def code(self) -> Coding | None:
        return coding(find(self.element, "h:code"))

    @property
    def key(self) -> str:
        """Inventory key, e.g. ``observation 1.2.246.537.6.12.999.2003#2``."""
        c = self.code
        if c is None:
            return f"{self.kind} (no code)"
        return f"{self.kind} {c.system}#{c.code}"

    @property
    def path_label(self) -> str:
        return " / ".join(step.label for step in self.path)


def iter_sections(root: Element) -> Iterator[tuple[tuple[SectionStep, ...], Element]]:
    """Yield every section with its full path (depth first, document order)."""
    body = find(root, "h:component/h:structuredBody")
    if body is None:
        return
    for comp in findall(body, "h:component"):
        section = find(comp, "h:section")
        if section is not None:
            yield from _walk(section, ())


def _walk(
    section: Element, parent: tuple[SectionStep, ...]
) -> Iterator[tuple[tuple[SectionStep, ...], Element]]:
    path = (*parent, SectionStep(coding(find(section, "h:code")), text(section, "h:title")))
    yield path, section
    for comp in findall(section, "h:component"):
        child = find(comp, "h:section")
        if child is not None:
            yield from _walk(child, path)


def iter_entries(root: Element) -> Iterator[EntryRef]:
    """Yield the clinical statement of every ``entry`` in every section."""
    for path, section in iter_sections(root):
        for entry in findall(section, "h:entry"):
            for child in entry:
                if not isinstance(child.tag, str) or child.tag == f"{H}templateId":
                    continue  # skip comments and templateIds
                yield EntryRef(path=path, element=child, entry_template_ids=template_ids(entry))
