"""Tests for newsletter.scoring — the composite score formula (Goal 6.3).

Expected values are hand-computed from PROJECT.md §3.4 so a weight or
divisor change fails loudly.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from newsletter.models import Category, Engagement, Priority, Source
from newsletter.scoring import (
    COMMENTS_CAP,
    DEFAULT_PRIORITY_PRESETS,
    ENGINEERING_WORKFLOW_AI_BOOST,
    POINTS_CAP,
    UNKNOWN_DATE_NOVELTY,
    UPVOTES_CAP,
    has_engineering_workflow_ai,
    log_scale,
    recency_boost,
    score_candidate,
    score_reasons,
    source_priority_score,
)

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _source(
    priority: Priority = "high",
    category: Category = "general_ai",
    name: str = "Test Blog",
) -> Source:
    return Source(
        name=name,
        scrape_url="https://example.com/feed",
        priority=priority,
        category=category,
        fetch_type="rss",
    )


def _hours_ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


# --------------------------------------------------------------------------- #
# log_scale
# --------------------------------------------------------------------------- #


class TestLogScale:
    @pytest.mark.parametrize("value", [None, 0, -1, -1000])
    def test_empty_and_negative_score_zero(self, value: int | None) -> None:
        assert log_scale(value, POINTS_CAP) == 0.0

    def test_cap_scores_one(self) -> None:
        assert log_scale(POINTS_CAP, POINTS_CAP) == 1.0

    def test_above_cap_is_clamped(self) -> None:
        assert log_scale(POINTS_CAP * 100, POINTS_CAP) == 1.0

    def test_matches_log1p_formula(self) -> None:
        assert log_scale(100, 1200) == pytest.approx(math.log1p(100) / math.log1p(1200))

    def test_monotonically_increasing(self) -> None:
        values = [log_scale(v, COMMENTS_CAP) for v in (1, 10, 100, 500, 800)]
        assert values == sorted(values)
        assert len(set(values)) == len(values)

    def test_log_compression_gives_small_counts_credit(self) -> None:
        """5 upvotes out of a 5000 cap still earns ~0.21, not 0.001."""
        assert 0.2 < log_scale(5, UPVOTES_CAP) < 0.25

    def test_log_compression_tames_large_counts(self) -> None:
        """Half the cap already scores ~0.8, so huge counts saturate."""
        half = log_scale(POINTS_CAP / 2, POINTS_CAP)
        assert 0.75 < half < 1.0
        assert half > log_scale(POINTS_CAP / 10, POINTS_CAP)

    def test_accepts_floats(self) -> None:
        assert log_scale(1.5, 10.0) == pytest.approx(math.log1p(1.5) / math.log1p(10))


# --------------------------------------------------------------------------- #
# recency_boost
# --------------------------------------------------------------------------- #


class TestRecencyBoost:
    def test_missing_date_gets_fixed_fraction(self) -> None:
        assert recency_boost(None, NOW, 24) == UNKNOWN_DATE_NOVELTY == 0.35

    def test_just_published_scores_one(self) -> None:
        assert recency_boost(NOW, NOW, 24) == 1.0

    def test_future_date_clamped_to_one(self) -> None:
        assert recency_boost(NOW + timedelta(hours=5), NOW, 24) == 1.0

    def test_half_window_decays_linearly(self) -> None:
        # 1.0 - (12 / 24) * 0.75 = 0.625
        assert recency_boost(_hours_ago(12), NOW, 24) == pytest.approx(0.625)

    def test_at_window_edge(self) -> None:
        # 1.0 - 1.0 * 0.75 = 0.25
        assert recency_boost(_hours_ago(24), NOW, 24) == pytest.approx(0.25)

    def test_beyond_window_scores_zero(self) -> None:
        assert recency_boost(_hours_ago(24.5), NOW, 24) == 0.0

    def test_wide_window_keeps_old_items_alive(self) -> None:
        """Engineering sources use a 720h window (config category_window_hours)."""
        assert recency_boost(_hours_ago(700), NOW, 720) > 0.15

    def test_zero_window_does_not_divide_by_zero(self) -> None:
        assert recency_boost(NOW, NOW, 0) == 0.0

    def test_naive_and_aware_mixing_is_caller_responsibility(self) -> None:
        """Both operands must be tz-aware (fetchers normalize to UTC)."""
        with pytest.raises(TypeError):
            recency_boost(datetime(2026, 9, 1, 12, 0), NOW, 24)


# --------------------------------------------------------------------------- #
# source_priority_score
# --------------------------------------------------------------------------- #


class TestSourcePriorityScore:
    @pytest.mark.parametrize(
        ("priority", "expected"), [("high", 1.0), ("medium", 0.65), ("low", 0.35)]
    )
    def test_default_presets(self, priority: Priority, expected: float) -> None:
        assert source_priority_score(_source(priority=priority)) == expected

    def test_config_presets_override_defaults(self) -> None:
        presets = {"high": 0.9, "medium": 0.5, "low": 0.1}
        assert source_priority_score(_source("medium"), presets) == 0.5

    def test_missing_preset_falls_back_to_medium(self) -> None:
        assert source_priority_score(_source("low"), {"high": 1.0}) == 0.65

    def test_defaults_match_v1(self) -> None:
        assert dict(DEFAULT_PRIORITY_PRESETS) == {
            "high": 1.0,
            "medium": 0.65,
            "low": 0.35,
        }


# --------------------------------------------------------------------------- #
# Engineering workflow AI boost
# --------------------------------------------------------------------------- #


class TestEngineeringWorkflowBoost:
    def test_requires_engineering_category(self) -> None:
        assert not has_engineering_workflow_ai(
            "general_ai", "an AI agent running a simulation"
        )

    def test_legacy_engineering_alias_qualifies(self) -> None:
        assert has_engineering_workflow_ai(
            "cae_ai_engineering", "an AI agent running a simulation"
        )

    def test_both_term_families_required(self) -> None:
        assert has_engineering_workflow_ai(
            "engineering_ai", "an AI agent automates the simulation workflow"
        )

    def test_ai_terms_alone_do_not_fire(self) -> None:
        assert not has_engineering_workflow_ai(
            "engineering_ai", "an LLM writes code generation prompts"
        )

    def test_context_terms_alone_do_not_fire(self) -> None:
        assert not has_engineering_workflow_ai(
            "engineering_ai", "a CFD and FEA meshing update"
        )

    def test_case_insensitive(self) -> None:
        assert has_engineering_workflow_ai(
            "engineering_ai", "SimCenter AI Agent for CFD"
        )

    def test_boost_is_ten_points(self) -> None:
        assert ENGINEERING_WORKFLOW_AI_BOOST == 10.0


# --------------------------------------------------------------------------- #
# score_candidate
# --------------------------------------------------------------------------- #


class TestScoreCandidate:
    def test_hand_computed_composite(self) -> None:
        """32*1 + 22*1 + 20*1 + 14 + 10 + 10 engagement = 108.0."""
        breakdown = score_candidate(
            _source(priority="high", category="general_ai"),
            Engagement(points=1200, comments=800, upvotes=5000),
            ["ai", "llm", "openai", "agent", "rag", "gpu"],
            NOW,
            NOW,
            24,
            "",  # no engineering / research terms
        )
        assert breakdown.score == 108.0
        assert breakdown.source_priority == 1.0
        assert breakdown.novelty == 1.0
        assert breakdown.general_relevance == 1.0
        assert breakdown.engineering_relevance == 0.0
        assert breakdown.research_relevance == 0.0
        assert breakdown.engineering_workflow_ai_boost == 0.0
        assert breakdown.points_score == 1.0
        assert breakdown.comments_score == 1.0
        assert breakdown.upvotes_score == 1.0

    def test_theoretical_maximum_with_boost(self) -> None:
        """Engineering source, all sub-scores maxed, boost fired: 140.0."""
        breakdown = score_candidate(
            _source(priority="high", category="engineering_ai"),
            Engagement(points=5000, comments=5000, upvotes=50000),
            ["cae"] * 6,
            NOW,
            NOW,
            720,
            "arxiv paper benchmark dataset: an AI agent runs the simulation",
        )
        assert breakdown.engineering_relevance == 1.0
        assert breakdown.research_relevance == 1.0
        assert breakdown.engineering_workflow_ai_boost == ENGINEERING_WORKFLOW_AI_BOOST
        # 32 + 22 + 20 + 14 + 8 + 10 + 14 + 10 + 10
        assert breakdown.score == 140.0

    def test_engineering_source_forces_relevance(self) -> None:
        breakdown = score_candidate(
            _source(category="engineering_ai"),
            Engagement(),
            [],
            NOW,
            NOW,
            24,
            "nothing technical at all",
        )
        assert breakdown.engineering_relevance == 1.0

    def test_research_source_forces_research_relevance(self) -> None:
        breakdown = score_candidate(
            _source(category="research"),
            Engagement(),
            [],
            NOW,
            NOW,
            168,
            "nothing technical at all",
        )
        assert breakdown.research_relevance == 1.0
        assert breakdown.engineering_relevance == 0.0

    def test_general_source_counts_engineering_terms(self) -> None:
        """min(term_hits / 4, 1.0) — three hits → 0.75."""
        breakdown = score_candidate(
            _source(category="general_ai"),
            Engagement(),
            [],
            NOW,
            NOW,
            24,
            "a digital twin driven by cfd simulation",
        )
        # "digital twin", "cfd", "simulation" → 3 hits → 0.75
        assert breakdown.engineering_relevance == 0.75

    def test_general_source_counts_research_terms(self) -> None:
        """min(term_hits / 3, 1.0) — two hits → 0.667."""
        breakdown = score_candidate(
            _source(category="general_ai"),
            Engagement(),
            [],
            NOW,
            NOW,
            24,
            "an arxiv paper about reasoning",
        )
        assert breakdown.research_relevance == pytest.approx(0.667, abs=1e-3)

    def test_relevance_fractions_are_capped(self) -> None:
        breakdown = score_candidate(
            _source(category="general_ai"),
            Engagement(),
            ["a"] * 50,
            NOW,
            NOW,
            24,
            "cae cad cfd fea spdm plm simulation surrogate arxiv paper research benchmark",
        )
        assert breakdown.general_relevance == 1.0
        assert breakdown.engineering_relevance == 1.0
        assert breakdown.research_relevance == 1.0

    def test_matched_term_count_drives_general_relevance(self) -> None:
        breakdown = score_candidate(
            _source(), Engagement(), ["ai", "llm", "rag"], NOW, NOW, 24, ""
        )
        assert breakdown.general_relevance == 0.5

    def test_null_engagement_scores_zero(self) -> None:
        breakdown = score_candidate(_source(), Engagement(), [], NOW, NOW, 24, "")
        assert breakdown.points_score == 0.0
        assert breakdown.comments_score == 0.0
        assert breakdown.upvotes_score == 0.0

    def test_partial_engagement(self) -> None:
        breakdown = score_candidate(
            _source(),
            Engagement(points=1200),
            [],
            NOW,
            NOW,
            24,
            "",
        )
        assert breakdown.points_score == 1.0
        assert breakdown.comments_score == 0.0
        assert breakdown.upvotes_score == 0.0

    def test_missing_date_costs_novelty(self) -> None:
        with_date = score_candidate(_source(), Engagement(), [], NOW, NOW, 24, "")
        without_date = score_candidate(_source(), Engagement(), [], None, NOW, 24, "")
        assert without_date.novelty == UNKNOWN_DATE_NOVELTY
        assert without_date.score < with_date.score

    def test_stale_item_scores_zero_novelty(self) -> None:
        breakdown = score_candidate(
            _source(), Engagement(), [], _hours_ago(48), NOW, 24, ""
        )
        assert breakdown.novelty == 0.0

    def test_priority_ordering(self) -> None:
        scores = [
            score_candidate(
                _source(priority=priority), Engagement(), ["ai"], NOW, NOW, 24, ""
            ).score
            for priority in ("low", "medium", "high")
        ]
        assert scores == sorted(scores)

    def test_custom_priority_presets_are_honoured(self) -> None:
        breakdown = score_candidate(
            _source(priority="high"),
            Engagement(),
            [],
            NOW,
            NOW,
            24,
            "",
            priority_presets={"high": 0.5, "medium": 0.4, "low": 0.1},
        )
        assert breakdown.source_priority == 0.5

    def test_scores_rounded_to_three_decimals(self) -> None:
        breakdown = score_candidate(
            _source(priority="medium"),
            Engagement(points=37, comments=11),
            ["ai", "llm"],
            _hours_ago(7),
            NOW,
            24,
            "an arxiv benchmark",
        )
        for value in (
            breakdown.score,
            breakdown.novelty,
            breakdown.general_relevance,
            breakdown.engineering_relevance,
            breakdown.research_relevance,
            breakdown.points_score,
            breakdown.comments_score,
            breakdown.upvotes_score,
        ):
            assert round(value, 3) == value

    def test_deterministic(self) -> None:
        args = (_source(), Engagement(points=10), ["ai"], _hours_ago(3), NOW, 24, "x")
        assert score_candidate(*args) == score_candidate(*args)

    def test_breakdown_is_immutable(self) -> None:
        breakdown = score_candidate(_source(), Engagement(), [], NOW, NOW, 24, "")
        with pytest.raises(AttributeError):
            breakdown.score = 1.0  # ty: ignore[invalid-assignment]


# --------------------------------------------------------------------------- #
# score_reasons
# --------------------------------------------------------------------------- #


class TestScoreReasons:
    def test_base_reasons_in_order(self) -> None:
        breakdown = score_candidate(
            _source(priority="high"), Engagement(), ["ai", "llm"], NOW, NOW, 24, ""
        )
        reasons = score_reasons(breakdown, ["ai", "llm"], Engagement())
        assert reasons[:5] == [
            "source_priority=1.00",
            "novelty=1.00",
            "matched_terms=2",
            "engineering_relevance=0.00",
            "research_relevance=0.00",
        ]

    def test_boost_reason_only_when_applied(self) -> None:
        boosted = score_candidate(
            _source(category="engineering_ai"),
            Engagement(),
            [],
            NOW,
            NOW,
            720,
            "an AI agent automates the simulation",
        )
        assert any(
            reason.startswith("engineering_workflow_ai_boost=")
            for reason in score_reasons(boosted, [], Engagement())
        )

        plain = score_candidate(_source(), Engagement(), [], NOW, NOW, 24, "")
        assert not any(
            reason.startswith("engineering_workflow_ai_boost=")
            for reason in score_reasons(plain, [], Engagement())
        )

    def test_visible_engagement_rendered(self) -> None:
        engagement = Engagement(points=100, comments=25)
        breakdown = score_candidate(_source(), engagement, [], NOW, NOW, 24, "")
        reasons = score_reasons(breakdown, [], engagement)
        assert reasons[-1] == "visible_engagement={'points': 100, 'comments': 25}"

    def test_missing_engagement_reported_unavailable(self) -> None:
        breakdown = score_candidate(_source(), Engagement(), [], NOW, NOW, 24, "")
        assert score_reasons(breakdown, [], Engagement())[-1] == (
            "visible_engagement=unavailable"
        )
