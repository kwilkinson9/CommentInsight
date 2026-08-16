"""Classifies a single reviewer comment using Claude (Haiku 4.5).

Chosen over Opus/Sonnet for cost: this is a small, repetitive, single-label
judgment call made once per comment, which is exactly the kind of task
Haiku is built for -- classifying a 100-comment document costs a fraction
of a cent. See app/ai/base.py for the categories and why "duplicate" and
"conflict" aren't in scope here.
"""

from __future__ import annotations

import json

import anthropic

from app.ai.base import CATEGORIES, Classification, Classifier
from app.ingestion.docx_parser import Comment

MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = """You triage reviewer comments on medical and regulatory documents \
for a professional medical writer. For each comment, assign exactly one category:

- Editorial: wording, grammar, punctuation, or formatting changes where the \
underlying scientific or regulatory meaning is not in question. A wording change is \
NOT Editorial if it swaps between defined regulatory/scientific terms (e.g. causality \
categories like "possibly" vs "probably related", severity grades) -- classify those \
as Scientific/Content instead, even if they look like a small word change.
- Scientific/Content: the core issue is the accuracy of data, a calculation, a \
factual claim, or whether the correct scientific/regulatory category or term was \
applied (e.g. a causality assessment, a severity grade, a reported statistic). \
Resolving it means checking data, a calculation, or a definition -- regardless of \
who ends up doing that check.
- Clarification Needed: the reviewer is asking an open question about what the text \
means or refers to, without proposing a specific fix or answer themselves. If the \
reviewer already proposes a specific resolution, use Scientific/Content, Editorial, \
or Decision Required instead, even if it's phrased as a question.
- Decision Required: resolving the comment means choosing between multiple valid, \
defensible options (e.g. how much detail to include, which section something \
belongs in, whether to expand, summarize, or escalate) rather than checking a fact \
against data or a definition. This is a discretionary call.
- Other: doesn't clearly fit the above (e.g. a comment with no requested action).

When a comment could plausibly fit two categories, prefer Scientific/Content over \
Decision Required if the dispute is fundamentally about whether something is \
factually or categorically correct, even when resolving it requires input from \
someone else (a statistician, a safety team, a medical monitor). Reserve Decision \
Required for disputes about which of several acceptable approaches to take.

Base your answer only on the comment and the document text given to you. Do not \
invent facts, and do not judge whether the reviewer is scientifically correct -- \
only classify what kind of comment this is."""


def _build_user_message(comment: Comment) -> str:
    return (
        f"Reviewer comment: {comment.text}\n\n"
        f'Text in the document this comment is attached to: "{comment.anchor_text}"\n\n'
        f'Surrounding paragraph, for context: "{comment.paragraph_text}"\n\n'
        "Classify this comment."
    )


_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": CATEGORIES},
        "rationale": {
            "type": "string",
            "description": "One sentence explaining the category, citing what in the comment led to it.",
        },
    },
    "required": ["category", "rationale"],
    "additionalProperties": False,
}


class AnthropicClassifier(Classifier):
    model_name = MODEL

    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()

    def classify(self, comment: Comment) -> Classification:
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=256,
            system=SYSTEM_PROMPT,
            output_config={"format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA}},
            messages=[{"role": "user", "content": _build_user_message(comment)}],
        )
        text = next(block.text for block in response.content if block.type == "text")
        data = json.loads(text)

        if data["category"] not in CATEGORIES:
            raise ValueError(f"Model returned an unrecognized category: {data['category']!r}")

        return Classification(category=data["category"], rationale=data["rationale"])


def main() -> None:
    """Standalone demo: classify every comment in a .docx and print the result.

    No database, no web app -- run this against a real document to see
    whether the categories actually look right before wiring this into
    the rest of the app.
    """
    import argparse

    from app.ingestion.docx_parser import extract_comments

    parser = argparse.ArgumentParser(description="Classify comments extracted from a .docx file.")
    parser.add_argument("docx_path", help="Path to a .docx file")
    args = parser.parse_args()

    comments = extract_comments(args.docx_path)
    classifier = AnthropicClassifier()

    for comment in comments:
        result = classifier.classify(comment)
        print(f"[{result.category}] {comment.author}: {comment.text}")
        print(f"    -> {result.rationale}\n")


if __name__ == "__main__":
    main()
