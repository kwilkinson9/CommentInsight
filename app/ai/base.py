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


@dataclass
class InsightComment:
    """A comment shape for cross-document pattern analysis -- unlike
    Comment (single-document extraction), this carries which document a
    comment came from plus the classification/resolution decisions already
    made on it, since spotting a pattern often depends on knowing those."""

    document_filename: str
    author: str
    text: str
    category: str | None
    resolution_status: str | None
    section: str | None


@dataclass
class InsightTheme:
    title: str
    description: str


@dataclass
class AnalysisInsights:
    overview: str
    themes: list[InsightTheme]


class InsightsGenerator(ABC):
    """Looks across every comment on every uploaded document to find
    recurring themes, notable reviewer patterns, and how documents compare
    -- unlike ConflictDetector (pairs within one document), this reasons
    over the whole corpus at once and returns prose, not comment-id pairs."""

    model_name: str

    @abstractmethod
    def generate_insights(self, comments: list[InsightComment]) -> AnalysisInsights: ...
