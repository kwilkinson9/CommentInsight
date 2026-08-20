"""Builds an Excel (.xlsx) workbook summarizing comments across every
uploaded document -- for writers who want to pivot/filter/sort the raw
data themselves rather than read a formatted report.

Kept separate from storage.py (no DB access here, just dicts in -> bytes
out) so it can be tested and read on its own, same pattern as reports.py.
"""

from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app import storage

_HEADER_FILL = PatternFill(start_color="FDEEF0", end_color="FDEEF0", fill_type="solid")
_HEADER_FONT = Font(bold=True)


def _friendly_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return value
    hour_12 = dt.hour % 12 or 12
    am_pm = "AM" if dt.hour < 12 else "PM"
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}, {hour_12}:{dt.minute:02d} {am_pm}"


def _write_header_row(sheet, headers: list[str]) -> None:
    for col, text in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=col, value=text)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
    sheet.freeze_panes = "A2"


def _autosize_columns(sheet, widths: list[int]) -> None:
    for col, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(col)].width = width


def build_workbook(
    document_summaries: list[dict],
    chart_rows: list[dict],
    resolution_chart_rows: list[dict],
    all_comments: list[dict],
    section_hotspot_rows: list[dict] | None = None,
) -> bytes:
    wb = Workbook()

    summary = wb.active
    summary.title = "Summary"
    _write_header_row(
        summary,
        ["Filename", "Comments", "Needs Discussion", "Accepted", "Rejected", "CRM", "No Decision"],
    )
    for row_num, doc in enumerate(document_summaries, start=2):
        summary.cell(row=row_num, column=1, value=doc["filename"])
        summary.cell(row=row_num, column=2, value=doc["total"])
        summary.cell(row=row_num, column=3, value=doc["priority_count"])
        summary.cell(row=row_num, column=4, value=doc["accepted"])
        summary.cell(row=row_num, column=5, value=doc["rejected"])
        summary.cell(row=row_num, column=6, value=doc["crm"])
        summary.cell(row=row_num, column=7, value=doc["no_decision"])
    _autosize_columns(summary, [32, 11, 16, 11, 11, 8, 12])

    by_category = wb.create_sheet("By Category")
    _write_header_row(by_category, ["Category", "Count"])
    for row_num, row in enumerate(chart_rows, start=2):
        by_category.cell(row=row_num, column=1, value=row["label"])
        by_category.cell(row=row_num, column=2, value=row["count"])
    _autosize_columns(by_category, [24, 10])

    by_resolution = wb.create_sheet("By Resolution")
    _write_header_row(by_resolution, ["Resolution Status", "Count"])
    for row_num, row in enumerate(resolution_chart_rows, start=2):
        by_resolution.cell(row=row_num, column=1, value=row["label"])
        by_resolution.cell(row=row_num, column=2, value=row["count"])
    _autosize_columns(by_resolution, [24, 10])

    if section_hotspot_rows:
        by_section = wb.create_sheet("Section Hotspots")
        _write_header_row(by_section, ["Section", "Documents", "Comment count"])
        for row_num, row in enumerate(section_hotspot_rows, start=2):
            by_section.cell(row=row_num, column=1, value=row["section"])
            by_section.cell(row=row_num, column=2, value=row["document_count"])
            by_section.cell(row=row_num, column=3, value=row["count"])
        _autosize_columns(by_section, [48, 12, 14])

    all_comments_sheet = wb.create_sheet("All Comments")
    _write_header_row(
        all_comments_sheet,
        ["Document", "Reviewer", "Date", "Section", "Category", "Priority",
         "Comment", "Document Text", "Resolution", "Resolution Note"],
    )
    wrap = Alignment(wrap_text=True, vertical="top")
    for row_num, comment in enumerate(all_comments, start=2):
        all_comments_sheet.cell(row=row_num, column=1, value=comment.get("document_filename", ""))
        all_comments_sheet.cell(row=row_num, column=2, value=comment.get("author") or "")
        all_comments_sheet.cell(row=row_num, column=3, value=_friendly_date(comment.get("comment_date")))
        all_comments_sheet.cell(row=row_num, column=4, value=comment.get("section") or "")
        all_comments_sheet.cell(row=row_num, column=5, value=comment.get("category") or "Not classified")
        all_comments_sheet.cell(row=row_num, column=6, value="Yes" if comment.get("is_priority") else "")
        comment_cell = all_comments_sheet.cell(row=row_num, column=7, value=comment.get("text") or "")
        comment_cell.alignment = wrap
        anchor_cell = all_comments_sheet.cell(row=row_num, column=8, value=comment.get("anchor_text") or "")
        anchor_cell.alignment = wrap
        all_comments_sheet.cell(
            row=row_num,
            column=9,
            value=storage.RESOLUTION_LABELS.get(comment.get("resolution_status"), "No decision yet"),
        )
        note_cell = all_comments_sheet.cell(row=row_num, column=10, value=comment.get("resolution_note") or "")
        note_cell.alignment = wrap
    _autosize_columns(all_comments_sheet, [22, 24, 18, 24, 18, 9, 50, 40, 18, 30])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
