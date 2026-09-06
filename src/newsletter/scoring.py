"""Candidate scoring (Goal 6.3).

v1 parity with ``scripts/build_digest_candidates.py`` — see PROJECT.md §3.4
for the formula and the weight table.

Composite score::

    score = 32 * source_priority
          + 22 * novelty
          + 20 * general_relevance
          + 14 * engineering_relevance
          +  8 * research_relevance
          + 10 * engineering_workflow_ai_boost   (conditional, all-or-nothing)
          + 14 * log_scale(points,   1200)
          + 10 * log_scale(comments,  800)
          + 10 * log_scale(upvotes,  5000)

Every sub-score is a 0.0–1.0 fraction except the workflow boost, which is
either 0 or 1 and contributes a flat +10 when an engineering source talks
about AI-driven simulation work.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime

from .category import canonical_category
from .models import Engagement, ScoreBreakdown, Source

# --------------------------------------------------------------------------- #
# Weights (PROJECT.md §3.4)
# --------------------------------------------------------------------------- #

WEIGHT_SOURCE_PRIORITY: float = 32.0
WEIGHT_NOVELTY: float = 22.0
WEIGHT_GENERAL_RELEVANCE: float = 20.0
WEIGHT_ENGINEERING_RELEVANCE: float = 14.0
WEIGHT_RESEARCH_RELEVANCE: float = 8.0
WEIGHT_POINTS: float = 14.0
WEIGHT_COMMENTS: float = 10.0
WEIGHT_UPVOTES: float = 10.0

#: Flat bonus (not a weight) when the engineering-workflow probe fires.
ENGINEERING_WORKFLOW_AI_BOOST: float = 10.0

# --------------------------------------------------------------------------- #
# Normalization divisors and engagement caps
# --------------------------------------------------------------------------- #

#: ``general_relevance = min(len(matches) / 6, 1.0)``
GENERAL_RELEVANCE_DIVISOR: float = 6.0

#: ``engineering_relevance = min(term_hits / 4, 1.0)`` for non-engineering sources
ENGINEERING_RELEVANCE_DIVISOR: float = 4.0

#: ``research_relevance = min(term_hits / 3, 1.0)`` for non-research sources
RESEARCH_RELEVANCE_DIVISOR: float = 3.0

POINTS_CAP: float = 1200.0
COMMENTS_CAP: float = 800.0
UPVOTES_CAP: float = 5000.0

# --------------------------------------------------------------------------- #
# Recency curve
# --------------------------------------------------------------------------- #

#: Score for an item with no published date (v1 parity).
UNKNOWN_DATE_NOVELTY: float = 0.35

#: Floor for an item inside the window (v1 parity).
MIN_NOVELTY: float = 0.15

#: Share of the score lost linearly across the window (v1 parity).
NOVELTY_DECAY: float = 0.75

# --------------------------------------------------------------------------- #
# Term probes (v1 parity)
# --------------------------------------------------------------------------- #

ENGINEERING_TERMS: tuple[str, ...] = (
    "cae",
    "computer-aided engineering",
    "engineering simulation",
    "simulation",
    "cad",
    "spdm",
    "plm",
    "digital twin",
    "physical ai",
    "scientific ml",
    "industrial ai",
    "cfd",
    "fea",
    "surrogate",
    "neural operator",
    "physics-informed",
)

RESEARCH_TERMS: tuple[str, ...] = (
    "arxiv",
    "paper",
    "research",
    "benchmark",
    "dataset",
    "model release",
    "nature",
    "science robotics",
    "papers with code",
    "hugging face papers",
)

#: AI-flavoured terms for the engineering-workflow boost.
WORKFLOW_AI_TERMS: tuple[str, ...] = (
    "agentic ai",
    "ai agent",
    "agents",
    "llm",
    "natural language",
    "post-processing",
    "result browser",
    "report template",
    "code generation",
    "sandboxed environment",
    "simulation workflow",
    "simulation automation",
    "plot agent",
    "variable metadata",
)

#: Simulation-context terms that must co-occur with a workflow AI term.
WORKFLOW_CONTEXT_TERMS: tuple[str, ...] = (
    "simulation",
    "cae",
    "simcenter",
    "amesim",
    "cfd",
    "fea",
    "digital twin",
)

#: Fallback priority weights when the config omits ``[priority_presets]``.
DEFAULT_PRIORITY_PRESETS: Mapping[str, float] = {
    "high": 1.0,
    "medium": 0.65,
    "low": 0.35,
}

#: Sub-scores are rounded to this many decimals before storage (v1 parity).
SCORE_PRECISION: int = 3


# --------------------------------------------------------------------------- #
# Sub-score helpers
# --------------------------------------------------------------------------- #


def log_scale(value: float | int | None, cap: float) -> float:
    """Logarithmically scale an engagement counter into 0.0–1.0.

    ``None``, zero and negative values score 0.0; ``cap`` and above score
    1.0.  Log scaling keeps one viral story from dominating the composite.
    """
    if not value or value <= 0:
        return 0.0
    return min(math.log1p(float(value)) / math.log1p(cap), 1.0)


def recency_boost(
    published_at: datetime | None,
    now: datetime,
    window_hours: int,
) -> float:
    """Novelty fraction for an item's age relative to the look-back window.

    * no date → :data:`UNKNOWN_DATE_NOVELTY` (0.35)
    * older than the window → 0.0
    * otherwise linear decay from 1.0 down to :data:`MIN_NOVELTY` (0.15)
    """
    if not published_at:
        return UNKNOWN_DATE_NOVELTY
    age_hours = max((now - published_at).total_seconds() / 3600, 0.0)
    if window_hours <= 0:
        return 0.0
    if age_hours > window_hours:
        return 0.0
    return max(MIN_NOVELTY, 1.0 - (age_hours / window_hours) * NOVELTY_DECAY)


def source_priority_score(
    source: Source,
    priority_presets: Mapping[str, float] | None = None,
) -> float:
    """Resolve a source's priority label into its 0.0–1.0 weight."""
    presets = DEFAULT_PRIORITY_PRESETS if priority_presets is None else priority_presets
    return float(presets.get(source.priority, 0.65))


