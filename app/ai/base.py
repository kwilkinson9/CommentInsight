"""Provider-agnostic classification interface.

The rest of the app calls Classifier.classify() without knowing which AI
provider is behind it. Swapping providers later means adding one new file
here, not touching storage, the API routes, or the dashboard.

Scope note: these five categories only cover judging ONE comment at a time.
"Potential duplicate" and "potential conflict" need to compare comments
against each other and are a deliberately separate, later piece of work.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.ingestion.docx_parser import Comment

CATEGORIES = [
    "Editorial",
    "Scientific/Content",
    "Clarification Needed",
    "Decision Required",
    "Other",
]


@dataclass
class Classification:
    category: str
    rationale: str


class Classifier(ABC):
    @abstractmethod
    def classify(self, comment: Comment) -> Classification: ...
