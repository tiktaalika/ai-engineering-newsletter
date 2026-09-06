"""Tests for newsletter.dedup — URL normalization and event identity."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from newsletter.dedup import (
    COMMON_EVENT_WORDS,
    EVENT_RULES,
    SOURCE_SUFFIXES,
    canonical_event_key,
    dedup_key,
    event_tokens,
    event_url_key,
    is_same_event,
    norm_url,
)
from newsletter.models import Candidate

CandidateFactory = Callable[..., Candidate]


class TestNormUrl:
    def test_strips_utm_parameters(self) -> None:
        result = norm_url(
            "https://example.com/a?utm_source=feed&utm_medium=rss&utm_campaign=x"
        )
        assert result == "https://example.com/a"

    def test_strips_utm_case_insensitively(self) -> None:
        result = norm_url("https://example.com/a?UTM_SOURCE=x&ref=keep")
        assert result == "https://example.com/a?ref=keep"

    def test_keeps_non_utm_query_parameters(self) -> None:
        result = norm_url("https://example.com/a?id=42&ref=feed&utm_source=x")
        assert result == "https://example.com/a?id=42&ref=feed"

    def test_lowercases_netloc(self) -> None:
        assert norm_url("https://EXAMPLE.Com/Path") == "https://example.com/Path"

    def test_strips_trailing_path_slash(self) -> None:
        assert norm_url("https://example.com/a/") == "https://example.com/a"

    def test_drops_fragment(self) -> None:
        assert norm_url("https://example.com/a#section") == "https://example.com/a"

    def test_drops_blank_query_values(self) -> None:
        assert norm_url("https://example.com/a?foo=") == "https://example.com/a"

    def test_empty_string(self) -> None:
        assert norm_url("") == ""

    def test_idempotent(self) -> None:
        url = "https://Example.com/a/?utm_source=x&id=1#frag"
        once = norm_url(url)
        assert norm_url(once) == once


# --------------------------------------------------------------------------- #
# event_url_key
# --------------------------------------------------------------------------- #


class TestEventUrlKey:
    def test_drops_query_and_fragment(self) -> None:
        assert (
            event_url_key("https://Example.com/a/?ref=feed#top")
            == "https://example.com/a"
        )

    def test_query_variants_share_a_key(self) -> None:
        assert event_url_key("https://a.com/x?utm=1") == event_url_key(
            "https://a.com/x?fbclid=2"
        )

    def test_strips_trailing_slash(self) -> None:
        assert event_url_key("https://a.com/x/") == event_url_key("https://a.com/x")

    def test_paths_differ(self) -> None:
        assert event_url_key("https://a.com/x") != event_url_key("https://a.com/y")

    @pytest.mark.parametrize("url", ["", "   ", "example.com/x", "/relative/path"])
    def test_no_scheme_or_host_is_empty(self, url: str) -> None:
        """Link-less records carry no URL evidence."""
        assert event_url_key(url) == ""


# --------------------------------------------------------------------------- #
# dedup_key
# --------------------------------------------------------------------------- #


class TestDedupKey:
    def test_uses_normalized_url(self) -> None:
        assert (
            dedup_key("Any Title", "https://Example.com/a/?utm_source=x")
            == "https://example.com/a"
        )

    def test_falls_back_to_lowercased_title(self) -> None:
        assert dedup_key("  Breaking AI News  ", "") == "breaking ai news"

    def test_same_article_via_two_feeds(self) -> None:
        assert dedup_key("T", "https://a.com/x?utm_source=rss") == dedup_key(
            "T", "https://a.com/x"
        )


# --------------------------------------------------------------------------- #
# event_tokens
# --------------------------------------------------------------------------- #


class TestEventTokens:
    def test_basic_tokenization(self) -> None:
        assert event_tokens("Nvidia unveils a GPU") == {"nvidia", "unveils", "gpu"}

    def test_drops_short_tokens(self) -> None:
        """Two-letter tokens ('AI', 'GPT-5' → '5') carry no identity."""
        assert event_tokens("AI model GPT-5 ships") == {"model", "gpt", "ships"}

    def test_drops_common_words(self) -> None:
        assert event_tokens("the new report says AI is breaking news") == set()

    def test_drops_source_suffix_words(self) -> None:
        assert "reuters" in SOURCE_SUFFIXES
        assert event_tokens("Deal announced reuters") == {"deal", "announced"}

    def test_strips_trailing_source_suffix(self) -> None:
        assert event_tokens("Nvidia unveils a GPU - TechCrunch") == event_tokens(
            "Nvidia unveils a GPU"
        )

    def test_only_strips_suffix_without_hyphen(self) -> None:
        """v1 quirk: the regex stops at the last ' - ' segment *without* '-'."""
        assert event_tokens("Model ships - GPT-5") == {"model", "ships", "gpt"}

    def test_punctuation_splits_tokens(self) -> None:
        # "openai" is a SOURCE_SUFFIX, so it is filtered out.
        assert event_tokens("OpenAI/Anthropic: price war!") == {
            "anthropic",
            "price",
            "war",
        }

    def test_empty_title(self) -> None:
        assert event_tokens("") == set()

    def test_common_words_are_lowercase(self) -> None:
        assert all(word == word.lower() for word in COMMON_EVENT_WORDS)


# --------------------------------------------------------------------------- #
# canonical_event_key
# --------------------------------------------------------------------------- #


class TestCanonicalEventKey:
    def test_unknown_story_returns_none(self) -> None:
        assert canonical_event_key("Nvidia unveils a new GPU") is None

    def test_openai_ipo(self) -> None:
        assert canonical_event_key("OpenAI files S-1 for IPO") == "openai-ipo"
        assert canonical_event_key("OpenAI plans to go public") == "openai-ipo"

    def test_openai_ipo_requires_both_signals(self) -> None:
        assert canonical_event_key("OpenAI ships a new model") is None
        assert canonical_event_key("Stripe files for IPO") is None

    def test_price_war_requires_both_companies(self) -> None:
        assert (
            canonical_event_key("OpenAI price cuts follow Anthropic move")
            == "openai-anthropic-price-war"
        )
        assert canonical_event_key("OpenAI announces price cuts") is None

    def test_visa_openai_payments_needs_two_groups(self) -> None:
        assert (
            canonical_event_key("Visa backs ChatGPT agentic commerce")
            == "visa-openai-agent-payments"
        )
        assert canonical_event_key("Visa reports record payments volume") is None

    def test_apple_siri_needs_no_extra_term(self) -> None:
        assert canonical_event_key("Apple Siri revamp delayed") == "apple-siri-ai"

    def test_meta_reliance_needs_three_terms(self) -> None:
        assert (
            canonical_event_key("Meta and Reliance plan a data center")
            == "meta-reliance-india-data-center"
        )
        assert canonical_event_key("Meta opens a data center") is None

    def test_first_matching_rule_wins(self) -> None:
        """'government order' also contains rule 6's 'government'."""
        assert (
            canonical_event_key("Anthropic backs government order on models")
            == "anthropic-regulation-call"
        )

    def test_export_controls_rule_reachable(self) -> None:
        assert (
            canonical_event_key("Anthropic model suspended over security fears")
            == "anthropic-export-controls-model-access"
        )

    def test_case_insensitive(self) -> None:
        assert canonical_event_key("APPLE Siri Gets An Upgrade") == "apple-siri-ai"

    def test_rule_keys_are_unique(self) -> None:
        keys = [rule.key for rule in EVENT_RULES]
        assert len(keys) == len(set(keys)) == 14


