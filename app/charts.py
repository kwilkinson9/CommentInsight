"""Data for the "comments by category" chart on the document page.

No JS chart library -- the app stays server-rendered HTML, so this module
only computes plain numbers (label / count / color / bar length). The
actual <svg> markup lives in the document template.
"""

from __future__ import annotations

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

CHART_BAR_MAX_WIDTH = 360  # logical SVG units; must match document.html's layout


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

    max_count = max((row["count"] for row in rows), default=0)
    for row in rows:
        row["bar_width"] = (row["count"] / max_count * CHART_BAR_MAX_WIDTH) if max_count else 0.0

    rows.sort(key=lambda row: row["count"], reverse=True)
    return rows
