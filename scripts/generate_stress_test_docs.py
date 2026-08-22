"""Generates two synthetic .docx files for a heavier end-to-end test than
the smaller sample docs: a Clinical Study Report and a Phase 3 Protocol,
20 comments each, four recurring reviewers -- one of whom (Dr. Victor
Kaminski) is a deliberately difficult reviewer who leaves far more comments
than anyone else, spread across every section of both documents, in a
consistently critical tone. No real patient, trial, or company data
involved anywhere; drug code "ZX-8814" and all findings are invented.

Built to exercise things the smaller samples don't stress as hard:
  - classification/conflict-detection volume (20 comments/doc instead of 9)
  - a reviewer whose pattern the AI Insights feature should be able to name
  - two reply-thread disagreements per document (conflict detection)
  - two section headings ("Statistical Methods" and "Safety Monitoring")
    used verbatim, as flat (non-nested) headings, in BOTH documents -- so
    uploading both gives the cross-document "section hotspots" feature
    (app/charts.py's section_hotspots()) real data to show, and gives the
    AI Insights feature a genuine "same reviewer flags this everywhere"
    and "same wording keeps coming up" pattern to find.

Same OOXML approach as generate_synthetic_doc.py (python-docx can't create
reply threads on its own), generalized here to link more than one reply
pair per document.

Usage: python3 scripts/generate_stress_test_docs.py [output_dir]
Defaults to tests/sample_docs/
"""

from __future__ import annotations

import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "sample_docs"

W15_NS = "http://schemas.microsoft.com/office/word/2012/wordml"
COMMENTS_EXTENDED_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml"
COMMENTS_EXTENDED_RELATIONSHIP_TYPE = "http://schemas.microsoft.com/office/2011/relationships/commentsExtended"

KAMINSKI = "Dr. Victor Kaminski (Senior Medical Director)"
TORRES = "Elena Torres (Biostatistics)"
PATEL = "Raj Patel (Regulatory Affairs)"
NGUYEN = "Sophie Nguyen (Medical Writer)"
_INITIALS = {KAMINSKI: "VK", TORRES: "ET", PATEL: "RP", NGUYEN: "SN"}


def _para_id() -> str:
    return uuid.uuid4().hex[:8].upper()


def _dt(year: int, month: int, day: int, hour: int, minute: int) -> str:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _add_comment(doc: Document, run, *, author: str, text: str, date: str) -> tuple[object, str]:
    """Adds a comment and returns (Comment, its new w14:paraId) -- every
    comment gets a paraId regardless of whether it's a reply, since a later
    comment might need to reply to *it*."""
    comment = doc.add_comment(run, text=text, author=author, initials=_INITIALS[author])
    comment._element.set(qn("w:date"), date)
    para_id = _para_id()
    comment_paragraph = comment._element.find(qn("w:p"))
    comment_paragraph.set(qn("w14:paraId"), para_id)
    return comment, para_id


def _link_replies(docx_path: Path, reply_pairs: list[tuple[str, str]]) -> None:
    """Adds word/commentsExtended.xml to an already-saved .docx, wiring up
    one or more reply-thread relationships. reply_pairs: list of
    (parent_para_id, reply_para_id)."""
    entries = []
    linked_parents: set[str] = set()
    for parent_id, reply_id in reply_pairs:
        if parent_id not in linked_parents:
            entries.append(f'<w15:commentEx w15:paraId="{parent_id}" w15:done="0"/>')
            linked_parents.add(parent_id)
        entries.append(f'<w15:commentEx w15:paraId="{reply_id}" w15:paraIdParent="{parent_id}" w15:done="0"/>')

    comments_extended_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w15:commentsEx xmlns:w15="{W15_NS}">' + "".join(entries) + "</w15:commentsEx>"
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


def _para(doc: Document, *parts: str) -> list:
    """Adds a paragraph built from alternating plain-text and anchor
    strings and returns the list of runs, in order -- callers pick out
    whichever runs they want to attach a comment to. Every part becomes
    its own run so any part can be an independent comment anchor."""
    p = doc.add_paragraph()
    return [p.add_run(part) for part in parts]


