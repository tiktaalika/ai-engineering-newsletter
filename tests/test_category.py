"""Tests for newsletter.category — canonicalization and inference (Goal 6.5)."""

from __future__ import annotations

import pytest

from newsletter.category import (
    AI_TERMS,
    ENGINEERING_PROMOTION_THRESHOLD,
    INDUSTRIAL_TERMS,
    canonical_category,
    infer_candidate_category,
)
from newsletter.models import ScoreBreakdown


def _breakdown(engineering_relevance: float = 0.0) -> ScoreBreakdown:
    return ScoreBreakdown(
        score=0.0, engineering_relevance=engineering_relevance, general_relevance=1.0
    )


class TestCanonicalCategory:
    @pytest.mark.parametrize(
        ("category", "expected"),
        [
            ("general_ai", "general_ai"),
            ("engineering_ai", "engineering_ai"),
            ("cae_ai_engineering", "engineering_ai"),  # legacy v1 alias
            ("research", "research"),
            ("startup", "startup"),
            ("vendor", "vendor"),
            ("community", "community"),
        ],
    )
    def test_known_categories(self, category: str, expected: str) -> None:
        assert canonical_category(category) == expected

    @pytest.mark.parametrize("category", ["", "unknown", "General_AI", "caE"])
    def test_unknown_collapses_to_general_ai(self, category: str) -> None:
        """Mapping is exact-match; anything else is general AI."""
        assert canonical_category(category) == "general_ai"

    def test_idempotent(self) -> None:
        once = canonical_category("cae_ai_engineering")
        assert canonical_category(once) == once


class TestInferCandidateCategory:
    def test_engineering_source_always_engineering(self) -> None:
        """Rule 1: the source category wins, whatever the text says."""
        assert (
            infer_candidate_category(
                "engineering_ai", "a recipe for pancakes", _breakdown()
            )
            == "engineering_ai"
        )

    def test_legacy_engineering_alias(self) -> None:
        assert (
            infer_candidate_category("cae_ai_engineering", "anything", _breakdown())
            == "engineering_ai"
        )

    def test_high_engineering_relevance_promotes(self) -> None:
        """Rule 2: a strong sub-score promotes a general-AI candidate."""
        assert (
            infer_candidate_category(
                "general_ai",
                "a story with no engineering words at all",
                _breakdown(ENGINEERING_PROMOTION_THRESHOLD),
            )
            == "engineering_ai"
        )

    def test_below_threshold_does_not_promote(self) -> None:
        assert (
            infer_candidate_category(
                "general_ai",
                "a story with no engineering words at all",
                _breakdown(ENGINEERING_PROMOTION_THRESHOLD - 0.01),
            )
            == "general_ai"
        )

    def test_industrial_plus_ai_terms_promote(self) -> None:
        """Rule 3: both term families must be present."""
        assert (
            infer_candidate_category(
                "general_ai", "Digital twin simulation for AI agents", _breakdown()
            )
            == "engineering_ai"
        )

    def test_industrial_terms_alone_do_not_promote(self) -> None:
        assert (
            infer_candidate_category(
                "general_ai", "A new simulation of ocean currents", _breakdown()
            )
            == "general_ai"
        )

    def test_ai_terms_alone_do_not_promote(self) -> None:
        assert (
            infer_candidate_category(
                "general_ai", "OpenAI ships an agent copilot", _breakdown()
            )
            == "general_ai"
        )

    def test_research_source_stays_research(self) -> None:
        assert (
            infer_candidate_category(
                "research", "A new benchmark dataset for reasoning", _breakdown()
            )
            == "research"
        )

    @pytest.mark.parametrize("category", ["startup", "vendor", "community"])
    def test_other_categories_become_general_ai(self, category: str) -> None:
        """Only research survives; startup/vendor/community collapse."""
        assert (
            infer_candidate_category(category, "A funding announcement", _breakdown())
            == "general_ai"
        )

    def test_term_matching_is_case_insensitive(self) -> None:
        assert (
            infer_candidate_category(
                "general_ai", "CFD Simulation Powered By ML", _breakdown()
            )
            == "engineering_ai"
        )

    def test_term_lists_are_lowercase(self) -> None:
        """Both probes lowercase the haystack, so terms must be lowercase."""
        assert all(term == term.lower() for term in INDUSTRIAL_TERMS)
        assert all(term == term.lower() for term in AI_TERMS)
