"""Tests for newsletter.pipeline — the collect stage (Goals 3.3, 6.1–6.5)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from newsletter.configuration import Configuration
from newsletter.keywords import KeywordConfig
from newsletter.models import (
    Candidate,
    Category,
    Engagement,
    FetchFailure,
    FetchResult,
    FetchSuccess,
    FetchType,
    Priority,
    RawRecord,
    RunLog,
    Source,
)
from newsletter.pipeline import (
    MAX_CANDIDATES_TOTAL,
    TEXT_PREVIEW_LIMIT,
    base_window_hours,
    build_issue,
    candidate_from_record,
    collect,
    is_stale,
    widens_to_engineering_window,
    window_hours_for,
)
from newsletter.text import entry_id

ConfigurationFactory = Callable[..., Configuration]
CandidateFactory = Callable[..., Candidate]

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

# Passes the general bucket: "OpenAI" + "AI" include terms, English, dated now.
GENERAL_TITLE = "OpenAI releases a new foundation model"
GENERAL_TEXT = "The company says the LLM agent beats every published benchmark."

# Passes only the engineering bucket: no general include term, but CFD (include
# and core gate) plus "surrogate" (ai_include gate).
ENGINEERING_TITLE = "CFD surrogate model speeds up thermal simulation"
ENGINEERING_TEXT = "The reduced order model cuts solver runs from hours to seconds."


def _source(
    name: str = "Test Blog",
    category: Category = "general_ai",
    priority: Priority = "high",
    fetch_type: FetchType | None = "rss",
    tags: list[str] | None = None,
) -> Source:
    return Source(
        name=name,
        scrape_url=f"https://example.com/{name.lower().replace(' ', '-')}/feed",
        priority=priority,
        category=category,
        fetch_type=fetch_type,
        tags=tags or [],
    )


def _record(
    title: str = GENERAL_TITLE,
    description: str = GENERAL_TEXT,
    url: str = "https://example.com/story",
    source: Source | None = None,
    pub_date: datetime | None = NOW,
    engagement: Engagement | None = None,
) -> RawRecord:
    return RawRecord(
        source=source or _source(),
        title=title,
        url=url,
        description=description,
        pub_date=pub_date,
        engagement=engagement or Engagement(),
    )


def _score(
    record: RawRecord,
    make_configuration: ConfigurationFactory,
    keyword_config: KeywordConfig,
    *,
    now: datetime = NOW,
    window_hours: int = 24,
    config: Configuration | None = None,
) -> Candidate | None:
    return candidate_from_record(
        record,
        config=config or make_configuration(),
        keywords=keyword_config,
        now=now,
        default_window_hours=window_hours,
    )


# --------------------------------------------------------------------------- #
# Window resolution
# --------------------------------------------------------------------------- #


class TestWindowResolution:
    def test_category_window_from_config(
        self, make_configuration: ConfigurationFactory
    ) -> None:
        config = make_configuration()
        assert base_window_hours("general_ai", config, 24) == 24
        assert base_window_hours("engineering_ai", config, 24) == 720
        assert base_window_hours("research", config, 24) == 168

    def test_legacy_category_alias(
        self, make_configuration: ConfigurationFactory
    ) -> None:
        config = make_configuration()
        assert base_window_hours("cae_ai_engineering", config, 24) == 720

    def test_unknown_category_uses_default(
        self, make_configuration: ConfigurationFactory
    ) -> None:
        config = make_configuration(category_window_hours={"general_ai": 24})
        assert base_window_hours("research", config, 48) == 48

    def test_discovery_source_widens_for_engineering_match(
        self, keyword_config: KeywordConfig
    ) -> None:
        assert widens_to_engineering_window(
            "general_ai",
            "sitemap_or_search",
            ENGINEERING_TITLE.lower(),
            True,
            keyword_config,
        )

    def test_rss_source_never_widens(self, keyword_config: KeywordConfig) -> None:
        assert not widens_to_engineering_window(
            "general_ai", "rss", ENGINEERING_TITLE.lower(), True, keyword_config
        )

    def test_engineering_source_does_not_widen(
        self, keyword_config: KeywordConfig
    ) -> None:
        """It already uses the engineering window."""
        assert not widens_to_engineering_window(
            "engineering_ai",
            "sitemap_or_search",
            ENGINEERING_TITLE.lower(),
            True,
            keyword_config,
        )

    def test_widening_needs_an_ai_term(self, keyword_config: KeywordConfig) -> None:
        # No ai_include term here — "cfd" alone is domain-only.  (Careful:
        # "plain" contains "ai", which the substring gate would accept.)
        assert not widens_to_engineering_window(
            "general_ai",
            "sitemap_or_search",
            "cfd mesh generation runs faster",
            True,
            keyword_config,
        )

    def test_widening_needs_an_engineering_match(
        self, keyword_config: KeywordConfig
    ) -> None:
        assert not widens_to_engineering_window(
            "general_ai",
            "sitemap_or_search",
            ENGINEERING_TITLE.lower(),
            False,
            keyword_config,
        )

    def test_window_hours_for_applies_widening(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        config = make_configuration()
        widened = window_hours_for(
            "general_ai",
            "sitemap_or_search",
            ENGINEERING_TITLE.lower(),
            True,
            config=config,
            keywords=keyword_config,
            default=24,
        )
        plain = window_hours_for(
            "general_ai",
            "rss",
            ENGINEERING_TITLE.lower(),
            True,
            config=config,
            keywords=keyword_config,
            default=24,
        )
        assert widened == 720
        assert plain == 24


class TestIsStale:
    def test_undated_items_are_never_stale(self) -> None:
        assert not is_stale(None, NOW, 24)

    def test_fresh_item(self) -> None:
        assert not is_stale(NOW - timedelta(hours=1), NOW, 24)

    def test_old_item(self) -> None:
        assert is_stale(NOW - timedelta(hours=25), NOW, 24)

    def test_future_item(self) -> None:
        assert not is_stale(NOW + timedelta(hours=5), NOW, 24)


# --------------------------------------------------------------------------- #
# candidate_from_record
# --------------------------------------------------------------------------- #


class TestCandidateFromRecord:
    def test_passing_record_becomes_candidate(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        record = _record()
        candidate = _score(record, make_configuration, keyword_config)

        assert candidate is not None
        assert candidate.title == GENERAL_TITLE
        assert candidate.url == "https://example.com/story"
        assert candidate.id == entry_id(candidate.url, candidate.title)
        assert candidate.text == GENERAL_TEXT
        assert candidate.description == GENERAL_TEXT
        assert candidate.matched_terms
        assert candidate.category == "general_ai"
        assert candidate.registry_category == "general_ai"
        assert candidate.source_priority == "high"
        assert candidate.score_breakdown.score > 0.0

    def test_html_and_entities_are_cleaned(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        record = _record(
            title="OpenAI &amp; Anthropic ship models",
            description="<p>An <b>LLM</b> &amp; agent&nbsp;release</p>",
        )
        candidate = _score(record, make_configuration, keyword_config)

        assert candidate is not None
        assert candidate.title == "OpenAI & Anthropic ship models"
        assert "<" not in candidate.text
        assert candidate.text == "An LLM & agent release"

    def test_urls_are_normalized(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        record = _record(url="https://Example.com/story/?utm_source=rss#top")
        candidate = _score(record, make_configuration, keyword_config)

        assert candidate is not None
        assert candidate.url == "https://example.com/story"
        assert candidate.id == entry_id("https://example.com/story", GENERAL_TITLE)

    def test_text_is_truncated(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        record = _record(description=f"An OpenAI LLM release. {'x' * 4000}")
        candidate = _score(record, make_configuration, keyword_config)

        assert candidate is not None
        assert len(candidate.text) == TEXT_PREVIEW_LIMIT
        # The raw description is preserved for downstream summarizers.
        assert len(candidate.description) > TEXT_PREVIEW_LIMIT

    @pytest.mark.parametrize(
        ("title", "url"),
        [
            ("", "https://example.com/story"),
            ("   ", "https://example.com/story"),
            (GENERAL_TITLE, ""),
        ],
    )
    def test_missing_title_or_url_rejected(
        self,
        make_configuration: ConfigurationFactory,
        keyword_config: KeywordConfig,
        title: str,
        url: str,
    ) -> None:
        assert (
            _score(_record(title=title, url=url), make_configuration, keyword_config)
            is None
        )

    def test_non_english_rejected(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        record = _record(
            title="OpenAI 发布新模型",
            description="人工智能工程周报：本周最重要的模型发布与开源项目汇总",
        )
        assert _score(record, make_configuration, keyword_config) is None

    def test_no_keyword_match_rejected(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        record = _record(
            title="Local council approves a bicycle lane",
            description="The lane opens next spring.",
        )
        assert _score(record, make_configuration, keyword_config) is None

    def test_excluded_term_rejected(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        """An exclude hit wins over any number of include hits."""
        record = _record(
            title="OpenAI LLM agents and AI washing claims",
            description="Analysts debate the AI washing label.",
        )
        assert _score(record, make_configuration, keyword_config) is None

    def test_stale_record_rejected(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        record = _record(pub_date=NOW - timedelta(hours=48))
        assert _score(record, make_configuration, keyword_config) is None

    def test_undated_record_kept(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        record = _record(pub_date=None)
        candidate = _score(record, make_configuration, keyword_config)

        assert candidate is not None
        assert candidate.pub_date is None
        assert candidate.score_breakdown.novelty == 0.35

    def test_engineering_bucket_fallback(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        """A general source publishing an engineering story is re-bucketed."""
        record = _record(title=ENGINEERING_TITLE, description=ENGINEERING_TEXT)
        candidate = _score(record, make_configuration, keyword_config)

        assert candidate is not None
        assert "CFD" in candidate.matched_terms
        assert candidate.score_breakdown.engineering_relevance >= 0.5
        assert candidate.category == "engineering_ai"

    def test_engineering_ai_gate_blocks_domain_only_text(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        """CFD without any AI term fails the ai_include gate."""
        record = _record(
            title="CFD mesh generation for thermal simulation",
            description="A solver upgrade improves finite volume accuracy.",
        )
        assert _score(record, make_configuration, keyword_config) is None

    def test_core_include_gate_blocks_non_engineering_text(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        """'digital twin' is an include term but not a core_include term."""
        record = _record(
            title="A digital twin for a battery plant",
            description="The twin mirrors a production line.",
        )
        assert _score(record, make_configuration, keyword_config) is None

    def test_engineering_source_forces_relevance(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        source = _source(category="engineering_ai")
        record = _record(
            title=ENGINEERING_TITLE, description=ENGINEERING_TEXT, source=source
        )
        candidate = _score(record, make_configuration, keyword_config)

        assert candidate is not None
        assert candidate.score_breakdown.engineering_relevance == 1.0
        assert candidate.category == "engineering_ai"

    def test_discovery_window_lets_old_engineering_items_through(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        """A 100h-old sitemap find survives on the 720h engineering window."""
        source = _source(fetch_type="website")
        old = NOW - timedelta(hours=100)
        engineering = _record(
            title=ENGINEERING_TITLE,
            description=ENGINEERING_TEXT,
            source=source,
            pub_date=old,
        )
        general = _record(
            title=GENERAL_TITLE, description=GENERAL_TEXT, source=source, pub_date=old
        )

        assert _score(engineering, make_configuration, keyword_config) is not None
        assert _score(general, make_configuration, keyword_config) is None

    def test_priority_presets_come_from_config(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        config = make_configuration(
            priority_presets={"high": 0.5, "medium": 0.4, "low": 0.1}
        )
        candidate = _score(_record(), make_configuration, keyword_config, config=config)

        assert candidate is not None
        assert candidate.score_breakdown.source_priority == 0.5

    def test_engagement_reaches_the_breakdown(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        record = _record(engagement=Engagement(points=1200, comments=800, upvotes=5000))
        candidate = _score(record, make_configuration, keyword_config)

        assert candidate is not None
        assert candidate.engagement.points == 1200
        assert candidate.score_breakdown.points_score == 1.0
        assert candidate.score_breakdown.comments_score == 1.0
        assert candidate.score_breakdown.upvotes_score == 1.0

    def test_recency_uses_the_effective_window(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        """A 12h-old item in a 24h window scores 0.625 novelty."""
        record = _record(pub_date=NOW - timedelta(hours=12))
        candidate = _score(record, make_configuration, keyword_config)

        assert candidate is not None
        assert candidate.score_breakdown.novelty == pytest.approx(0.625)


# --------------------------------------------------------------------------- #
# collect
# --------------------------------------------------------------------------- #


class TestCollect:
    def test_empty_results(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        config = make_configuration(sources=[_source()])
        candidates, run_log = collect(
            [], config=config, keywords=keyword_config, now=NOW
        )

        assert candidates == []
        assert run_log.source_count == 1
        assert run_log.fetched_count == 0
        assert run_log.filtered_count == 0
        assert run_log.duplicate_count == 0
        assert run_log.failures == []
        assert run_log.generated_at == NOW

    def test_sorts_by_score_descending(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        high = _source(name="High Priority", priority="high")
        low = _source(name="Low Priority", priority="low")
        config = make_configuration(sources=[high, low])
        results = [
            FetchSuccess(
                source=low,
                records=[_record(source=low, url="https://low.com/story")],
            ),
            FetchSuccess(
                source=high,
                records=[_record(source=high, url="https://high.com/story")],
            ),
        ]

        candidates, run_log = collect(
            results, config=config, keywords=keyword_config, now=NOW
        )

        assert [c.source.name for c in candidates] == ["High Priority", "Low Priority"]
        scores = [c.score_breakdown.score for c in candidates]
        assert scores == sorted(scores, reverse=True)
        assert run_log.filtered_count == 2

    def test_deduplicates_by_url(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        first = _source(name="Outlet A")
        second = _source(name="Outlet B")
        config = make_configuration(sources=[first, second])
        results = [
            FetchSuccess(
                source=first,
                records=[_record(source=first, url="https://a.com/story")],
            ),
            FetchSuccess(
                source=second,
                records=[
                    _record(source=second, url="https://a.com/story?utm_source=rss")
                ],
            ),
        ]

        candidates, run_log = collect(
            results, config=config, keywords=keyword_config, now=NOW
        )

        assert len(candidates) == 1
        assert candidates[0].source.name == "Outlet A"
        assert run_log.duplicate_count == 1
        assert run_log.fetched_count == 2

    def test_failures_are_captured(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        broken = _source(name="Broken Feed")
        config = make_configuration(sources=[broken])
        results = [
            FetchFailure(
                source=broken, error="MaxRetriesExceeded: 503", elapsed_ms=12.0
            )
        ]

        candidates, run_log = collect(
            results, config=config, keywords=keyword_config, now=NOW
        )

        assert candidates == []
        assert run_log.failures == [
            {"source": "Broken Feed", "error": "MaxRetriesExceeded: 503"}
        ]
        assert run_log.fetched_count == 0

    def test_filtered_records_do_not_count(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        source = _source()
        config = make_configuration(sources=[source])
        results = [
            FetchSuccess(
                source=source,
                records=[
                    _record(source=source, url="https://a.com/1"),
                    _record(
                        source=source,
                        title="Local council approves a bicycle lane",
                        description="The lane opens next spring.",
                        url="https://a.com/2",
                    ),
                ],
            )
        ]

        candidates, run_log = collect(
            results, config=config, keywords=keyword_config, now=NOW
        )

        assert len(candidates) == 1
        assert run_log.fetched_count == 2
        assert run_log.filtered_count == 1

    def test_unexpected_result_objects_are_ignored(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        """Defensive: anything that is not a FetchResult contributes nothing."""
        config = make_configuration(sources=[_source()])
        results = [cast("FetchResult", "not a fetch result")]

        candidates, run_log = collect(
            results, config=config, keywords=keyword_config, now=NOW
        )

        assert candidates == []
        assert run_log.fetched_count == 0
        assert run_log.failures == []

    def test_window_hours_reach_the_run_log(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        config = make_configuration(sources=[_source()])
        _, run_log = collect(
            [], config=config, keywords=keyword_config, now=NOW, default_window_hours=48
        )
        assert run_log.window_hours == 48

    def test_now_defaults_to_the_current_time(
        self, make_configuration: ConfigurationFactory, keyword_config: KeywordConfig
    ) -> None:
        config = make_configuration(sources=[_source()])
        before = datetime.now(tz=UTC)
        _, run_log = collect([], config=config, keywords=keyword_config)
        assert run_log.generated_at >= before


# --------------------------------------------------------------------------- #
# build_issue
# --------------------------------------------------------------------------- #


class TestBuildIssue:
    def test_sections_are_filled(self, make_candidate: CandidateFactory) -> None:
        candidates = [
            make_candidate(
                title="OpenAI releases a model",
                url="https://a.com/1",
                category="general_ai",
            ),
            make_candidate(
                title="CFD simulation with a surrogate model",
                url="https://b.com/2",
                category="engineering_ai",
            ),
            make_candidate(
                title="A clinical trial uses machine learning",
                url="https://c.com/3",
                category="general_ai",
            ),
            make_candidate(
                title="An arxiv benchmark dataset",
                url="https://d.com/4",
                category="research",
            ),
        ]

        issue = build_issue(candidates, RunLog(source_count=4))

        assert len(issue.top_10_general_ai) >= 1
        assert len(issue.top_5_engineering_ai) == 1
        assert len(issue.top_5_medical_bio_ai) == 1
        assert len(issue.research_radar) == 1
        assert issue.top_100_news_candidates == candidates

    def test_candidate_pool_is_capped(self, make_candidate: CandidateFactory) -> None:
        candidates = [
            make_candidate(
                title=f"Zebra story {i} alpha beta", url=f"https://n{i}.com/{i}"
            )
            for i in range(MAX_CANDIDATES_TOTAL + 50)
        ]

        issue = build_issue(candidates, RunLog())

        assert len(issue.top_100_news_candidates) == MAX_CANDIDATES_TOTAL

    def test_history_suppresses_repeats(self, make_candidate: CandidateFactory) -> None:
        published = make_candidate(
            title="Nvidia unveils a GPU", url="https://a.com/1", source_name="Outlet A"
        )
        repeat = make_candidate(
            title="Nvidia unveils a GPU", url="https://b.com/2", source_name="Outlet A"
        )
        fresh = make_candidate(
            title="Quartz kiosk lantern report", url="https://c.com/3"
        )

        issue = build_issue(
            [repeat, fresh], RunLog(), history={"general_ai": [published]}
        )

        assert issue.top_10_general_ai == [fresh]

    def test_biomedical_section_may_overlap_general(
        self, make_candidate: CandidateFactory
    ) -> None:
        """v1 parity: the medical section re-reads general/research items."""
        medical = make_candidate(
            title="A hospital deploys machine learning", url="https://a.com/1"
        )

        issue = build_issue([medical], RunLog())

        assert medical in issue.top_10_general_ai
        assert medical in issue.top_5_medical_bio_ai

    def test_run_log_is_passed_through(self, make_candidate: CandidateFactory) -> None:
        run_log = RunLog(source_count=7, fetched_count=42, filtered_count=3)
        issue = build_issue([], run_log)

        assert issue.run_log is run_log

    def test_empty_candidates(self) -> None:
        issue = build_issue([], RunLog())

        assert issue.top_10_general_ai == []
        assert issue.top_5_engineering_ai == []
        assert issue.top_5_medical_bio_ai == []
        assert issue.research_radar == []
        assert issue.top_100_news_candidates == []
