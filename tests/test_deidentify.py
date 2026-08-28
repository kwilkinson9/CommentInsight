"""Tests for app/deidentify.py -- the local (no-network) best-effort scan
for likely patient-identifying details, used to scrub text before it's
sent to Claude's API. See the module docstring for what this is and isn't."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import deidentify


class ScanTests(unittest.TestCase):
    def test_empty_and_none_text_finds_nothing(self):
        self.assertEqual(deidentify.scan(""), [])
        self.assertEqual(deidentify.scan(None), [])

    def test_ordinary_clinical_prose_has_no_false_positives(self):
        text = (
            "The primary endpoint showed a significant improvement (p<0.001) at "
            "Week 12, per Table 14.3.1. Subject 1042-003 discontinued due to an AE."
        )
        self.assertEqual(deidentify.scan(text), [])

    def test_finds_email(self):
        findings = deidentify.scan("Contact jane.smith@example.com for details.")
        kinds = [f.kind for f in findings]
        self.assertIn("email", kinds)

    def test_finds_phone_number(self):
        findings = deidentify.scan("Call the site at 614-555-0192 to confirm.")
        self.assertTrue(any(f.kind == "phone number" for f in findings))

    def test_finds_ssn(self):
        findings = deidentify.scan("SSN on file: 123-45-6789.")
        # Matched by the more specific "labeled identifier" pattern since
        # it's explicitly prefixed with SSN -- either way it must be found.
        self.assertTrue(any("123-45-6789" in f.text for f in findings))

    def test_finds_specific_date(self):
        findings = deidentify.scan("The event occurred on 04/12/1985.")
        self.assertTrue(any(f.kind == "specific date" for f in findings))

    def test_relative_dates_are_not_flagged(self):
        findings = deidentify.scan("The visit occurred at Week 12, Day 3 of the study.")
        self.assertEqual(findings, [])

    def test_finds_labeled_identifiers(self):
        for snippet in ["MRN 445829", "DOB 04/12/1985", "Patient ID: 8871"]:
            findings = deidentify.scan(f"Notes: {snippet} on file.")
            self.assertTrue(any(f.kind == "labeled identifier" for f in findings), snippet)

    def test_finds_person_name_via_local_ner(self):
        findings = deidentify.scan("The subject, Jane Smith, reported a headache.")
        self.assertTrue(any(f.kind == "person name" and "Jane Smith" in f.text for f in findings))

    def test_finds_place_name_via_local_ner(self):
        findings = deidentify.scan("The subject resides in Columbus, Ohio.")
        kinds = [f.kind for f in findings]
        self.assertIn("place name", kinds)

    def test_overlapping_matches_are_not_double_counted(self):
        # "DOB 04/12/1985" should be caught once by the labeled-identifier
        # pattern, not also separately as a bare "specific date".
        findings = deidentify.scan("DOB 04/12/1985 confirmed at screening.")
        date_like = [f for f in findings if "04/12/1985" in f.text]
        self.assertEqual(len(date_like), 1)
        self.assertEqual(date_like[0].kind, "labeled identifier")


class RedactTests(unittest.TestCase):
    def test_clean_text_is_returned_unchanged_with_no_findings(self):
        text = "No changes needed here, looks good."
        redacted, findings = deidentify.redact(text)
        self.assertEqual(redacted, text)
        self.assertEqual(findings, [])

    def test_none_text_passes_through(self):
        redacted, findings = deidentify.redact(None)
        self.assertIsNone(redacted)
        self.assertEqual(findings, [])

    def test_matched_text_is_replaced_with_a_placeholder(self):
        redacted, findings = deidentify.redact("Contact jane.smith@example.com please.")
        self.assertNotIn("jane.smith@example.com", redacted)
        self.assertIn("[EMAIL]", redacted)
        self.assertEqual(len(findings), 1)

    def test_punctuation_around_a_match_is_preserved(self):
        redacted, _ = deidentify.redact("(MRN 445829) confirmed.")
        self.assertTrue(redacted.startswith("("))
        self.assertIn(")", redacted)

    def test_does_not_redact_things_that_are_not_flagged(self):
        redacted, _ = deidentify.redact("Table 14.3.1 shows a p-value of 0.002.")
        self.assertIn("Table 14.3.1", redacted)
        self.assertIn("0.002", redacted)

    def test_returned_findings_match_what_scan_would_report(self):
        text = "Reach Dr. Jane Smith at jane.smith@example.com."
        _, redact_findings = deidentify.redact(text)
        scan_findings = deidentify.scan(text)
        self.assertEqual(
            sorted((f.kind, f.text) for f in redact_findings),
            sorted((f.kind, f.text) for f in scan_findings),
        )


if __name__ == "__main__":
    unittest.main()
