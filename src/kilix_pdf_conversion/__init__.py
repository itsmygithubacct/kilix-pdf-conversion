"""Validated multi-engine PDF conversion."""

from .models import (
    Complexity,
    ConversionRecommendation,
    DocumentAnalysis,
    DocumentKind,
    EngineName,
    Profile,
    QualityStatus,
    RecommendationConfidence,
)
from .recommendation import recommend_conversion

__all__ = [
    "Complexity",
    "ConversionRecommendation",
    "DocumentAnalysis",
    "DocumentKind",
    "EngineName",
    "Profile",
    "QualityStatus",
    "RecommendationConfidence",
    "recommend_conversion",
]

__version__ = "0.3.0"
