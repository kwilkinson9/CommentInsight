"""Tests for the classifier's parsing/validation logic using a fake Anthropic
client -- no real API calls, no cost, no API key required. Whether the
classifications are actually *good* is a separate question, answered by
running app/ai/anthropic_classifier.py against a real document with a real
key (see the module's own __main__), not by this automated test."""

import json
import pathlib
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.ai.anthropic_classifier import AnthropicClassifier
from app.ai.base import Classification
from app.ingestion.docx_parser import Comment


def _comment(**overrides) -> Comment:
    fields = dict(
        id="0",
        author="Priya Patel (Biostatistics)",
        initials="PP",
        date="2026-07-28T14:12:00Z",
        text="Please confirm this percentage against Table 14.3.1.",
        parent_id=None,
        anchor_text="67.6%",
        paragraph_text="During the 24-week treatment period... 67.6%...",
        section="5.3.1 Overview of Adverse Events",
    )
    fields.update(overrides)
    return Comment(**fields)


class FakeMessages:
    def __init__(self, response_text: str):
        self._response_text = response_text
        self.last_call_kwargs = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._response_text)])


class FakeClient:
    def __init__(self, response_text: str):
        self.messages = FakeMessages(response_text)


class ClassifierTests(unittest.TestCase):
    def test_parses_a_well_formed_response(self):
        response_text = json.dumps(
            {"category": "Scientific/Content", "rationale": "Disputes a reported percentage."}
        )
        client = FakeClient(response_text)
        classifier = AnthropicClassifier(client=client)

        result = classifier.classify(_comment())

        self.assertEqual(result, Classification("Scientific/Content", "Disputes a reported percentage."))

    def test_rejects_a_category_outside_the_known_list(self):
        response_text = json.dumps({"category": "Not A Real Category", "rationale": "..."})
        client = FakeClient(response_text)
        classifier = AnthropicClassifier(client=client)

        with self.assertRaises(ValueError):
            classifier.classify(_comment())

    def test_prompt_includes_the_comment_and_its_document_context(self):
        response_text = json.dumps({"category": "Editorial", "rationale": "..."})
        client = FakeClient(response_text)
        classifier = AnthropicClassifier(client=client)

        classifier.classify(_comment(text="Fix this typo.", anchor_text="teh", paragraph_text="...teh word..."))

        sent_message = client.messages.last_call_kwargs["messages"][0]["content"]
        self.assertIn("Fix this typo.", sent_message)
        self.assertIn("teh", sent_message)

    def test_uses_haiku_for_cost(self):
        client = FakeClient(json.dumps({"category": "Other", "rationale": "..."}))
        classifier = AnthropicClassifier(client=client)

        classifier.classify(_comment())

        self.assertEqual(client.messages.last_call_kwargs["model"], "claude-haiku-4-5")


if __name__ == "__main__":
    unittest.main()