def _count_terms(text: str, terms: tuple[str, ...]) -> int:
    return sum(1 for term in terms if term in text)


def has_engineering_workflow_ai(category: str, text: str) -> bool:
    """Whether the flat +10 engineering-workflow boost applies.

    All three conditions must hold (v1 parity):

    1. the source's canonical category is ``engineering_ai``;
    2. the text mentions an AI-workflow term;
    3. the text mentions a simulation-context term.
    """
    if canonical_category(category) != "engineering_ai":
        return False
    lowered = text.lower()
    return _count_terms(lowered, WORKFLOW_AI_TERMS) > 0 and (
        _count_terms(lowered, WORKFLOW_CONTEXT_TERMS) > 0
    )


# --------------------------------------------------------------------------- #
# Composite score
# --------------------------------------------------------------------------- #


def score_candidate(
    source: Source,
    engagement: Engagement,
    matches: list[str],
    published_at: datetime | None,
    now: datetime,
    window_hours: int,
    text: str,
    *,
    priority_presets: Mapping[str, float] | None = None,
) -> ScoreBreakdown:
    """Score one candidate and return the full breakdown.

    Parameters
    ----------
    source:
        Registry entry — supplies the priority weight and the category that
        forces engineering/research relevance to 1.0.
    engagement:
        Points, comments and upvotes (any of which may be ``None``).
    matches:
        Keyword ``include`` hits for the winning bucket; drives
        ``general_relevance``.
    published_at, now, window_hours:
        Recency inputs.  ``now`` is injected so scoring stays deterministic
        and testable.
    text:
        Lowercased-comparison haystack, conventionally ``f"{title} {text}"``.
    priority_presets:
        Config-driven priority weights, defaulting to
        :data:`DEFAULT_PRIORITY_PRESETS`.
    """
    lowered = text.lower()
    category = canonical_category(source.category)

    priority = source_priority_score(source, priority_presets)
    novelty = recency_boost(published_at, now, window_hours)
    general_relevance = min(len(matches) / GENERAL_RELEVANCE_DIVISOR, 1.0)

    if category == "engineering_ai":
        engineering_relevance = 1.0
    else:
        engineering_relevance = min(
            _count_terms(lowered, ENGINEERING_TERMS) / ENGINEERING_RELEVANCE_DIVISOR,
            1.0,
        )

    if category == "research":
        research_relevance = 1.0
    else:
        research_relevance = min(
            _count_terms(lowered, RESEARCH_TERMS) / RESEARCH_RELEVANCE_DIVISOR, 1.0
        )

    workflow_boost = (
        ENGINEERING_WORKFLOW_AI_BOOST
        if has_engineering_workflow_ai(source.category, lowered)
        else 0.0
    )

    points_score = log_scale(engagement.points, POINTS_CAP)
    comments_score = log_scale(engagement.comments, COMMENTS_CAP)
    upvotes_score = log_scale(engagement.upvotes, UPVOTES_CAP)

    score = (
        WEIGHT_SOURCE_PRIORITY * priority
        + WEIGHT_NOVELTY * novelty
        + WEIGHT_GENERAL_RELEVANCE * general_relevance
        + WEIGHT_ENGINEERING_RELEVANCE * engineering_relevance
        + WEIGHT_RESEARCH_RELEVANCE * research_relevance
        + workflow_boost
        + WEIGHT_POINTS * points_score
        + WEIGHT_COMMENTS * comments_score
        + WEIGHT_UPVOTES * upvotes_score
    )

    return ScoreBreakdown(
        score=round(score, SCORE_PRECISION),
        source_priority=round(priority, SCORE_PRECISION),
        novelty=round(novelty, SCORE_PRECISION),
        general_relevance=round(general_relevance, SCORE_PRECISION),
        engineering_relevance=round(engineering_relevance, SCORE_PRECISION),
        research_relevance=round(research_relevance, SCORE_PRECISION),
        engineering_workflow_ai_boost=workflow_boost,
        points_score=round(points_score, SCORE_PRECISION),
        comments_score=round(comments_score, SCORE_PRECISION),
        upvotes_score=round(upvotes_score, SCORE_PRECISION),
    )


