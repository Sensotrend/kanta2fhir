"""FHIR document bundles."""

from __future__ import annotations

from kanta2fhir.fhir.datatypes import JSON, full_url, resource_id


def document_bundle(
    key: str,
    timestamp: str,
    composition: JSON,
    resources: list[tuple[str, JSON]],
    profile: str | None = None,
) -> JSON:
    """A ``Bundle`` of type ``document``: the Composition first, then everything it uses.

    ``key`` identifies the document (e.g. "eps|<patient>"); the bundle id, identifier and the
    Composition id derive from it, so a re-run gives the same ids.
    """
    bundle_id = resource_id("Bundle", key)
    entries = [{"fullUrl": full_url(composition["id"]), "resource": composition}]
    entries += [
        {"fullUrl": url, "resource": res}
        for url, res in resources
        if url != full_url(composition["id"])
    ]
    bundle: JSON = {"resourceType": "Bundle", "id": bundle_id}
    if profile:
        bundle["meta"] = {"profile": [profile]}
    bundle |= {
        "language": "fi",
        "identifier": {"system": "urn:ietf:rfc:3986", "value": full_url(bundle_id)},
        "type": "document",
        "timestamp": timestamp,
        "entry": entries,
    }
    return bundle
