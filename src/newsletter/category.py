"""Category canonicalization and inference (Goals 6.5 / 2.4).

The source registry declares a :data:`~newsletter.models.Category` per
source, but the digest sections are keyed by *canonical* categories, and a
candidate's final category may differ from its source's (a general-AI feed
can publish an engineering story).  Both mappings are v1 parity — see
PROJECT.md §3.5.
"""

from __future__ import annotations

from .models import Category, ScoreBreakdown

# --------------------------------------------------------------------------- #
# Canonical mapping
# --------------------------------------------------------------------------- #

#: Registry category → canonical category.  ``cae_ai_engineering`` is the
#: legacy v1 name for the engineering bucket; anything unlisted is general AI.
CANONICAL_CATEGORIES: dict[str, Category] = {
    "engineering_ai": "engineering_ai",
    "cae_ai_engineering": "engineering_ai",
    "research": "research",
    "startup": "startup",
    "vendor": "vendor",
    "community": "community",
}

#: Terms that mark a story as industrial/engineering (v1 parity).
INDUSTRIAL_TERMS: tuple[str, ...] = (
    "industrial ai",
    "ai for engineering",
    "engineering ai",
    "engineering simulation",
    "computer-aided engineering",
    "simulation",
    "cae",
    "cad",
    "cfd",
    "fea",
    "spdm",
    "plm",
    "digital twin",
    "manufacturing",
    "robotics",
    "surrogate model",
    "physics-informed",
    "scientific ml",
)

#: Terms that mark a story as AI-related (v1 parity).
AI_TERMS: tuple[str, ...] = (
    "ai",
    "artificial intelligence",
    "machine learning",
    "ml",
    "agent",
    "copilot",
    "generative",
    "neural",
)

#: ``engineering_relevance`` at or above this promotes a candidate to
#: engineering AI regardless of the term probes below.
ENGINEERING_PROMOTION_THRESHOLD: float = 0.5


def canonical_category(category: str) -> Category:
    """Map any registry category onto its canonical digest category.

    Unknown or legacy values collapse to ``"general_ai"``.
    """
    return CANONICAL_CATEGORIES.get(category, "general_ai")


# --------------------------------------------------------------------------- #
# Inference
# --------------------------------------------------------------------------- #


def infer_candidate_category(
    source_category: str,
    text: str,
    breakdown: ScoreBreakdown,
) -> Category:
    """Infer the section a candidate belongs to (v1 parity, PROJECT.md §3.5).

    Rules, in order:

    1. An engineering source always yields ``"engineering_ai"``.
    2. A strong engineering sub-score (≥ 0.5) promotes the candidate.
    3. An industrial term *and* an AI term in the text promote it.
    4. Otherwise the source's canonical category is kept
       (``"research"`` stays research, everything else is general AI).
    """
    category = canonical_category(source_category)
    if category == "engineering_ai":
        return "engineering_ai"

    if breakdown.engineering_relevance >= ENGINEERING_PROMOTION_THRESHOLD:
        return "engineering_ai"

    lowered = text.lower()
    if any(term in lowered for term in INDUSTRIAL_TERMS) and any(
        term in lowered for term in AI_TERMS
    ):
        return "engineering_ai"

    if category == "research":
        return "research"
    return "general_ai"
