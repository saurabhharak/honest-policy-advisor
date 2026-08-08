"""Loader for the curated insurer metrics benchmark data.

Reads src/policydecoder/data/insurer_metrics.json (IRDAI FY2024-25 figures)
and provides name lookup with tolerant matching, so "star health" resolves
to "Star Health and Allied Insurance".

Data is curated and versioned by the `as_of` field. Never guess a null —
missing metrics are reported as "no data" by the health calculator.
"""

import json
from difflib import SequenceMatcher
from importlib import resources
from typing import Any

_DATA = None


def load_insurer_metrics() -> dict[str, dict[str, Any]]:
    """Load all insurer metrics keyed by canonical name."""
    global _DATA
    if _DATA is None:
        with (
            resources.files("policydecoder.data")
            .joinpath("insurer_metrics.json")
            .open("r", encoding="utf-8") as f
        ):
            raw = json.load(f)
        _DATA = {m["name"]: m for m in raw["insurers"]}
    return _DATA


def get_insurer_metrics(name: str | None) -> dict[str, Any] | None:
    """Look up an insurer by name, with fuzzy matching.

    Matches exact name, then substring, then fuzzy ratio. Returns None for
    unknown insurers (the caller reports "no benchmark data").
    """
    if not name:
        return None
    data = load_insurer_metrics()

    query = name.strip().lower()
    if query in data:
        return data[query]

    # Substring match on both directions
    for canonical in data:
        if query in canonical.lower() or canonical.lower() in query:
            return data[canonical]

    # Fuzzy ratio match for common short names
    best_name, best_ratio = None, 0.0
    for canonical in data:
        ratio = SequenceMatcher(None, query, canonical.lower()).ratio()
        if ratio > best_ratio:
            best_name, best_ratio = canonical, ratio
    if best_ratio >= 0.75:
        return data[best_name]

    return None
