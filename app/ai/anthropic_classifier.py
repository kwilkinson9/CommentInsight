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

- Editorial: wording, grammar, style, or formatting changes that do not affect \
scientific or regulatory meaning.
- Scientific/Content: questions or objections about data accuracy, statistical or \
clinical claims, or the factual correctness of the content.
- Clarification Needed: the reviewer is asking a question or requesting clarification \
about what the text means or what it refers to, rather than proposing a specific change.
- Decision Required: resolving the comment requires a judgment call, sign-off, or \
input from someone other than the writer -- not a straightforward fix.
- Other: doesn't clearly fit the above (e.g. a comment with no requested action).

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
