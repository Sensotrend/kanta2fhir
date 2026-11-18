"""Target implementation guides (decision D2) and profile URLs used by the builders."""

from __future__ import annotations

FHIR_VERSION = "4.0.1"

# Packages the validator loads per target. The base package is used for shared resources.
PACKAGES = {
    "base": ["hl7.fhir.eu.base#2.0.1"],
    "eps": ["hl7.fhir.eu.eps#1.0.0-ballot"],
    "lab": ["hl7.fhir.eu.laboratory#2.1.0"],
    "hdr": ["hl7.fhir.eu.hdr#1.0.0"],
}

EU_BASE = "http://hl7.eu/fhir/base/StructureDefinition"
EU_CORE = {
    "Patient": f"{EU_BASE}/patient-eu-core",
    "Organization": f"{EU_BASE}/organization-eu-core",
    "Practitioner": f"{EU_BASE}/practitioner-eu-core",
    "PractitionerRole": f"{EU_BASE}/practitionerRole-eu-core",
}
