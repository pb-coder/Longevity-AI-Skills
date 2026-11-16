"""Structured workout load and equipment metadata, with legacy-note support."""
from __future__ import annotations

import re

LOAD_BASES = frozenset({"total", "plates_only"})


def equipment_limit_reached(notes: str | None) -> bool:
    """Recognize an explicit equipment-limit annotation, not exertion."""
    for clause in re.split(r"[;.!?\n]", str(notes or "").casefold()):
        if re.search(r"\b(?:not|never|no|almost|near)\b", clause):
            continue
        if re.search(r"\b(?:machine|stack)\s+(?:(?:limit|maximum|max)\s+"
                     r"(?:reached|hit)|(?:is\s+)?maxed\s+out)\b", clause):
            return True
    return False


def is_partial_bar_load(notes: str | None) -> bool:
    """Recognize explicit legacy descriptions; never infer from the weight."""
    text = str(notes or "").casefold()
    return any(term in text for term in (
        "weight excludes bar", "weight excluding bar", "excluding bar",
        "excludes bar", "without bar weight", "plates only", "plate only",
        "ohne stange", "exklusive stange", "exclusive stange"))


def partial_load(row: dict) -> bool:
    """Typed basis wins; legacy notes are used when the basis is absent."""
    basis = str(row.get("load_basis") or "").strip().lower()
    return basis != "total" if basis else is_partial_bar_load(row.get("notes"))


def equipment_context(row: dict) -> tuple[str, str] | None:
    """Exact case-insensitive gym/machine identity, or None if unspecified."""
    gym = str(row.get("gym") or "").strip().casefold()
    machine = str(row.get("machine") or "").strip().casefold()
    return (gym, machine) if gym or machine else None
