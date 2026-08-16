"""Data for the small "comments by X" charts on the document page.

No JS chart library -- the app stays server-rendered HTML, so this module
only computes plain numbers (label / count / color / bar length). The
actual <svg> markup lives in the document template.
"""

from __future__ import annotations

from app import storage
from app.ai.base import CATEGORIES

# A validated categorical palette (checked for colorblind-safe adjacent
# contrast and lightness/chroma bounds) -- the first five slots of a
# documented eight-hue order chosen specifically so neighboring colors stay
# distinguishable under color-vision deficiency, not picked by eye.
_CATEGORY_COLORS = {
    "Editorial": "#2a78d6",
    "Scientific/Content": "#eb6834",
    "Clarification Needed": "#1baf7a",
    "Decision Required": "#eda100",
    "Other": "#e87ba4",
}

# "Not classified" isn't a real category -- it's an absence of one -- so it
# gets a neutral gray outside the categorical set rather than a sixth hue.
_NOT_CLASSIFIED_LABEL = "Not classified"
_NOT_CLASSIFIED_COLOR = "#c3c2b7"

# Resolution status is a state, not an identity, so it wears status colors
# (good / pending) rather than the categorical palette -- accepted reads as
# a settled positive outcome, CRM as something still needing action.
# Rejected isn't a "bad" outcome here (just a different editorial decision),
# so it gets the app's own neutral ink color rather than a status red.
_RESOLUTION_COLORS = {
    "accepted": "#0ca30c",
    "rejected": "#6b7280",
    "crm": "#fab219",
}
_NO_DECISION_LABEL = "No decision yet"
_NO_DECISION_COLOR = "#c3c2b7"

CHART_BAR_MAX_WIDTH = 360  # logical SVG units; must match document.html's layout


def _scale_and_sort(rows: list[dict]) -> list[dict]:
    max_count = max((row["count"] for row in rows), default=0)
    for row in rows:
        row["bar_width"] = (row["count"] / max_count * CHART_BAR_MAX_WIDTH) if max_count else 0.0
    rows.sort(key=lambda row: row["count"], reverse=True)
    return rows


def category_breakdown(comments: list[dict]) -> list[dict]:
    """One row per category (always all of CATEGORIES, even at zero) plus
    "Not classified" when any comments haven't been classified yet. Each row
    carries a bar_width scaled against the largest bucket. Sorted by count,
    descending, so the busiest category reads first -- sort order doesn't
    affect each category's assigned color, which stays fixed to the label."""
    counts: dict[str, int] = {label: 0 for label in CATEGORIES}
    not_classified = 0
    for comment in comments:
        category = comment.get("category")
        if category in counts:
            counts[category] += 1
        else:
            not_classified += 1

    rows = [
        {"label": label, "count": count, "color": _CATEGORY_COLORS[label]}
        for label, count in counts.items()
    ]
    if not_classified:
        rows.append({"label": _NOT_CLASSIFIED_LABEL, "count": not_classified, "color": _NOT_CLASSIFIED_COLOR})

    return _scale_and_sort(rows)


def resolution_breakdown(comments: list[dict]) -> list[dict]:
    """One row per resolution status (accepted / rejected / crm, always all
    three even at zero) plus "No decision yet" when any comments are still
    unresolved. Same shape and scaling as category_breakdown."""
    counts: dict[str, int] = {status: 0 for status in storage.RESOLUTION_STATUSES}
    no_decision = 0
    for comment in comments:
        status = comment.get("resolution_status")
        if status in counts:
            counts[status] += 1
        else:
            no_decision += 1

    rows = [
        {"label": storage.RESOLUTION_LABELS[status], "count": count, "color": _RESOLUTION_COLORS[status]}
        for status, count in counts.items()
    ]
    if no_decision:
        rows.append({"label": _NO_DECISION_LABEL, "count": no_decision, "color": _NO_DECISION_COLOR})

    return _scale_and_sort(rows)
