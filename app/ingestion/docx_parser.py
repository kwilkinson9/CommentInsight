"""Extract reviewer comments (and their surrounding context) from a .docx file.

A .docx is a zip archive of XML parts. The parts relevant to comments are:
  word/document.xml          - the document body; marks WHERE each comment is
                                anchored via <w:commentRangeStart>/<w:commentRangeEnd>
  word/comments.xml          - the comment text, author, date, per comment id
  word/commentsExtended.xml  - reply-thread links (which comment replies to which)

This module has no dependencies beyond the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
W15_NS = "http://schemas.microsoft.com/office/word/2012/wordml"


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def _w14(tag: str) -> str:
    return f"{{{W14_NS}}}{tag}"


def _w15(tag: str) -> str:
    return f"{{{W15_NS}}}{tag}"


# Word's default built-in heading style ids. A document using custom heading
# styles won't be picked up by this heuristic -- acceptable for the MVP, but
# worth knowing if "location" ends up blank on a real document.
_HEADING_STYLES = {f"Heading{i}": i for i in range(1, 6)}


@dataclass
class Comment:
    id: str
    author: str
    initials: str
    date: str | None
    text: str
    parent_id: str | None
    anchor_text: str
    paragraph_text: str
    section: str | None


def _run_text(elem: ET.Element) -> str | None:
    """Return the text contributed by a single run-level element, or None if
    the element carries no text of its own (comment markers, run properties, etc.)."""
    tag = elem.tag
    if tag == _w("t"):
        return elem.text or ""
    if tag == _w("tab"):
        return "\t"
    if tag in (_w("br"), _w("cr")):
        return "\n"
    return None


def _parse_comments_xml(root: ET.Element) -> dict[str, dict]:
    """Return {comment_id: {author, initials, date, text, para_id}}."""
    comments: dict[str, dict] = {}
    for c in root.findall(_w("comment")):
        cid = c.get(_w("id"))
        paragraphs = []
        para_id = None
        for p in c.findall(_w("p")):
            if para_id is None:
                para_id = p.get(_w14("paraId"))
            texts = [
                t.text or ""
                for t in p.iter()
                if t.tag == _w("t")
            ]
            paragraphs.append("".join(texts))
        comments[cid] = {
            "author": c.get(_w("author")) or "",
            "initials": c.get(_w("initials")) or "",
            "date": c.get(_w("date")),
            "text": "\n".join(paragraphs).strip(),
            "para_id": para_id,
        }
    return comments


def _parse_comments_extended_xml(root: ET.Element) -> dict[str, str | None]:
    """Return {para_id: parent_para_id_or_None} from commentsExtended.xml."""
    parents: dict[str, str | None] = {}
    for ex in root.findall(_w15("commentEx")):
        para_id = ex.get(_w15("paraId"))
        if para_id is not None:
            parents[para_id] = ex.get(_w15("paraIdParent"))
    return parents


def _parse_document_anchors(root: ET.Element) -> tuple[dict[str, str], dict[str, str], dict[str, str | None]]:
    """Walk word/document.xml in document order and, for every comment id,
    work out the exact anchored text, the full paragraph(s) it sits in, and
    the nearest preceding heading ("section").

    Returns (anchor_text_by_id, paragraph_text_by_id, section_by_id).
    """
    anchor_text: dict[str, str] = {}
    paragraph_text: dict[str, str] = {}
    section_by_id: dict[str, str | None] = {}

    open_anchors: dict[str, list[str]] = {}       # comment id -> text chunks seen so far
    open_paragraphs: dict[str, list[str]] = {}    # comment id -> paragraph texts touched
    heading_trail: dict[int, str] = {}            # heading level -> current heading text

    body = root.find(_w("body"))
    if body is None:
        return anchor_text, paragraph_text, section_by_id

    for p in body.iter(_w("p")):
        para_chunks: list[str] = []
        closed_this_paragraph: list[str] = []

        p_pr = p.find(_w("pPr"))
        style = p_pr.find(_w("pStyle")) if p_pr is not None else None
        style_id = style.get(_w("val")) if style is not None else None

        for elem in p.iter():
            if elem.tag == _w("commentRangeStart"):
                cid = elem.get(_w("id"))
                open_anchors[cid] = []
                open_paragraphs[cid] = []
            elif elem.tag == _w("commentRangeEnd"):
                cid = elem.get(_w("id"))
                if cid in open_anchors:
                    anchor_text[cid] = "".join(open_anchors.pop(cid)).strip()
                    closed_this_paragraph.append(cid)
            else:
                text = _run_text(elem)
                if text:
                    para_chunks.append(text)
                    for buf in open_anchors.values():
                        buf.append(text)

        # Full paragraph text is only known once the whole <w:p> has been
        # walked, so record it now against every range that touched this
        # paragraph -- ones still open (spanning into the next paragraph)
        # and ones that just closed here.
        para_text = "".join(para_chunks).strip()
        for cid in set(open_paragraphs) | set(closed_this_paragraph):
            bucket = open_paragraphs.setdefault(cid, [])
            if not bucket or bucket[-1] != para_text:
                bucket.append(para_text)

        for cid in closed_this_paragraph:
            paragraph_text[cid] = "\n".join(open_paragraphs.pop(cid)).strip()
            section_by_id[cid] = " > ".join(
                heading_trail[lvl] for lvl in sorted(heading_trail)
            ) or None

        if style_id in _HEADING_STYLES:
            level = _HEADING_STYLES[style_id]
            heading_trail[level] = para_text
            for deeper in [lvl for lvl in heading_trail if lvl > level]:
                del heading_trail[deeper]

    return anchor_text, paragraph_text, section_by_id


def extract_comments(docx_path: str | Path) -> list[Comment]:
    with zipfile.ZipFile(docx_path) as zf:
        names = set(zf.namelist())
        if "word/document.xml" not in names:
            raise ValueError(f"{docx_path} does not look like a .docx (no word/document.xml)")

        document_root = ET.fromstring(zf.read("word/document.xml"))

        if "word/comments.xml" not in names:
            return []  # valid docx, just no comments in it

        comments_root = ET.fromstring(zf.read("word/comments.xml"))
        comments_meta = _parse_comments_xml(comments_root)

        parent_para_of: dict[str, str | None] = {}
        if "word/commentsExtended.xml" in names:
            ext_root = ET.fromstring(zf.read("word/commentsExtended.xml"))
            parent_para_of = _parse_comments_extended_xml(ext_root)

    anchor_text, paragraph_text, section_by_id = _parse_document_anchors(document_root)

    para_id_to_comment_id = {
        meta["para_id"]: cid for cid, meta in comments_meta.items() if meta["para_id"]
    }

    results: list[Comment] = []
    for cid, meta in comments_meta.items():
        parent_para_id = parent_para_of.get(meta["para_id"])
        parent_id = para_id_to_comment_id.get(parent_para_id) if parent_para_id else None

        results.append(
            Comment(
                id=cid,
                author=meta["author"],
                initials=meta["initials"],
                date=meta["date"],
                text=meta["text"],
                parent_id=parent_id,
                anchor_text=anchor_text.get(cid, ""),
                paragraph_text=paragraph_text.get(cid, ""),
                section=section_by_id.get(cid),
            )
        )

    results.sort(key=lambda c: int(c.id) if c.id.isdigit() else c.id)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract reviewer comments from a .docx file.")
    parser.add_argument("docx_path", help="Path to a .docx file")
    args = parser.parse_args()

    comments = extract_comments(args.docx_path)
    print(json.dumps([asdict(c) for c in comments], indent=2))
    print(f"\n{len(comments)} comment(s) extracted.", file=sys.stderr)


if __name__ == "__main__":
    main()
