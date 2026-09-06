"""Tests for newsletter.text — cleaning, language detection, IDs, summaries."""

from __future__ import annotations

from newsletter.dedup import norm_url
from newsletter.models import Candidate, Source
from newsletter.text import (
    FALLBACK_SUMMARY,
    SUMMARY_MAX_CHARS,
    clean_text,
    effective_source,
    english_summary,
    entry_id,
    language_looks_english,
)


def _candidate(
    title: str = "Some Title",
    text: str = "",
    source_name: str = "Test Blog",
) -> Candidate:
    """Minimal candidate for the presentation-helper tests."""
    return Candidate(
        id=entry_id("https://example.com/a", title),
        title=title,
        url="https://example.com/a",
        source=Source(
            name=source_name,
            scrape_url="https://example.com/feed",
            priority="high",
            category="general_ai",
        ),
        category="general_ai",
        text=text,
    )


class TestEntryId:
    def test_returns_16_hex_chars(self) -> None:
        result = entry_id("https://example.com/article", "Some Title")
        assert len(result) == 16
        int(result, 16)  # must be valid hex

    def test_deterministic(self) -> None:
        a = entry_id("https://example.com/article", "Title")
        b = entry_id("https://example.com/article", "Title")
        assert a == b

    def test_case_insensitive(self) -> None:
        a = entry_id("https://example.com/Article", "Title")
        b = entry_id("https://example.com/article", "Title")
        assert a == b

    def test_falls_back_to_title_when_url_empty(self) -> None:
        result = entry_id("", "Breaking AI News")
        assert len(result) == 16
        # Derived from the title, not the empty URL.
        assert result == entry_id("", "Breaking AI News")
        assert result != entry_id("", "Different Title")

    def test_url_wins_over_title(self) -> None:
        a = entry_id("https://example.com/a", "Title One")
        b = entry_id("https://example.com/a", "Title Two")
        assert a == b  # same URL → same ID regardless of title

    def test_different_urls_get_different_ids(self) -> None:
        a = entry_id("https://example.com/a", "Title")
        b = entry_id("https://example.com/b", "Title")
        assert a != b

    def test_normalized_equivalent_urls_share_id(self) -> None:
        """UTM variants and host case must collapse to one ID."""
        a = entry_id(norm_url("https://Example.com/a?utm_source=x&utm_campaign=y"), "T")
        b = entry_id(norm_url("https://example.com/a/"), "T")
        assert a == b

    def test_unicode_title_fallback(self) -> None:
        result = entry_id("", "Café AI — 中文标题")
        assert len(result) == 16
        int(result, 16)


# --------------------------------------------------------------------------- #
# clean_text
# --------------------------------------------------------------------------- #


class TestCleanText:
    def test_strips_tags(self) -> None:
        assert clean_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_unescapes_entities(self) -> None:
        assert clean_text("AT&amp;T &lt;3 &quot;AI&quot;") == 'AT&T <3 "AI"'

    def test_collapses_whitespace(self) -> None:
        assert clean_text("  AI\n\n  news\t everywhere ") == "AI news everywhere"

    def test_none_becomes_empty(self) -> None:
        assert clean_text(None) == ""

    def test_empty_stays_empty(self) -> None:
        assert clean_text("") == ""

    def test_tags_and_entities_and_newlines_combined(self) -> None:
        raw = "<div>OpenAI&nbsp;ships\n  <span>a&amp;nbsp;model</span></div>"
        # &amp;nbsp; unescapes once to the literal text "&nbsp;".
        assert clean_text(raw) == "OpenAI ships a&nbsp;model"

    def test_idempotent(self) -> None:
        once = clean_text("<p>Some &amp; text</p>")
        assert clean_text(once) == once

    def test_self_closing_and_br_tags(self) -> None:
        assert clean_text("line<br/>break") == "line break"


# --------------------------------------------------------------------------- #
# language_looks_english
# --------------------------------------------------------------------------- #


