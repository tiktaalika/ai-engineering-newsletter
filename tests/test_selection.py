"""Tests for newsletter.selection — topics, predicates, multi-pass selection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from newsletter.models import Candidate
from newsletter.selection import (
    ENGINEERING_AI_LIMIT,
    FALLBACK_TOPIC,
    GENERAL_AI_LIMIT,
    MAX_PER_TOPIC,
    MEDICAL_BIO_AI_LIMIT,
    RESEARCH_RADAR_LIMIT,
    is_broad_google_discovery,
    is_excluded_from_engineering,
    is_guo_yichen_reference,
    is_historical_repeat,
    is_medical_bio_ai,
    is_trusted_or_curated,
    select_medical_bio_ai,
    select_unique_events,
    selection_category_matches,
    source_kind,
    topic_key,
)

CandidateFactory = Callable[..., Candidate]

# Headlines that hit no topic rule, so topic-cap tests stay unambiguous.
NEUTRAL_TITLES = (
    "Zebra quarantine update",
    "Quartz kiosk lantern report",
    "Meadow picnic walnut notes",
    "Gizmo banjo tulip details",
    "Copper fountain basket story",
)

# Distinct trailing words so same-topic candidates are not the same *event*.
TOPIC_VARIANTS = ("shortage", "pricing", "supply", "rollout")


def _neutral(index: int, **kwargs: Any) -> dict[str, Any]:
    """Keyword arguments for a topic-neutral candidate from its own outlet."""
    return {
        "title": NEUTRAL_TITLES[index % len(NEUTRAL_TITLES)],
        "url": f"https://example{index}.com/story-{index}",
        "source_name": f"Outlet {index}",
        **kwargs,
    }


def _infrastructure(index: int, **kwargs: Any) -> dict[str, Any]:
    """Keyword arguments for a candidate in the infrastructure_compute topic."""
    return {
        "title": f"Nvidia GPU {TOPIC_VARIANTS[index % len(TOPIC_VARIANTS)]}",
        "url": f"https://topic{index}.com/story-{index}",
        "source_name": f"Topic Outlet {index}",
        **kwargs,
    }


def _medical(index: int, **kwargs: Any) -> dict[str, Any]:
    """Keyword arguments for a biomedical candidate (topic ``health_bio``)."""
    return _neutral(
        index,
        title=f"{NEUTRAL_TITLES[index % len(NEUTRAL_TITLES)]} clinical trial",
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# topic_key
# --------------------------------------------------------------------------- #


class TestTopicKey:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("A stablecoin wallet for checkout", "payments_agent_commerce"),
            ("New AI regulation from the Senate", "policy_safety_governance"),
            ("Nvidia opens a data center", "infrastructure_compute"),
            ("A coding assistant for developers", "software_development"),
            ("Zebra quarantine update", FALLBACK_TOPIC),
            ("Robotics firm ships a drone", "robotics_autonomy"),
            ("Anthropic releases a new LLM", "frontier_models"),
        ],
    )
    def test_rule_matching(
        self, make_candidate: CandidateFactory, text: str, expected: str
    ) -> None:
        assert topic_key(make_candidate(title=text)) == expected

    def test_health_terms_map_to_health_bio(
        self, make_candidate: CandidateFactory
    ) -> None:
        """health_bio outranks frontier_models for a clinical model story."""
        assert topic_key(make_candidate(title="A clinical model deployment")) == (
            "health_bio"
        )

    def test_first_rule_wins(self, make_candidate: CandidateFactory) -> None:
        """Payments outranks frontier models for a ChatGPT payments story."""
        candidate = make_candidate(title="ChatGPT adds payments and a wallet")
        assert topic_key(candidate) == "payments_agent_commerce"

    def test_body_text_counts(self, make_candidate: CandidateFactory) -> None:
        candidate = make_candidate(title="Zebra quarantine update", text="gpu pricing")
        assert topic_key(candidate) == "infrastructure_compute"

    def test_cae_topic_requires_engineering_category(
        self, make_candidate: CandidateFactory
    ) -> None:
        text = "A CFD simulation with a digital twin"
        general = make_candidate(title=text, category="general_ai")
        engineering = make_candidate(title=text, category="engineering_ai")
        assert topic_key(engineering) == "cae_simulation"
        assert topic_key(general) != "cae_simulation"

    def test_case_insensitive(self, make_candidate: CandidateFactory) -> None:
        assert topic_key(make_candidate(title="NVIDIA GPU Shortage")) == (
            "infrastructure_compute"
        )

    def test_section_limits_match_v1(self) -> None:
        assert (GENERAL_AI_LIMIT, ENGINEERING_AI_LIMIT) == (10, 5)
        assert (MEDICAL_BIO_AI_LIMIT, RESEARCH_RADAR_LIMIT) == (5, 5)
        assert MAX_PER_TOPIC == 2


# --------------------------------------------------------------------------- #
# Biomedical detection
# --------------------------------------------------------------------------- #


class TestIsMedicalBioAi:
    @pytest.mark.parametrize(
        "title",
        [
            "A healthcare platform raises funds",
            "Clinical trial results published",
            "CRISPR gene editing advance",
            "Genomics startup benchmarks a model",
            "Drug discovery with a neural net",
        ],
    )
    def test_matches(self, make_candidate: CandidateFactory, title: str) -> None:
        assert is_medical_bio_ai(make_candidate(title=title))

    def test_no_match(self, make_candidate: CandidateFactory) -> None:
        assert not is_medical_bio_ai(make_candidate(title="Nvidia opens a data center"))

    def test_word_boundaries_enforced(self, make_candidate: CandidateFactory) -> None:
        """'genomic' must not match inside a longer token."""
        assert not is_medical_bio_ai(make_candidate(title="genomicsoftware ships v2"))

    def test_body_text_counts(self, make_candidate: CandidateFactory) -> None:
        candidate = make_candidate(
            title="Zebra quarantine update", text="a hospital deployment"
        )
        assert is_medical_bio_ai(candidate)

    def test_source_tags_count(self, make_candidate: CandidateFactory) -> None:
        candidate = make_candidate(
            title="Zebra quarantine update", tags=["medical", "research"]
        )
        assert is_medical_bio_ai(candidate)


# --------------------------------------------------------------------------- #
# Engineering exclusion list
# --------------------------------------------------------------------------- #


class TestEngineeringExclusion:
    @pytest.mark.parametrize(
        "title",
        ["CFD trading signals", "TSX:CAE moves", "Analysts Offer Insights on CAE"],
    )
    def test_excluded(self, make_candidate: CandidateFactory, title: str) -> None:
        assert is_excluded_from_engineering(make_candidate(title=title))

    def test_clean_item_not_excluded(self, make_candidate: CandidateFactory) -> None:
        assert not is_excluded_from_engineering(
            make_candidate(title="A surrogate model for CFD simulation")
        )


# --------------------------------------------------------------------------- #
# Trust / preference predicates
# --------------------------------------------------------------------------- #


class TestSourcePredicates:
    def test_rss_source_is_trusted(self, make_candidate: CandidateFactory) -> None:
        candidate = make_candidate(fetch_type="rss")
        assert source_kind(candidate) == "rss"
        assert is_trusted_or_curated(candidate)
        assert not is_broad_google_discovery(candidate)

    def test_untagged_google_news_is_broad_discovery(
        self, make_candidate: CandidateFactory
    ) -> None:
        candidate = make_candidate(
            source_name="Google News AI", fetch_type="google_news_rss", tags=[]
        )
        assert source_kind(candidate) == "google_news_rss"
        assert is_broad_google_discovery(candidate)
        assert not is_trusted_or_curated(candidate)

    def test_trusted_discovery_tag_promotes_google_news(
        self, make_candidate: CandidateFactory
    ) -> None:
        candidate = make_candidate(
            source_name="Google News AI",
            fetch_type="google_news_rss",
            tags=["trusted_discovery"],
        )
        assert is_trusted_or_curated(candidate)
        assert not is_broad_google_discovery(candidate)

    def test_google_news_kind_without_the_name_prefix(
        self, make_candidate: CandidateFactory
    ) -> None:
        """Both the kind and the name prefix are required."""
        candidate = make_candidate(
            source_name="Bing News AI", fetch_type="google_news_rss"
        )
        assert not is_broad_google_discovery(candidate)
        assert not is_trusted_or_curated(candidate)

    def test_guo_reference_tag(self, make_candidate: CandidateFactory) -> None:
        assert is_guo_yichen_reference(
            make_candidate(tags=["curated_rss", "guo_yichen_reference"])
        )
        assert not is_guo_yichen_reference(make_candidate(tags=["curated_rss"]))


# --------------------------------------------------------------------------- #
# Section eligibility
# --------------------------------------------------------------------------- #


class TestSelectionCategoryMatches:
    def test_general_section_takes_general_items(
        self, make_candidate: CandidateFactory
    ) -> None:
        assert selection_category_matches(
            make_candidate(category="general_ai"), "general_ai"
        )

    def test_research_items_need_guo_tag_for_general(
        self, make_candidate: CandidateFactory
    ) -> None:
        plain = make_candidate(category="research")
        referenced = make_candidate(category="research", tags=["guo_yichen_reference"])
        assert not selection_category_matches(plain, "general_ai")
        assert selection_category_matches(referenced, "general_ai")

    def test_engineering_section_is_exclusive(
        self, make_candidate: CandidateFactory
    ) -> None:
        assert selection_category_matches(
            make_candidate(category="engineering_ai"), "engineering_ai"
        )
        assert not selection_category_matches(
            make_candidate(category="general_ai"), "engineering_ai"
        )

    def test_legacy_alias_matches_engineering(
        self, make_candidate: CandidateFactory
    ) -> None:
        assert selection_category_matches(
            make_candidate(category="engineering_ai"), "cae_ai_engineering"
        )


class TestIsHistoricalRepeat:
    def test_repeat_detected(self, make_candidate: CandidateFactory) -> None:
        published = make_candidate(title="Nvidia unveils a GPU", url="https://a.com/1")
        fresh = make_candidate(title="Nvidia unveils a GPU", url="https://b.com/2")
        assert is_historical_repeat(fresh, [published])

    def test_unrelated_item_passes(self, make_candidate: CandidateFactory) -> None:
        published = make_candidate(title="Nvidia unveils a GPU", url="https://a.com/1")
        fresh = make_candidate(title="Zebra quarantine update", url="https://b.com/2")
        assert not is_historical_repeat(fresh, [published])

    def test_empty_history(self, make_candidate: CandidateFactory) -> None:
        assert not is_historical_repeat(make_candidate(), [])


# --------------------------------------------------------------------------- #
# select_unique_events
# --------------------------------------------------------------------------- #


class TestSelectUniqueEvents:
    def test_empty_input(self) -> None:
        assert select_unique_events([], "general_ai", GENERAL_AI_LIMIT) == []

    def test_zero_limit(self, make_candidate: CandidateFactory) -> None:
        candidates = [make_candidate(**_neutral(i)) for i in range(3)]
        assert select_unique_events(candidates, "general_ai", 0) == []

    def test_respects_limit(self, make_candidate: CandidateFactory) -> None:
        candidates = [make_candidate(**_neutral(i)) for i in range(5)]
        assert len(select_unique_events(candidates, "general_ai", 3)) == 3

    def test_preserves_score_order(self, make_candidate: CandidateFactory) -> None:
        candidates = [make_candidate(**_neutral(i)) for i in range(3)]
        assert select_unique_events(candidates, "general_ai", 3) == candidates

    def test_duplicate_urls_collapse(self, make_candidate: CandidateFactory) -> None:
        candidates = [
            make_candidate(title="Zebra quarantine update", url="https://a.com/x"),
            make_candidate(title="Quartz kiosk lantern", url="https://a.com/x"),
        ]
        assert len(select_unique_events(candidates, "general_ai", 2)) == 1

    def test_same_event_across_outlets_collapses(
        self, make_candidate: CandidateFactory
    ) -> None:
        candidates = [
            make_candidate(title="OpenAI files S-1 for IPO", url="https://a.com/1"),
            make_candidate(
                title="OpenAI prepares a public offering", url="https://b.com/2"
            ),
        ]
        assert len(select_unique_events(candidates, "general_ai", 2)) == 1

    def test_topic_cap_limits_early_passes(
        self, make_candidate: CandidateFactory
    ) -> None:
        """Three items in one topic still fit a limit of two."""
        candidates = [make_candidate(**_infrastructure(i)) for i in range(3)]
        assert len(select_unique_events(candidates, "general_ai", 2)) == 2

    def test_topic_cap_relaxes_when_slots_remain(
        self, make_candidate: CandidateFactory
    ) -> None:
        """Pass 3 drops the topic cap rather than leave the section short."""
        candidates = [make_candidate(**_infrastructure(i)) for i in range(3)]
        assert len(select_unique_events(candidates, "general_ai", 3)) == 3

    def test_diverse_topics_fill_the_section(
        self, make_candidate: CandidateFactory
    ) -> None:
        candidates = [
            make_candidate(
                title="Nvidia opens a data center",
                url="https://a.com/1",
                source_name="Outlet A",
            ),
            make_candidate(
                title="New AI regulation debated",
                url="https://b.com/2",
                source_name="Outlet B",
            ),
            make_candidate(
                title="A coding assistant ships",
                url="https://c.com/3",
                source_name="Outlet C",
            ),
        ]
        assert len(select_unique_events(candidates, "general_ai", 3)) == 3

    def test_per_source_cap_for_general_ai(
        self, make_candidate: CandidateFactory
    ) -> None:
        """General AI takes at most 2 items per outlet, in every pass."""
        candidates = [
            make_candidate(**_neutral(i, source_name="Same Outlet")) for i in range(3)
        ]
        assert len(select_unique_events(candidates, "general_ai", 3)) == 2

    def test_per_source_cap_for_engineering_ai(
        self, make_candidate: CandidateFactory
    ) -> None:
        """Engineering AI is stricter: one item per outlet."""
        candidates = [
            make_candidate(
                **_neutral(i, source_name="Same Outlet", category="engineering_ai")
            )
            for i in range(3)
        ]
        assert len(select_unique_events(candidates, "engineering_ai", 3)) == 1

    def test_research_section_has_no_source_cap(
        self, make_candidate: CandidateFactory
    ) -> None:
        candidates = [
            make_candidate(**_neutral(i, source_name="arXiv", category="research"))
            for i in range(3)
        ]
        assert len(select_unique_events(candidates, "research", 3)) == 3

    def test_section_only_takes_its_own_category(
        self, make_candidate: CandidateFactory
    ) -> None:
        candidates = [
            make_candidate(**_neutral(0, category="general_ai")),
            make_candidate(**_neutral(1, category="engineering_ai")),
        ]
        selected = select_unique_events(candidates, "engineering_ai", 5)
        assert [candidate.category for candidate in selected] == ["engineering_ai"]

    def test_history_repeats_are_skipped(
        self, make_candidate: CandidateFactory
    ) -> None:
        published = make_candidate(
            title="Nvidia unveils a GPU chip",
            url="https://a.com/1",
            source_name="Outlet B",
        )
        candidates = [
            make_candidate(
                title="Nvidia unveils a GPU chip",
                url="https://b.com/2",
                source_name="Outlet B",
            ),
            make_candidate(**_neutral(1)),
        ]
        selected = select_unique_events(candidates, "general_ai", 2, [published])
        assert selected == [candidates[1]]

    def test_guo_reference_sources_are_preferred(
        self, make_candidate: CandidateFactory
    ) -> None:
        """A lower-scored preferred source outranks higher-scored others."""
        untagged = make_candidate(**_neutral(0, tags=[]))
        preferred = make_candidate(**_neutral(1, tags=["guo_yichen_reference"]))
        selected = select_unique_events([untagged, preferred], "general_ai", 2)
        assert selected == [preferred, untagged]

    def test_guo_preference_can_be_disabled(
        self, make_candidate: CandidateFactory
    ) -> None:
        untagged = make_candidate(**_neutral(0))
        preferred = make_candidate(**_neutral(1, tags=["guo_yichen_reference"]))
        selected = select_unique_events(
            [untagged, preferred], "general_ai", 2, require_guo_general=False
        )
        assert selected == [untagged, preferred]

    def test_broad_google_news_capped_at_two_for_general(
        self, make_candidate: CandidateFactory
    ) -> None:
        trusted = make_candidate(**_neutral(0))
        broad = [
            make_candidate(
                **_neutral(
                    i, source_name=f"Google News {i}", fetch_type="google_news_rss"
                )
            )
            for i in (1, 2, 3)
        ]
        selected = select_unique_events([trusted, *broad], "general_ai", 4)
        assert trusted in selected
        assert len(selected) == 3
        assert broad[2] not in selected

    def test_broad_google_news_excluded_from_first_pass(
        self, make_candidate: CandidateFactory
    ) -> None:
        """Pass 1 is trusted-only, so a curated source wins the first slot."""
        broad = make_candidate(
            **_neutral(0, source_name="Google News AI", fetch_type="google_news_rss")
        )
        curated = make_candidate(**_neutral(1))
        assert select_unique_events([broad, curated], "general_ai", 1) == [curated]

    def test_trusted_discovery_google_news_is_first_pass_eligible(
        self, make_candidate: CandidateFactory
    ) -> None:
        candidate = make_candidate(
            **_neutral(
                0,
                source_name="Google News AI",
                fetch_type="google_news_rss",
                tags=["trusted_discovery"],
            )
        )
        assert select_unique_events([candidate], "general_ai", 1) == [candidate]

    def test_result_never_exceeds_available_candidates(
        self, make_candidate: CandidateFactory
    ) -> None:
        candidates = [make_candidate(**_neutral(0))]
        assert len(select_unique_events(candidates, "general_ai", 10)) == 1

    def test_fallback_skips_already_selected_items(
        self, make_candidate: CandidateFactory
    ) -> None:
        """The no-preference rerun must not re-add what passes 1–4 picked."""
        preferred = make_candidate(**_neutral(0, tags=["guo_yichen_reference"]))
        untagged = make_candidate(**_neutral(1))
        selected = select_unique_events([preferred, untagged], "general_ai", 3)
        assert selected == [preferred, untagged]

    def test_idempotent_for_same_input(self, make_candidate: CandidateFactory) -> None:
        candidates = [make_candidate(**_neutral(i)) for i in range(4)]
        assert select_unique_events(candidates, "general_ai", 3) == (
            select_unique_events(candidates, "general_ai", 3)
        )


# --------------------------------------------------------------------------- #
# select_medical_bio_ai
# --------------------------------------------------------------------------- #


class TestSelectMedicalBioAi:
    def test_selects_medical_items(self, make_candidate: CandidateFactory) -> None:
        candidates = [make_candidate(**_medical(i)) for i in range(3)]
        assert len(select_medical_bio_ai(candidates)) == 3

    def test_ignores_non_medical(self, make_candidate: CandidateFactory) -> None:
        candidates = [make_candidate(**_neutral(i)) for i in range(3)]
        assert select_medical_bio_ai(candidates) == []

    def test_respects_limit(self, make_candidate: CandidateFactory) -> None:
        candidates = [make_candidate(**_medical(i)) for i in range(4)]
        assert len(select_medical_bio_ai(candidates, limit=2)) == 2

    def test_engineering_candidates_are_ineligible(
        self, make_candidate: CandidateFactory
    ) -> None:
        candidates = [
            make_candidate(**_medical(0, category="engineering_ai")),
            make_candidate(**_medical(1, category="research")),
        ]
        selected = select_medical_bio_ai(candidates)
        assert [candidate.category for candidate in selected] == ["research"]

    def test_same_event_collapses(self, make_candidate: CandidateFactory) -> None:
        candidates = [
            make_candidate(**_medical(0, url="https://a.com/x")),
            make_candidate(**_medical(1, url="https://a.com/x")),
        ]
        assert len(select_medical_bio_ai(candidates)) == 1

    def test_topic_cap_relaxes_in_second_pass(
        self, make_candidate: CandidateFactory
    ) -> None:
        """All medical items share the health_bio topic; pass 2 relaxes it."""
        candidates = [make_candidate(**_medical(i)) for i in range(3)]
        assert len(select_medical_bio_ai(candidates, limit=3)) == 3
        assert len(select_medical_bio_ai(candidates, limit=2)) == 2

    def test_history_repeats_skipped(self, make_candidate: CandidateFactory) -> None:
        published = make_candidate(**_medical(0))
        candidates = [
            make_candidate(**_medical(0, url="https://other.com/repeat")),
            make_candidate(**_medical(1)),
        ]
        selected = select_medical_bio_ai(candidates, historical_items=[published])
        assert selected == [candidates[1]]

    def test_broad_google_news_capped_at_one(
        self, make_candidate: CandidateFactory
    ) -> None:
        curated = make_candidate(**_medical(0))
        broad = [
            make_candidate(
                **_medical(
                    i, source_name=f"Google News {i}", fetch_type="google_news_rss"
                )
            )
            for i in (1, 2)
        ]
        selected = select_medical_bio_ai([curated, *broad], limit=3)
        assert curated in selected
        assert len(selected) == 2

    def test_preserves_input_order(self, make_candidate: CandidateFactory) -> None:
        candidates = [make_candidate(**_medical(i)) for i in range(3)]
        assert select_medical_bio_ai(candidates) == candidates
