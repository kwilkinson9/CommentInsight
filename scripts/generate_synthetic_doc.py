"""Generates a synthetic .docx with fake reviewer comments for testing --
no real patient, trial, or company data involved anywhere.

python-docx (1.2+) can add native Word comments via Document.add_comment(),
which covers everything docx_parser.py reads *except* reply threads: Word
links a reply to its parent via a w14:paraId on each comment's paragraph
plus a <w15:commentEx> entry in word/commentsExtended.xml, and python-docx
doesn't create either. This script builds the document with python-docx,
then does a small amount of manual OOXML surgery afterward to add exactly
one reply thread (for testing conflict detection, which depends on a real
reply-to relationship existing).

Usage: python3 scripts/generate_synthetic_doc.py [output_path]
Defaults to tests/sample_docs/comment_insight_synthetic_sample_2.docx
"""

from __future__ import annotations

import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "tests" / "sample_docs" / "comment_insight_synthetic_sample_2.docx"

W15_NS = "http://schemas.microsoft.com/office/word/2012/wordml"
COMMENTS_EXTENDED_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml"
COMMENTS_EXTENDED_RELATIONSHIP_TYPE = "http://schemas.microsoft.com/office/2011/relationships/commentsExtended"


def _para_id() -> str:
    """An 8-hex-digit id in the style Word generates for w14:paraId."""
    return uuid.uuid4().hex[:8].upper()


def _dt(month: int, day: int, hour: int, minute: int) -> str:
    return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _add_comment(doc: Document, run, *, author: str, initials: str, text: str, date: str) -> tuple[object, str]:
    """Adds a comment and returns (Comment, its new w14:paraId) -- every
    comment gets a paraId regardless of whether it's a reply, since a later
    comment might need to reply to *it*."""
    comment = doc.add_comment(run, text=text, author=author, initials=initials)
    comment._element.set(qn("w:date"), date)
    para_id = _para_id()
    comment_paragraph = comment._element.find(qn("w:p"))
    comment_paragraph.set(qn("w14:paraId"), para_id)
    return comment, para_id