def build_csr() -> tuple[Document, list[tuple[str, str]]]:
    doc = Document()
    doc.add_heading("Clinical Study Report -- ZX-8814-301", level=0)

    doc.add_heading("1. Efficacy Results", level=1)
    doc.add_heading("1.1 Primary Endpoint", level=2)
    runs = _para(
        doc,
        "The primary endpoint, change from baseline in the ",
        "composite symptom index",
        " at Week 16, demonstrated a statistically significant improvement in the ZX-8814 arm compared to placebo (",
        "least-squares mean difference",
        " ",
        "-5.1 points, 95% CI -7.2 to -3.0, p<0.001",
        ").",
    )
    _add_comment(doc, runs[5], author=KAMINSKI, date=_dt(2026, 8, 10, 9, 0), text=(
        "This effect size is smaller than what was presented at the investigator meeting. Either "
        "the numbers changed or nobody bothered to check them before circulating this draft. Which is it?"
    ))
    _add_comment(doc, runs[3], author=TORRES, date=_dt(2026, 8, 10, 10, 15), text=(
        "Confirmed this matches the final MMRM output in Table 14.2.1.1. No discrepancy on my end."
    ))
    _add_comment(doc, runs[1], author=PATEL, date=_dt(2026, 8, 10, 11, 0), text=(
        "Please spell out the full name of this index on first use -- reviewers outside the study "
        "team won't know what this refers to."
    ))

    doc.add_heading("1.2 Secondary Endpoints", level=2)
    runs = _para(
        doc,
        "Responder rates (defined as ≥40% reduction in composite symptom index) were ",
        "58% in the ZX-8814 arm versus 34% in placebo",
        " (p=0.004). Time to onset of response was also significantly shorter with ZX-8814 (",
        "median 12 days vs 21 days",
        ").",
    )
    _add_comment(doc, runs[1], author=KAMINSKI, date=_dt(2026, 8, 10, 13, 30), text=(
        "Nobody on this team seems to proofread before sending things to me. Table 14.2.3 says "
        "57%, not 58%. I shouldn't have to catch this."
    ))
    _add_comment(doc, runs[1], author=NGUYEN, date=_dt(2026, 8, 10, 14, 10), text=(
        "Checked against Table 14.2.3 -- it does say 57%. Will correct to 57% throughout this paragraph."
    ))
    _add_comment(doc, runs[3], author=TORRES, date=_dt(2026, 8, 10, 14, 45), text=(
        "Suggest adding the hazard ratio and CI here for consistency with how we reported "
        "time-to-event data in Section 1.1."
    ))

    doc.add_heading("1.3 Subgroup Analyses", level=2)
    runs = _para(
        doc,
        "In the subgroup of patients over 65 years of age, the treatment effect was attenuated "
        "(LS mean difference -2.3, 95% CI -5.1 to 0.5) and ",
        "did not reach statistical significance",
        ", though the subgroup was small (n=28).",
    )
    _, parent_1 = _add_comment(doc, runs[1], author=KAMINSKI, date=_dt(2026, 8, 11, 9, 5), text=(
        "This is exactly the kind of hedging language that makes a CSR look like it's hiding "
        "something. Just say the drug doesn't work as well in older patients and move on."
    ))
    _, reply_1 = _add_comment(doc, runs[1], author=TORRES, date=_dt(2026, 8, 11, 10, 20), text=(
        "Disagree strongly. With n=28 this subgroup is underpowered by design -- 'doesn't work as "
        "well' overstates what the data can actually support. The current wording is accurate and "
        "appropriately cautious."
    ))

    doc.add_heading("2. Safety Results", level=1)
    doc.add_heading("2.1 Overview of Adverse Events", level=2)
    runs = _para(
        doc,
        "Treatment-emergent adverse events (",
        "TEAEs",
        ") were reported in ",
        "61% of subjects",
        " in the ZX-8814 arm compared to 52% in the placebo arm. The most commonly reported TEAEs "
        "in the active arm were ",
        "headache (14.2%), nausea (11.8%), and fatigue (9.3%)",
        ".",
    )
    _add_comment(doc, runs[3], author=KAMINSKI, date=_dt(2026, 8, 11, 11, 0), text=(
        "61% of subjects had an adverse event and this is buried in a single sentence with no "
        "discussion? This section reads like it was written to be skimmed past, not read."
    ))
    _add_comment(doc, runs[5], author=PATEL, date=_dt(2026, 8, 11, 11, 40), text=(
        "Please confirm these percentages are all-causality, not just treatment-related, and label "
        "accordingly -- Table 12.1 in the appendix isn't clear on this distinction either."
    ))
    _add_comment(doc, runs[1], author=NGUYEN, date=_dt(2026, 8, 11, 13, 15), text=(
        "Spell out on first use per house style: 'treatment-emergent adverse events (TEAEs)'."
    ))

    doc.add_heading("2.2 Deaths and Serious Adverse Events", level=2)
    runs = _para(
        doc,
        "One death occurred during the study, in a subject randomized to the active arm. The "
        "death was attributed by the investigator as ",
        "unrelated to study treatment",
        ". Serious adverse events (SAEs) occurred in ",
        "8 subjects (3.8%)",
        " in the active arm and 5 subjects (2.4%) in the placebo arm.",
    )
    _, parent_2 = _add_comment(doc, runs[1], author=KAMINSKI, date=_dt(2026, 8, 12, 9, 0), text=(
        "A death in the active arm gets one sentence and an 'unrelated' with no supporting detail? "
        "I don't find this convincing and I doubt a reviewer at the agency will either."
    ))
    _, reply_2 = _add_comment(doc, runs[1], author=PATEL, date=_dt(2026, 8, 12, 10, 30), text=(
        "The full causality narrative is in Appendix 16.2.7 including the autopsy findings -- I "
        "think we should add a cross-reference here rather than restating it, but I don't think "
        "the causality assessment itself is in question."
    ))
    _add_comment(doc, runs[3], author=KAMINSKI, date=_dt(2026, 8, 12, 11, 15), text=(
        "This SAE rate looks high to me and there's no comparison to what was seen in the Phase 2 "
        "study. We can't just present a number in isolation like this."
    ))

    # Deliberately flat (level 1, not nested under "2. Safety Results") and
    # named identically to a section in the protocol -- see module docstring.
    doc.add_heading("Safety Monitoring", level=1)
    runs = _para(
        doc,
        "An independent Data Safety Monitoring Board (DSMB) reviewed unblinded safety data on a "
        "quarterly basis",
        " throughout the study and ",
        "did not recommend any changes",
        " to the study conduct.",
    )
    _add_comment(doc, runs[2], author=KAMINSKI, date=_dt(2026, 8, 12, 14, 0), text=(
        "'Did not recommend any changes' is doing a lot of work in this sentence. Were there any "
        "safety signals discussed at all, even ones not acted on? This needs more detail or it "
        "reads as evasive."
    ))
    _add_comment(doc, runs[0], author=TORRES, date=_dt(2026, 8, 12, 14, 40), text=(
        "Suggest adding the actual DSMB meeting dates here, we have them in the TMF and it "
        "strengthens the narrative."
    ))

    # Also deliberately flat and shared verbatim with the protocol.
    doc.add_heading("Statistical Methods", level=1)
    runs = _para(
        doc,
        "All efficacy analyses were performed on the intent-to-treat population using a ",
        "mixed-effects model for repeated measures (MMRM)",
        ", with treatment, visit, and treatment-by-visit interaction as fixed effects and ",
        "baseline score as a covariate",
        ".",
    )
    _add_comment(doc, runs[1], author=KAMINSKI, date=_dt(2026, 8, 13, 9, 0), text=(
        "Every section of this document assumes the reader already knows our statistical methods "
        "cold. Add a sentence explaining why MMRM was chosen over a simpler ANCOVA approach, or "
        "reviewers will ask."
    ))
    _add_comment(doc, runs[3], author=TORRES, date=_dt(2026, 8, 13, 9, 45), text=(
        "This matches the pre-specified SAP Section 9.2 exactly. No changes needed."
    ))

    doc.add_heading("5. Discussion and Conclusions", level=1)
    runs = _para(
        doc,
        "Overall, ZX-8814 demonstrated a ",
        "favorable efficacy and safety profile",
        " in this study population, ",
        "supporting its continued clinical development",
        ".",
    )
    _add_comment(doc, runs[1], author=KAMINSKI, date=_dt(2026, 8, 13, 11, 0), text=(
        "After everything flagged in Sections 1 and 2, calling this 'favorable' without any "
        "caveats feels like spin, not a conclusion. This needs to be rewritten to actually reflect "
        "what the data showed."
    ))
    _add_comment(doc, runs[3], author=PATEL, date=_dt(2026, 8, 13, 13, 0), text=(
        "Agree with the overall conclusion. Suggest softening 'favorable' to 'generally favorable' "
        "given the subgroup and safety findings raised elsewhere -- small wording change, addresses "
        "the concern without a full rewrite."
    ))

    return doc, [(parent_1, reply_1), (parent_2, reply_2)]


