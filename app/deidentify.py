"""Best-effort local detection of likely patient-identifying details in
free-text document content, so they can be scrubbed out of whatever gets
sent to Claude's API.

This runs entirely on this machine -- no network calls, no third-party
service -- since the whole point is to avoid sending raw identifying text
anywhere external in the first place. It combines two approaches:

  - Regex for things with a predictable shape: emails, phone numbers,
    SSNs, specific dates, and explicitly-labeled identifiers ("MRN:",
    "DOB:", etc.).
  - A small local NLP model (spaCy's en_core_web_sm) for the fuzzier
    case -- names and places written as ordinary prose, which no regex
    can reliably catch.

Deliberately NOT covered: reviewer/author names (that's professional
context the app needs, not patient data -- see app/ai/service.py, which
only ever redacts comment text/anchor_text/paragraph_text, never the
author field), and bare numbers that could just as easily be a subject ID,
a p-value, or a table reference -- flagging every number in a clinical
document would bury the real findings in false positives.

This is a mitigation, not a guarantee. Pattern-matching and a small local
model will both miss things a person would catch (unusual names, an
indirectly identifying combination of details) and can also over-flag
things that aren't actually identifying. It's meant to sit alongside a
human confirmation step (see the review screen in dashboard.py), not
replace one. See SECURITY.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache


@dataclass
class Finding:
    kind: str  # short label shown on the review screen, e.g. "email"
    text: str  # the actual matched text


_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
# Explicitly-labeled identifiers -- unambiguous (a human already labeled
# it as an identifier), unlike a bare number that could be anything.
# [\w/-]+ (not \S+) so trailing punctuation like the comma in "DOB 4/1/85,"
# or the closing paren in "(MRN 12345)" doesn't get swallowed into the match.
_LABELED_ID_RE = re.compile(
    r"\b(?:MRN|SSN|DOB|patient\s*(?:id|name)|medical\s*record\s*(?:number|no\.?)|"
    r"date\s*of\s*birth)\s*[:#]?\s*[\w/-]+",
    re.IGNORECASE,
)

# Order matters: earlier patterns claim their span first, so a later,
# more generic pattern (e.g. a bare date) skips text a more specific one
# (e.g. a labeled "DOB 4/1/85") already matched -- see the overlap check
# in scan().
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("labeled identifier", _LABELED_ID_RE),
    ("email", _EMAIL_RE),
    ("phone number", _PHONE_RE),
    ("SSN", _SSN_RE),
    ("specific date", _DATE_RE),
]

_PERSON_PLACE_LABELS = {"PERSON": "person name", "GPE": "place name", "LOC": "place name"}


@lru_cache(maxsize=1)
def _nlp():
    import spacy

    try:
        return spacy.load("en_core_web_sm")
    except OSError as exc:
        raise RuntimeError(
            "The local name/place detector isn't installed. Run "
            "`python -m spacy download en_core_web_sm` and try again."
        ) from exc


def scan(text: str | None) -> list[Finding]:
    """Every likely-identifying span found in text, via regex first (exact
    matches win) then the local NER model for names/places that don't
    overlap a regex match already found."""
    if not text:
        return []

    findings: list[Finding] = []
    matched_spans: list[tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(s < end and start < e for s, e in matched_spans)

    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            if overlaps(*m.span()):
                continue
            findings.append(Finding(kind=kind, text=m.group(0)))
            matched_spans.append(m.span())

    for ent in _nlp()(text).ents:
        label = _PERSON_PLACE_LABELS.get(ent.label_)
        if label is None:
            continue
        if overlaps(ent.start_char, ent.end_char):
            continue  # already covered by a more specific regex match
        findings.append(Finding(kind=label, text=ent.text))
        matched_spans.append((ent.start_char, ent.end_char))

    return findings


def redact(text: str | None) -> tuple[str, list[Finding]]:
    """Returns (redacted_text, findings). Each matched span is replaced
    with a bracketed placeholder naming its kind (e.g. "[EMAIL]") rather
    than deleted outright, so Claude still sees that *something* was
    there -- useful context -- without seeing the actual value."""
    if not text:
        return text, []

    findings = scan(text)
    if not findings:
        return text, []

    redacted = text
    replaced: set[str] = set()
    # Longest matches first, so a shorter match embedded in a longer one
    # (e.g. a phone number inside a "Patient ID: ..." labeled match)
    # doesn't get replaced out from under the longer one first.
    for finding in sorted(findings, key=lambda f: len(f.text), reverse=True):
        if finding.text in replaced:
            continue
        replaced.add(finding.text)
        redacted = redacted.replace(finding.text, f"[{finding.kind.upper()}]")

    return redacted, findings