class TestLanguageLooksEnglish:
    def test_english_sentence(self) -> None:
        assert language_looks_english(
            "OpenAI announced a new reasoning model for enterprise customers."
        )

    def test_chinese_text_rejected(self) -> None:
        assert not language_looks_english(
            "人工智能工程周报：本周最重要的模型发布与开源项目汇总"
        )

    def test_short_text_abstains(self) -> None:
        """Fewer than 20 ASCII letters is never confidently English."""
        assert not language_looks_english("AI news")
        assert not language_looks_english("")

    def test_exactly_twenty_letters_can_pass(self) -> None:
        text = "abcdefghijklmnopqrst"
        assert len(text) == 20
        assert language_looks_english(text)

    def test_heavy_non_ascii_ratio_rejected(self) -> None:
        """Enough ASCII letters, but the ratio is below the 0.82 threshold."""
        mixed = "OpenAI and Anthropic released new models 人工智能 日本語 リリース"
        assert not language_looks_english(mixed)

    def test_numbers_and_punctuation_alone_rejected(self) -> None:
        assert not language_looks_english("12345 67890 !!! ??? --- *** ###")


# --------------------------------------------------------------------------- #
# effective_source
# --------------------------------------------------------------------------- #


class TestEffectiveSource:
    def test_plain_source_returned(self) -> None:
        assert effective_source(_candidate(source_name="MIT Technology Review")) == (
            "MIT Technology Review"
        )

    def test_google_news_suffix_extracted(self) -> None:
        candidate = _candidate(
            title="OpenAI ships a new model - Reuters",
            source_name="Google News AI",
        )
        assert effective_source(candidate) == "Reuters"

    def test_google_news_without_suffix_keeps_source(self) -> None:
        candidate = _candidate(title="No suffix here", source_name="Google News AI")
        assert effective_source(candidate) == "Google News AI"

    def test_only_last_suffix_segment_used(self) -> None:
        candidate = _candidate(
            title="Deal - Analysis - Bloomberg",
            source_name="google news search",
        )
        assert effective_source(candidate) == "Bloomberg"

    def test_trailing_suffix_whitespace_stripped(self) -> None:
        candidate = _candidate(
            title="Something happened -   CNBC  ", source_name="Google News"
        )
        assert effective_source(candidate) == "CNBC"

    def test_blank_source_becomes_unknown(self) -> None:
        assert effective_source(_candidate(source_name="   ")) == "unknown"


# --------------------------------------------------------------------------- #
# english_summary
# --------------------------------------------------------------------------- #


class TestEnglishSummary:
    def test_keeps_first_two_sentences(self) -> None:
        candidate = _candidate(
            title="News",
            text="First sentence here. Second sentence here. Third is dropped.",
        )
        assert (
            english_summary(candidate) == "First sentence here. Second sentence here."
        )

    def test_strips_leading_title_repeat(self) -> None:
        candidate = _candidate(
            title="OpenAI ships a model",
            text="OpenAI ships a model - it is faster than before. Details follow.",
        )
        summary = english_summary(candidate)
        assert summary.startswith("it is faster than before.")

    def test_fallback_when_text_empty(self) -> None:
        assert english_summary(_candidate(text="")) == FALLBACK_SUMMARY

    def test_fallback_when_only_title_repeated(self) -> None:
        candidate = _candidate(title="Just The Title", text="Just The Title")
        assert english_summary(candidate) == FALLBACK_SUMMARY

    def test_long_summary_is_truncated(self) -> None:
        candidate = _candidate(text=("word " * 400).strip())
        summary = english_summary(candidate)
        assert summary.endswith("...")
        assert len(summary) <= SUMMARY_MAX_CHARS

    def test_single_sentence_kept(self) -> None:
        candidate = _candidate(text="Only one sentence without terminal period")
        assert english_summary(candidate) == "Only one sentence without terminal period"

    def test_question_and_exclamation_split_sentences(self) -> None:
        candidate = _candidate(text="What changed? A lot! Ignore this third part.")
        assert english_summary(candidate) == "What changed? A lot!"