def build_protocol() -> tuple[Document, list[tuple[str, str]]]:
    doc = Document()
    doc.add_heading("Phase 3 Protocol -- ZX-8814-301", level=0)

    doc.add_heading("1. Study Objectives", level=1)
    runs = _para(
        doc,
        "The primary objective of this study is to evaluate the efficacy of ZX-8814 compared to "
        "placebo in reducing ",
        "composite symptom index scores",
        " at Week 16. Secondary objectives include evaluating safety, tolerability, and ",
        "time to onset of response",
        ".",
    )
    _add_comment(doc, runs[1], author=KAMINSKI, date=_dt(2026, 7, 20, 9, 0), text=(
        "This objective doesn't say anything about clinical meaningfulness, only statistical "
        "change. If we can't define what a meaningful improvement looks like, the whole study is "
        "measuring the wrong thing."
    ))
    _add_comment(doc, runs[3], author=NGUYEN, date=_dt(2026, 7, 20, 9, 40), text=(
        "Recommend listing this as a key secondary rather than folding it into 'secondary "
        "objectives' generally -- it's called out separately in the SAP."
    ))

    doc.add_heading("2. Study Design", level=1)
    runs = _para(
        doc,
        "This is a randomized, double-blind, placebo-controlled, ",
        "multicenter",
        " Phase 3 study. ",
        "Approximately 240 subjects",
        " will be ",
        "randomized 1:1",
        " to receive ZX-8814 or matching placebo for 16 weeks.",
    )
    _add_comment(doc, runs[5], author=KAMINSKI, date=_dt(2026, 7, 20, 10, 15), text=(
        "Why 1:1 and not something that gives us more active-arm safety exposure given this is a "
        "novel mechanism? This should at least be discussed and justified, not just stated."
    ))
    _add_comment(doc, runs[3], author=TORRES, date=_dt(2026, 7, 20, 11, 0), text=(
        "This matches the sample size calculation in Section 6. No issue."
    ))
    _add_comment(doc, runs[1], author=PATEL, date=_dt(2026, 7, 20, 11, 30), text=(
        "Please specify approximate number of sites and countries here -- Health Authorities will "
        "ask, better to have it up front."
    ))

    doc.add_heading("3. Eligibility Criteria", level=1)
    doc.add_heading("3.1 Inclusion Criteria", level=2)
    runs = _para(
        doc,
        "Subjects must be ",
        "aged 18 to 75 years",
        ", have a confirmed diagnosis for at least 6 months prior to screening, and have a ",
        "baseline composite symptom index score of at least 12",
        ".",
    )
    _, parent_1 = _add_comment(doc, runs[1], author=KAMINSKI, date=_dt(2026, 7, 21, 9, 0), text=(
        "An upper age cutoff of 75 with no rationale given is going to get flagged by the agency. "
        "This entire criteria section reads like it was copied from a template without being "
        "tailored to this drug."
    ))
    _, reply_1 = _add_comment(doc, runs[1], author=TORRES, date=_dt(2026, 7, 21, 9, 50), text=(
        "Disagree that this needs a major rework -- an upper age bound of 75 is standard for this "
        "drug class given the exclusion criteria already address relevant comorbidities. A one-line "
        "rationale would resolve this, not a rewrite."
    ))
    _add_comment(doc, runs[3], author=NGUYEN, date=_dt(2026, 7, 21, 10, 30), text=(
        "Confirm this threshold matches what's used in the primary endpoint definition in Section "
        "1 -- want to make sure these two sections stay consistent if the threshold changes."
    ))

    doc.add_heading("3.2 Exclusion Criteria", level=2)
    runs = _para(
        doc,
        "Subjects with a ",
        "history of hepatic impairment",
        ", current use of a ",
        "strong CYP3A4 inhibitor",
        ", or participation in another investigational drug study within 30 days of screening "
        "will be excluded.",
    )
    _add_comment(doc, runs[1], author=KAMINSKI, date=_dt(2026, 7, 21, 13, 0), text=(
        "'History of hepatic impairment' is vague to the point of being meaningless. Define it "
        "with actual lab values or a specific classification, otherwise every site will interpret "
        "this differently."
    ))
    _add_comment(doc, runs[3], author=PATEL, date=_dt(2026, 7, 21, 13, 45), text=(
        "Suggest adding a reference table of prohibited medications in an appendix -- sites will "
        "ask for this regardless."
    ))

    doc.add_heading("4. Study Treatments", level=1)
    runs = _para(
        doc,
        "ZX-8814 will be administered orally once daily at a dose of ",
        "200mg",
        ". Placebo will be ",
        "matched in appearance",
        " and administered on the same schedule. ",
        "Dose reductions to 100mg are permitted",
        " for tolerability.",
    )
    _add_comment(doc, runs[5], author=KAMINSKI, date=_dt(2026, 7, 22, 9, 0), text=(
        "Permitted under what specific criteria? 'For tolerability' is not a criterion, it's a "
        "shrug. If we can't define this precisely the site staff will apply it inconsistently."
    ))
    _add_comment(doc, runs[1], author=TORRES, date=_dt(2026, 7, 22, 9, 45), text=(
        "Confirmed this matches the Phase 2 dose-finding results. No concerns."
    ))
    _add_comment(doc, runs[3], author=NGUYEN, date=_dt(2026, 7, 22, 10, 20), text=(
        "Suggest 'identical in appearance' -- 'matched' is a little ambiguous here."
    ))

    # Deliberately flat and shared verbatim with the CSR.
    doc.add_heading("Statistical Methods", level=1)
    runs = _para(
        doc,
        "The primary endpoint will be analyzed using a ",
        "mixed-effects model for repeated measures (MMRM)",
        ", with treatment, visit, and treatment-by-visit interaction as fixed effects and baseline "
        "score as a covariate. The study is ",
        "powered at 90% to detect a treatment difference of 4 points",
        ".",
    )
    _add_comment(doc, runs[3], author=KAMINSKI, date=_dt(2026, 7, 22, 13, 0), text=(
        "Where does the 4-point assumption come from? If it's not justified with a citation or "
        "pilot data, statisticians reviewing this will ask, and so will I."
    ))
    _add_comment(doc, runs[1], author=TORRES, date=_dt(2026, 7, 22, 13, 50), text=(
        "This is consistent with the analysis approach used in the Phase 2 study -- keeping the "
        "same model here is the right call for comparability."
    ))

    doc.add_heading("6. Sample Size", level=1)
    runs = _para(
        doc,
        "Assuming a ",
        "standard deviation of 9 points",
        " and a two-sided alpha of 0.05, 240 subjects (120 per arm) provides 90% power to detect "
        "the assumed treatment difference, accounting for an ",
        "estimated 15% dropout rate",
        ".",
    )
    _add_comment(doc, runs[3], author=KAMINSKI, date=_dt(2026, 7, 23, 9, 0), text=(
        "15% feels optimistic for a 16-week study in this population. What was the actual dropout "
        "rate in Phase 2? If it was higher than this, the sample size is undersized and that's a "
        "real problem, not a nitpick."
    ))
    _add_comment(doc, runs[1], author=PATEL, date=_dt(2026, 7, 23, 9, 50), text=(
        "Please cite the source study this SD estimate is drawn from."
    ))

    # Deliberately flat and shared verbatim with the CSR.
    doc.add_heading("Safety Monitoring", level=1)
    runs = _para(
        doc,
        "An independent Data Safety Monitoring Board (DSMB) will review unblinded safety data on a ",
        "quarterly basis",
        " throughout the study and will have the authority to ",
        "recommend study modifications or termination",
        " based on emerging safety data.",
    )
    _, parent_2 = _add_comment(doc, runs[1], author=KAMINSKI, date=_dt(2026, 7, 24, 9, 0), text=(
        "Quarterly is too infrequent for a novel mechanism in this population. This should be "
        "monthly for at least the first two cohorts, and I don't think that's negotiable."
    ))
    _, reply_2 = _add_comment(doc, runs[1], author=PATEL, date=_dt(2026, 7, 24, 9, 45), text=(
        "Disagree -- quarterly is consistent with what Health Authorities accepted for the Phase 2 "
        "DSMB charter, and there's no new safety signal from Phase 2 that would justify a more "
        "frequent schedule. Happy to revisit if new data comes in."
    ))
    _add_comment(doc, runs[3], author=NGUYEN, date=_dt(2026, 7, 24, 10, 30), text=(
        "Suggest adding a sentence on how DSMB recommendations get communicated to sites and the "
        "timeline for implementation -- not currently specified anywhere in this section."
    ))

    return doc, [(parent_1, reply_1), (parent_2, reply_2)]


def main() -> None:
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    csr_path = output_dir / "comment_insight_synthetic_sample_3_csr.docx"
    doc, reply_pairs = build_csr()
    doc.save(csr_path)
    _link_replies(csr_path, reply_pairs)
    print(f"Wrote {csr_path}")

    protocol_path = output_dir / "comment_insight_synthetic_sample_4_protocol.docx"
    doc, reply_pairs = build_protocol()
    doc.save(protocol_path)
    _link_replies(protocol_path, reply_pairs)
    print(f"Wrote {protocol_path}")


if __name__ == "__main__":
    main()
