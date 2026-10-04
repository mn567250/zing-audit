"""WCAG 2.1 success criteria -> EN 301 549 clause / BITV 2.0 test step.

BITV 2.0 requires EN 301 549, whose chapter 9 (web) repeats WCAG 2.1 A/AA with
"9." in front of the criterion number: WCAG 1.4.3 is EN 301 549 9.1.4.3, which
is also the BITV-Test step number (Prüfschritt 9.1.4.3 "Kontraste von Texten
ausreichend"). axe-core tags its rules "wcag143", so the mapping is mechanical.
"""

from __future__ import annotations

import re

# WCAG 2.1 level A + AA (the EN 301 549 / BITV scope), with short titles.
CRITERIA: dict[str, str] = {
    "1.1.1": "Non-text Content",
    "1.2.1": "Audio-only and Video-only (Prerecorded)",
    "1.2.2": "Captions (Prerecorded)",
    "1.2.3": "Audio Description or Media Alternative",
    "1.2.4": "Captions (Live)",
    "1.2.5": "Audio Description (Prerecorded)",
    "1.3.1": "Info and Relationships",
    "1.3.2": "Meaningful Sequence",
    "1.3.3": "Sensory Characteristics",
    "1.3.4": "Orientation",
    "1.3.5": "Identify Input Purpose",
    "1.4.1": "Use of Color",
    "1.4.2": "Audio Control",
    "1.4.3": "Contrast (Minimum)",
    "1.4.4": "Resize Text",
    "1.4.5": "Images of Text",
    "1.4.10": "Reflow",
    "1.4.11": "Non-text Contrast",
    "1.4.12": "Text Spacing",
    "1.4.13": "Content on Hover or Focus",
    "2.1.1": "Keyboard",
    "2.1.2": "No Keyboard Trap",
    "2.1.4": "Character Key Shortcuts",
    "2.2.1": "Timing Adjustable",
    "2.2.2": "Pause, Stop, Hide",
    "2.3.1": "Three Flashes or Below Threshold",
    "2.4.1": "Bypass Blocks",
    "2.4.2": "Page Titled",
    "2.4.3": "Focus Order",
    "2.4.4": "Link Purpose (In Context)",
    "2.4.5": "Multiple Ways",
    "2.4.6": "Headings and Labels",
    "2.4.7": "Focus Visible",
    "2.5.1": "Pointer Gestures",
    "2.5.2": "Pointer Cancellation",
    "2.5.3": "Label in Name",
    "2.5.4": "Motion Actuation",
    "3.1.1": "Language of Page",
    "3.1.2": "Language of Parts",
    "3.2.1": "On Focus",
    "3.2.2": "On Input",
    "3.2.3": "Consistent Navigation",
    "3.2.4": "Consistent Identification",
    "3.3.1": "Error Identification",
    "3.3.2": "Labels or Instructions",
    "3.3.3": "Error Suggestion",
    "3.3.4": "Error Prevention (Legal, Financial, Data)",
    "4.1.1": "Parsing",
    "4.1.2": "Name, Role, Value",
    "4.1.3": "Status Messages",
}

_TAG = re.compile(r"^wcag(\d)(\d)(\d+)$")


def criterion_of(tag: str) -> str | None:
    """axe tag "wcag1410" -> "1.4.10" (None for non-criterion tags)."""
    m = _TAG.match(tag)
    if not m:
        return None
    sc = ".".join(m.groups())
    return sc if sc in CRITERIA else None


def bitv(sc: str) -> str:
    """WCAG criterion -> BITV/EN 301 549 label, e.g. "BITV 9.1.4.3 Contrast (Minimum)"."""
    return f"BITV/EN 9.{sc} {CRITERIA.get(sc, '')}".rstrip()


def describe(tags: list[str]) -> str:
    """Human label for an axe rule's tags ("best practice" when it maps to no criterion)."""
    scs = [sc for sc in (criterion_of(t) for t in tags) if sc]
    if not scs:
        return "best practice (no WCAG criterion)"
    return "; ".join(f"WCAG {sc} / {bitv(sc)}" for sc in scs)
