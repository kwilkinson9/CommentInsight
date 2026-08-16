"""Renders the same chart data as app/charts.py as a PNG (via Pillow)
instead of inline SVG. python-docx can't embed SVG, so the multi-document
Word export needs a raster version of the same bar charts.

Fonts are bundled in app/static/fonts/ (see LICENSE.txt there) rather than
loaded from a system path, since this needs to render the same way on
Windows as it does here.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.charts import CHART_BAR_MAX_WIDTH

_FONT_DIR = Path(__file__).resolve().parent / "static" / "fonts"

_WIDTH = 900
_TITLE_AREA_HEIGHT = 44
_ROW_HEIGHT = 42
_TOP_PAD = 16
_BOTTOM_PAD = 16
_LABEL_X = 8
_BAR_X = 270
_BAR_MAX_WIDTH = 520
_BAR_HEIGHT = 24

_BACKGROUND = (255, 255, 255)
_TITLE_COLOR = (26, 29, 41)  # matches --text
_LABEL_COLOR = (107, 114, 128)  # matches --muted
_VALUE_COLOR = (26, 29, 41)  # matches --text


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = _FONT_DIR / name
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def render_bar_chart_png(title: str, rows: list[dict]) -> bytes:
    """rows: the same shape charts.category_breakdown() / resolution_breakdown()
    produce -- [{"label", "count", "color", "bar_width"}, ...]. bar_width is
    expressed in the SVG chart's own units (0..CHART_BAR_MAX_WIDTH) and gets
    rescaled here to this image's pixel width, so both charts stay visually
    proportional to their SVG counterparts."""
    height = _TOP_PAD + _TITLE_AREA_HEIGHT + len(rows) * _ROW_HEIGHT + _BOTTOM_PAD
    image = Image.new("RGB", (_WIDTH, max(height, 1)), _BACKGROUND)
    draw = ImageDraw.Draw(image)

    title_font = _font(24, bold=True)
    label_font = _font(17)
    value_font = _font(17, bold=True)

    draw.text((_LABEL_X, _TOP_PAD), title, font=title_font, fill=_TITLE_COLOR)

    max_svg_width = CHART_BAR_MAX_WIDTH or 1
    y = _TOP_PAD + _TITLE_AREA_HEIGHT
    for row in rows:
        bar_px = (row["bar_width"] / max_svg_width) * _BAR_MAX_WIDTH if row["bar_width"] else 0.0
        mid_y = y + _BAR_HEIGHT / 2
        draw.text((_LABEL_X, mid_y), row["label"], font=label_font, fill=_LABEL_COLOR, anchor="lm")

        if bar_px > 0:
            radius = _BAR_HEIGHT / 2 if bar_px >= _BAR_HEIGHT else max(1.0, bar_px / 2)
            draw.rounded_rectangle(
                [_BAR_X, y, _BAR_X + bar_px, y + _BAR_HEIGHT],
                radius=radius,
                fill=_hex_to_rgb(row["color"]),
            )

        draw.text((_BAR_X + bar_px + 12, mid_y), str(row["count"]), font=value_font, fill=_VALUE_COLOR, anchor="lm")
        y += _ROW_HEIGHT

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
