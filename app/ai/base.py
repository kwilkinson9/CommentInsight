"""Provider-agnostic AI interfaces: classification and conflict detection.

The rest of the app calls Classifier.classify() / ConflictDetector.detect_conflicts()
without knowing which AI provider is behind them. Swapping providers later
means adding one new file here, not touching storage, the API routes, or
the dashboard.
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
    model_name: str

    @abstractmethod
    def classify(self, comment: Comment) -> Classification: ...


@dataclass
class ConflictPair:
    """A detected disagreement between two comments, identified by their
    docx-native ids (Comment.id) -- not database row ids."""
    comment_id: str
    conflicts_with_id: str
    reason: str


class ConflictDetector(ABC):
    """Unlike Classifier, this looks at every comment in a document
    together, since a conflict is a relationship between two comments, not
    a property of one."""

    model_name: str

    @abstractmethod
    def detect_conflicts(self, comments: list[Comment]) -> list[ConflictPair]: ...