def build_document() -> tuple[Document, dict[str, str]]:
    """Returns (document, {"parent_para_id": ..., "reply_para_id": ...})."""
    doc = Document()

    doc.add_heading("9. Efficacy Results", level=1)
    doc.add_heading("9.1 Primary Endpoint", level=2)

    p1 = doc.add_paragraph()
    p1.add_run(
        "The primary endpoint, change from baseline in the total symptom score at "
        "Week 12, showed a statistically significant improvement in the treatment "
        "arm compared to placebo (least-squares mean difference "
    )
    p1_target = p1.add_run("-4.2 points, 95% CI -6.1 to -2.3, p<0.001")
    p1.add_run(").")
    _add_comment(
        doc, p1_target,
        author="Elena Rodriguez (Biostatistics Lead)", initials="ER",
        text=(
            "Please confirm this LS mean difference matches the SAP-specified MMRM "
            "model output in Table 9.1.2 -- the value in my analysis dataset shows "
            "-4.4, not -4.2."
        ),
        date=_dt(8, 3, 14, 10),
    )

    p2 = doc.add_paragraph()
    p2.add_run("A sensitivity analysis using ")
    p2_target = p2.add_run("multiple imputation")
    p2.add_run(" for missing data produced consistent results, supporting the robustness of the primary analysis.")
    _add_comment(
        doc, p2_target,
        author="Tom Bennett (Medical Writer)", initials="TB",
        text=(
            "Should we specify which imputation method (MICE vs. LOCF) was used "
            "here, or does the SAP allow either? Want to make sure this matches "
            "Section 7.4."
        ),
        date=_dt(8, 3, 15, 45),
    )

    doc.add_heading("9.2 Secondary Endpoints", level=2)

    p3 = doc.add_paragraph()
    p3.add_run(
        "Responder rates (defined as ≥50% reduction in symptom score) were 62% "
        "in the treatment group versus 38% in placebo (p=0.002). "
    )
    p3_target = p3.add_run("This meaningful difference supports a favorable overall clinical benefit.")
    _add_comment(
        doc, p3_target,
        author="Tom Bennett (Medical Writer)", initials="TB",
        text="Suggest changing 'meaningful' to 'clinically meaningful' for consistency with how we describe effect sizes elsewhere in the CSR.",
        date=_dt(8, 4, 9, 20),
    )

    p4 = doc.add_paragraph()
    p4.add_run("Time to symptom relief was also significantly shorter in the treatment arm (median 3.2 days vs 5.8 days, ")
    p4_target = p4.add_run("HR 1.8, 95% CI 1.3-2.5")
    p4.add_run(").")
    _add_comment(
        doc, p4_target,
        author="Dr. Aisha Khan (Clinical Pharmacology)", initials="AK",
        text=(
            "We need to decide whether to report the hazard ratio here or defer to "
            "the time-to-event section in 9.4, since presenting it twice with "
            "slightly different confidence intervals could confuse reviewers. "
            "Please confirm approach with the biostatistics lead before finalizing."
        ),
        date=_dt(8, 4, 11, 5),
    )

    doc.add_heading("9.3 Subgroup Analyses", level=2)

    p5 = doc.add_paragraph()
    p5.add_run(
        "In the subgroup of patients with moderate baseline severity, the treatment "
        "effect was attenuated (LS mean difference -2.1, 95% CI -4.5 to 0.3) and "
    )
    p5_target = p5.add_run("did not reach statistical significance")
    p5.add_run(".")
    parent_comment, parent_para_id = _add_comment(
        doc, p5_target,
        author="Dr. Marcus Webb (Principal Investigator)", initials="MW",
        text=(
            "Given the wide confidence interval and small subgroup size (n=34), I "
            "don't think we should describe this as a true attenuation of effect -- "
            "more likely underpowered. Recommend softening this language."
        ),
        date=_dt(8, 5, 10, 0),
    )
    # The reply is anchored on the same run as the original -- Word allows
    # multiple comments to share an anchor, and this is the realistic case
    # (a reviewer disagreeing with a comment, not with the manuscript text).
    reply_comment, reply_para_id = _add_comment(
        doc, p5_target,
        author="Elena Rodriguez (Biostatistics Lead)", initials="ER",
        text=(
            "Disagree -- the CI still crosses zero and includes negative values "
            "in the placebo-favoring direction, which is a meaningfully different "
            "signal than the overall population. I think the current wording is "
            "appropriately cautious and shouldn't be softened."
        ),
        date=_dt(8, 5, 13, 40),
    )

    p6 = doc.add_paragraph()
    p6_target = p6.add_run("No clinically meaningful differences in treatment effect were observed across age, sex, or region subgroups (Figure 9.3.1).")
    _add_comment(
        doc, p6_target,
        author="Dr. Aisha Khan (Clinical Pharmacology)", initials="AK",
        text="Clean summary, no changes needed here.",
        date=_dt(8, 5, 16, 15),
    )

    doc.add_heading("9.4 Time-to-Event Analysis", level=2)

    p7 = doc.add_paragraph()
    p7_target = p7.add_run("Kaplan-Meier estimates showed separation between treatment arms beginning at Week 2 and persisting through Week 12 (Figure 9.4.1).")
    _add_comment(
        doc, p7_target,
        author="Tom Bennett (Medical Writer)", initials="TB",
        text="Should we note the number of patients still at risk at each landmark timepoint, or is that only needed in the statistical appendix?",
        date=_dt(8, 6, 9, 30),
    )

    p8 = doc.add_paragraph()
    p8.add_run("The proportional hazards assumption was tested using Schoenfeld residuals and ")
    p8_target = p8.add_run("was not violated")
    p8.add_run(" (p=0.41).")
    _add_comment(
        doc, p8_target,
        author="Dr. Marcus Webb (Principal Investigator)", initials="MW",
        text="Minor: 'was not violated' reads awkwardly -- suggest 'held' or 'was satisfied'.",
        date=_dt(8, 7, 8, 50),
    )

    return doc, {"parent_para_id": parent_para_id, "reply_para_id": reply_para_id}


def _link_reply(docx_path: Path, parent_para_id: str, reply_para_id: str) -> None:
    """Adds word/commentsExtended.xml to an already-saved .docx and wires it
    into [Content_Types].xml + word/_rels/document.xml.rels, so the reply
    comment resolves to its parent the same way docx_parser.py expects."""
    comments_extended_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w15:commentsEx xmlns:w15="{W15_NS}">'
        f'<w15:commentEx w15:paraId="{parent_para_id}" w15:done="0"/>'
        f'<w15:commentEx w15:paraId="{reply_para_id}" w15:paraIdParent="{parent_para_id}" w15:done="0"/>'
        "</w15:commentsEx>"
    )

    tmp_path = docx_path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(docx_path, "r") as src, zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)

            if item.filename == "[Content_Types].xml":
                override = f'<Override PartName="/word/commentsExtended.xml" ContentType="{COMMENTS_EXTENDED_CONTENT_TYPE}"/>'
                data = data.replace(b"</Types>", override.encode("utf-8") + b"</Types>")
            elif item.filename == "word/_rels/document.xml.rels":
                relationship = (
                    f'<Relationship Id="rIdCommentsExtended" '
                    f'Type="{COMMENTS_EXTENDED_RELATIONSHIP_TYPE}" Target="commentsExtended.xml"/>'
                )
                data = data.replace(b"</Relationships>", relationship.encode("utf-8") + b"</Relationships>")

            dst.writestr(item, data)

        dst.writestr("word/commentsExtended.xml", comments_extended_xml)

    tmp_path.replace(docx_path)


def main() -> None:
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc, para_ids = build_document()
    doc.save(output_path)
    _link_reply(output_path, para_ids["parent_para_id"], para_ids["reply_para_id"])

    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
