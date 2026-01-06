"""AI/Claude integration module."""

from .classifier import EmailClassifier, ClassificationResult
from .responder import ResponseGenerator

__all__ = ["EmailClassifier", "ClassificationResult", "ResponseGenerator"]
