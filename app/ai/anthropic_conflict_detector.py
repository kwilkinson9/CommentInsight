"""Finds genuine disagreements between different reviewers' comments.

Unlike classification, this has to look at every comment in a document
together -- a conflict is a relationship between two comments, not a
property of one -- so it's one request per document, not one per comment.
"""

from __future__ import annotations

import json

import anthropic

from app.ai.base import ConflictDetector, ConflictPair
from app.ingestion.docx_parser import Comment

MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = """You review reviewer comments on a medical/regulatory document to find \
genuine disagreements between different reviewers.

Two comments are in conflict only when resolving one would contradict resolving the \
other -- they propose or imply incompatible outcomes for the same or closely related \
point in the document. Do not flag comments just because they discuss the same topic, \
raise similar concerns, or come from different reviewers -- only flag a genuine \
disagreement about what the resolution should be.

A reply comment that explicitly disagrees with the comment it replies to is always a \
conflict. Comments from the same author are never in conflict with each other. Report \
each conflicting pair only once."""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "comment_id": {"type": "string"},
                    "conflicts_with_id": {"type": "string"},
                    "reason": {
                        "type": "string",
                        "description": "One sentence explaining the disagreement.",
                    },
                },
                "required": ["comment_id", "conflicts_with_id", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["conflicts"],
    "additionalProperties": False,
}


def _build_user_message(comments: list[Comment]) -> str:
    payload = [
        {
            "id": c.id,
            "author": c.author,
            "reply_to_id": c.parent_id,
            "anchor_text": c.anchor_text,
            "comment_text": c.text,
        }
        for c in comments
    ]
    return (
        "Here are all the reviewer comments on one document, as JSON. Identify every "
        "pair that is in genuine conflict.\n\n" + json.dumps(payload, indent=2)
    )


class AnthropicConflictDetector(ConflictDetector):
    model_name = MODEL

    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()

    def detect_conflicts(self, comments: list[Comment]) -> list[ConflictPair]:
        if len(comments) < 2:
            return []

        known_ids = {c.id for c in comments}

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=1536,
            system=SYSTEM_PROMPT,
            output_config={"format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA}},
            messages=[{"role": "user", "content": _build_user_message(comments)}],
        )
        text = next(block.text for block in response.content if block.type == "text")
        data = json.loads(text)

        pairs: list[ConflictPair] = []
        seen_pairs: set[frozenset] = set()
        for item in data["conflicts"]:
            a, b = item["comment_id"], item["conflicts_with_id"]
            if a == b or a not in known_ids or b not in known_ids:
                continue  # ignore anything the model hallucinated
            pair_key = frozenset((a, b))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            pairs.append(ConflictPair(comment_id=a, conflicts_with_id=b, reason=item["reason"]))
        return pairs


def main() -> None:
    """Standalone demo: find conflicts among the comments in a .docx and print them."""
    import argparse

    from app.ingestion.docx_parser import extract_comments

    parser = argparse.ArgumentParser(description="Detect reviewer disagreements in a .docx file.")
    parser.add_argument("docx_path", help="Path to a .docx file")
    args = parser.parse_args()

    comments = extract_comments(args.docx_path)
    by_id = {c.id: c for c in comments}
    detector = AnthropicConflictDetector()

    pairs = detector.detect_conflicts(comments)
    if not pairs:
        print("No conflicts found.")
        return

    for pair in pairs:
        a, b = by_id[pair.comment_id], by_id[pair.conflicts_with_id]
        print(f"{a.author} vs {b.author}:")
        print(f"  [{a.id}] {a.text}")
        print(f"  [{b.id}] {b.text}")
        print(f"  -> {pair.reason}\n")


if __name__ == "__main__":
    main()
