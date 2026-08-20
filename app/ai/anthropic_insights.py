"""Finds recurring patterns across every uploaded document's comments --
themes, notable reviewer habits, and how documents compare to each other.

Unlike ConflictDetector (pairs within one document), this reasons over the
whole corpus at once and returns prose, not comment-id pairs, so there's no
known-id validation step here -- the model's output is text, not
references back into the data.
"""

from __future__ import annotations

import json

import anthropic

from app.ai.base import AnalysisInsights, InsightComment, InsightsGenerator, InsightTheme

MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = """You review reviewer comments left across one or more medical/regulatory \
documents to find patterns a medical writer would want to know about before a Comment \
Resolution Meeting (CRM).

Look for things like: recurring concerns that show up across multiple documents or \
sections, a reviewer who consistently focuses on a particular kind of issue, categories \
or resolution statuses that cluster in a way worth flagging, and how documents compare to \
each other (e.g. one document has far more unresolved Decision Required comments than \
the others).

Pay particular attention to two patterns a medical writer can fix once rather than every \
time: (1) the same wording, phrase, or word choice getting corrected by reviewers in more \
than one document -- a sign the house style guide or template language itself needs \
fixing, not just this one document; and (2) the same section or heading repeatedly \
drawing comments across different documents -- a sign that section's template \
instructions or boilerplate, not any single document's content, are the recurring \
problem. When you spot one, name the specific wording or section rather than saying \
"phrasing issues exist."

Write for someone who has already seen the raw comments and the charts -- don't restate \
individual comments verbatim or just repeat counts, explain what the pattern is and why it \
matters. If there's too little data for a real pattern (e.g. only one document, or very \
few comments), say so plainly in the overview and return an empty themes list rather than \
inventing a theme."""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {
            "type": "string",
            "description": "2-4 sentence overview of the most important cross-document pattern(s).",
        },
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short theme name, a few words."},
                    "description": {
                        "type": "string",
                        "description": "1-3 sentences explaining the pattern and why it matters.",
                    },
                },
                "required": ["title", "description"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overview", "themes"],
    "additionalProperties": False,
}


def _build_user_message(comments: list[InsightComment]) -> str:
    payload = [
        {
            "document": c.document_filename,
            "author": c.author,
            "section": c.section,
            "category": c.category,
            "resolution_status": c.resolution_status,
            "comment_text": c.text,
        }
        for c in comments
    ]
    return (
        "Here are all reviewer comments across every uploaded document, as JSON. Identify "
        "the patterns worth surfacing to a medical writer.\n\n" + json.dumps(payload, indent=2)
    )


class AnthropicInsightsGenerator(InsightsGenerator):
    model_name = MODEL

    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()

    def generate_insights(self, comments: list[InsightComment]) -> AnalysisInsights:
        if not comments:
            return AnalysisInsights(overview="No comments to analyze yet.", themes=[])

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=1536,
            system=SYSTEM_PROMPT,
            output_config={"format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA}},
            messages=[{"role": "user", "content": _build_user_message(comments)}],
        )
        text = next(block.text for block in response.content if block.type == "text")
        data = json.loads(text)

        themes = [InsightTheme(title=t["title"], description=t["description"]) for t in data["themes"]]
        return AnalysisInsights(overview=data["overview"], themes=themes)


def main() -> None:
    """Standalone demo: find cross-document patterns among one or more .docx files' comments."""
    import argparse

    from app.ingestion.docx_parser import extract_comments

    parser = argparse.ArgumentParser(description="Find cross-document reviewer patterns across .docx files.")
    parser.add_argument("docx_paths", nargs="+", help="Paths to one or more .docx files")
    args = parser.parse_args()

    comments = []
    for path in args.docx_paths:
        for c in extract_comments(path):
            comments.append(
                InsightComment(
                    document_filename=path,
                    author=c.author,
                    text=c.text,
                    category=None,
                    resolution_status=None,
                    section=c.section,
                )
            )

    generator = AnthropicInsightsGenerator()
    result = generator.generate_insights(comments)

    print(result.overview)
    print()
    for theme in result.themes:
        print(f"- {theme.title}: {theme.description}")


if __name__ == "__main__":
    main()