# --------------------------------------------------------------------------- #
# Human-readable reasons (v1 `score_reasons`)
# --------------------------------------------------------------------------- #


def score_reasons(
    breakdown: ScoreBreakdown,
    matched_terms: list[str],
    engagement: Engagement,
) -> list[str]:
    """Render the breakdown as v1's ``score_reasons`` strings.

    Kept as a derived view rather than a model field: everything here is
    recomputable from :class:`ScoreBreakdown` plus the term hits and the
    visible engagement counters.
    """
    reasons = [
        f"source_priority={breakdown.source_priority:.2f}",
        f"novelty={breakdown.novelty:.2f}",
        f"matched_terms={len(matched_terms)}",
        f"engineering_relevance={breakdown.engineering_relevance:.2f}",
        f"research_relevance={breakdown.research_relevance:.2f}",
    ]
    if breakdown.engineering_workflow_ai_boost:
        reasons.append(
            f"engineering_workflow_ai_boost={breakdown.engineering_workflow_ai_boost:.0f}"
        )

    visible = {
        name: value
        for name, value in (
            ("points", engagement.points),
            ("comments", engagement.comments),
            ("upvotes", engagement.upvotes),
        )
        if value
    }
    reasons.append(f"visible_engagement={visible if visible else 'unavailable'}")
    return reasons
