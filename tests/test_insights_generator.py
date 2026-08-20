"""Tests for the insights generator's parsing logic using a fake Anthropic
client -- no real API calls, no cost, no API key required. Whether the
insights are actually *good* is a separate question, answered by running
app/ai/anthropic_insights.py against real documents with a real key (see the
module's own __main__), not by this automated test."""

import json
import pathlib
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.ai.anthropic_insights import SYSTEM_PROMPT, AnthropicInsightsGenerator
from app.ai.base import AnalysisInsights, InsightComment, InsightTheme


def _comment(**overrides) -> InsightComment:
    fields = dict(
        document_filename="csr_draft.docx",
        author="Priya Patel (Biostatistics)",
        text="Please confirm this percentage against Table 14.3.1.",
        category=None,
        resolution_status=None,
        section="5.3.1 Overview of Adverse Events",
    )
    fields.update(overrides)
    return InsightComment(**fields)


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


class InsightsGeneratorTests(unittest.TestCase):
    def test_parses_a_well_formed_response(self):
        response_text = json.dumps(
            {
                "overview": "Reviewers repeatedly flag statistical discrepancies across both documents.",
                "themes": [{"title": "Statistical sign-off pending", "description": "Waiting on biostats."}],
            }
        )
        client = FakeClient(response_text)
        generator = AnthropicInsightsGenerator(client=client)

        result = generator.generate_insights([_comment()])

        self.assertEqual(
            result,
            AnalysisInsights(
                overview="Reviewers repeatedly flag statistical discrepancies across both documents.",
                themes=[InsightTheme(title="Statistical sign-off pending", description="Waiting on biostats.")],
            ),
        )

    def test_no_comments_short_circuits_without_an_api_call(self):
        client = FakeClient(json.dumps({"overview": "unused", "themes": []}))
        generator = AnthropicInsightsGenerator(client=client)

        result = generator.generate_insights([])

        self.assertEqual(result.themes, [])
        self.assertIsNone(client.messages.last_call_kwargs)

    def test_uses_haiku_for_cost(self):
        client = FakeClient(json.dumps({"overview": "...", "themes": []}))
        generator = AnthropicInsightsGenerator(client=client)

        generator.generate_insights([_comment()])

        self.assertEqual(client.messages.last_call_kwargs["model"], "claude-haiku-4-5")

    def test_prompt_sends_document_and_section_per_comment(self):
        client = FakeClient(json.dumps({"overview": "...", "themes": []}))
        generator = AnthropicInsightsGenerator(client=client)

        generator.generate_insights([_comment(document_filename="csr_v2.docx", section="9.3 Subgroup Analyses")])

        sent_message = client.messages.last_call_kwargs["messages"][0]["content"]
        self.assertIn("csr_v2.docx", sent_message)
        self.assertIn("9.3 Subgroup Analyses", sent_message)

    def test_system_prompt_asks_for_recurring_phrasing_and_section_patterns(self):
        # Regression guard: the whole point of this prompt (beyond generic
        # "find patterns") is to explicitly surface template-level issues --
        # wording that keeps getting corrected, or a section that keeps
        # drawing comments -- across documents, not just within one.
        self.assertIn("wording", SYSTEM_PROMPT.lower())
        self.assertIn("section", SYSTEM_PROMPT.lower())
        self.assertIn("template", SYSTEM_PROMPT.lower())


if __name__ == "__main__":
    unittest.main()
