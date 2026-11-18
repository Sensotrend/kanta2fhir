"""Terminology layer: Kanta code systems → FHIR codings, international equivalents, English.

Principle (plan §2.4): every original Finnish coding is kept, and international codings are
*added* where a mapping exists. Finnish displays stay primary; English is added either as the
display of an international coding or as a translation of a Finnish display (D8).
"""

from kanta2fhir.terminology.lookup import FhirCoding, Terminology, ucum_unit

__all__ = ["FhirCoding", "Terminology", "ucum_unit"]