# --------------------------------------------------------------------------- #
# is_same_event
# --------------------------------------------------------------------------- #


class TestIsSameEvent:
    def test_identical_urls(self, make_candidate: CandidateFactory) -> None:
        left = make_candidate(title="Alpha story", url="https://a.com/x")
        right = make_candidate(
            title="Completely different words", url="https://a.com/x"
        )
        assert is_same_event(left, right)

    def test_url_match_ignores_query(self, make_candidate: CandidateFactory) -> None:
        left = make_candidate(url="https://a.com/x?utm_source=rss")
        right = make_candidate(url="https://a.com/x?fbclid=1")
        assert is_same_event(left, right)

    def test_different_urls_different_titles(
        self, make_candidate: CandidateFactory
    ) -> None:
        left = make_candidate(title="Nvidia unveils a GPU", url="https://a.com/1")
        right = make_candidate(
            title="Anthropic hires researchers", url="https://b.com/2"
        )
        assert not is_same_event(left, right)

    def test_canonical_event_overrides_urls(
        self, make_candidate: CandidateFactory
    ) -> None:
        left = make_candidate(
            title="OpenAI files S-1 for IPO", url="https://a.com/ipo-1"
        )
        right = make_candidate(
            title="OpenAI prepares public offering", url="https://b.com/ipo-2"
        )
        assert is_same_event(left, right)

    def test_same_source_token_overlap(self, make_candidate: CandidateFactory) -> None:
        """Same outlet + 3 shared tokens covering ≥ 67% → same event."""
        left = make_candidate(
            title="Nvidia unveils new GPU for data centers",
            url="https://a.com/1",
            source_name="Same Outlet",
        )
        right = make_candidate(
            title="Nvidia unveils new GPU chip",
            url="https://a.com/2",
            source_name="Same Outlet",
        )
        assert is_same_event(left, right)

    def test_cross_source_overlap_below_strong_bar(
        self, make_candidate: CandidateFactory
    ) -> None:
        """3 shared tokens across outlets is not enough."""
        left = make_candidate(
            title="Nvidia unveils new GPU for data centers",
            url="https://a.com/1",
            source_name="Outlet A",
        )
        right = make_candidate(
            title="Nvidia unveils new GPU chip",
            url="https://b.com/2",
            source_name="Outlet B",
        )
        assert not is_same_event(left, right)

    def test_strong_overlap_across_sources(
        self, make_candidate: CandidateFactory
    ) -> None:
        """≥ 5 shared tokens covering ≥ 50% → same event, any outlets."""
        shared = "acme beta gamma delta epsilon zeta"
        left = make_candidate(
            title=f"{shared} announce partnership", url="https://a.com/1"
        )
        right = make_candidate(title=shared, url="https://b.com/2")
        assert is_same_event(left, right)

    def test_union_rule_across_sources(self, make_candidate: CandidateFactory) -> None:
        """4 shared tokens with a small union (Jaccard ≥ 0.42) → same event."""
        left = make_candidate(
            title="acme beta gamma delta epsilon", url="https://a.com/1"
        )
        right = make_candidate(
            title="acme beta gamma delta omega", url="https://b.com/2"
        )
        assert is_same_event(left, right)

    def test_union_rule_near_miss(self, make_candidate: CandidateFactory) -> None:
        """3 shared tokens never trip the union rule (needs ≥ 4)."""
        left = make_candidate(
            title="acme beta gamma delta epsilon", url="https://a.com/1"
        )
        right = make_candidate(
            title="acme beta gamma omega sigma", url="https://b.com/2"
        )
        assert not is_same_event(left, right)

    def test_stopword_only_titles_never_match(
        self, make_candidate: CandidateFactory
    ) -> None:
        """A headline made only of generic words has no token identity."""
        title = "Breaking exclusive news report says the new"
        left = make_candidate(title=title, url="https://a.com/1", source_name="A")
        right = make_candidate(title=title, url="https://b.com/2", source_name="B")
        assert event_tokens(title) == set()
        assert not is_same_event(left, right)

    def test_source_comparison_is_case_insensitive(
        self, make_candidate: CandidateFactory
    ) -> None:
        left = make_candidate(
            title="Nvidia unveils new GPU for data centers",
            url="https://a.com/1",
            source_name="Tech Outlet",
        )
        right = make_candidate(
            title="Nvidia unveils new GPU chip",
            url="https://a.com/2",
            source_name="tech outlet",
        )
        assert is_same_event(left, right)

    def test_link_less_candidates_compare_by_title(
        self, make_candidate: CandidateFactory
    ) -> None:
        left = make_candidate(
            title="acme beta gamma delta epsilon zeta", url="", source_name="A"
        )
        right = make_candidate(
            title="acme beta gamma delta epsilon zeta", url="", source_name="A"
        )
        assert is_same_event(left, right)

    def test_symmetric(self, make_candidate: CandidateFactory) -> None:
        left = make_candidate(title="Nvidia unveils new GPU", url="https://a.com/1")
        right = make_candidate(
            title="Nvidia unveils new GPU chip", url="https://a.com/2"
        )
        assert is_same_event(left, right) == is_same_event(right, left)

    def test_reflexive(self, make_candidate: CandidateFactory) -> None:
        candidate = make_candidate()
        assert is_same_event(candidate, candidate)
