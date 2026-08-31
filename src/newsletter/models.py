"""Domain models for the AI Engineering Newsletter pipeline.

All models are immutable ``attrs`` frozen classes with full type annotations.
The pipeline flows through these types:

    Source  →  RawRecord  →  Candidate  →  DigestIssue
                  ↑                           ↓
             FetchResult                  PaperPush / Period / RepoRecord
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from attrs import field, frozen

# --------------------------------------------------------------------------- #
# Configuration-level enums
# --------------------------------------------------------------------------- #

Priority = Literal["high", "medium", "low"]
"""Source priority level used in scoring."""

Category = Literal[
    "general_ai",
    "engineering_ai",
    "research",
    "startup",
    "vendor",
    "community",
]
"""Content category as declared in the source registry."""

SourceType = Literal[
    "rss",
    "website",
    "github",
    "arxiv",
    "linkedin_manual",
    "x_api",
    "newsletter",
    "manual",
]
"""High-level source type (broad delivery mechanism)."""

FetchType = Literal[
    # --- Config-level values (declared in [[sources]] entries) ---
    "rss",
    "atom",
    "rdf",
    "website",
    "youtube",
    "api",
    "json",
    # --- Resolved fetch kinds (used at runtime by the fetcher registry) ---
    "google_news_rss",
    "hn_algolia",
    "reddit_json",
    "sitemap_or_search",
    "web_search_query",
]
"""Fetcher strategy.  When omitted on a :class:`Source`, the fetcher
registry resolves it from ``source_type`` via the ``fetch_kind`` logic."""

# --------------------------------------------------------------------------- #
# Source
# --------------------------------------------------------------------------- #


@frozen
class Source:
    """Represents an individual scraping source target.

    Loaded from ``config/config.toml`` ``[[sources]]`` entries.
    Optional fields default to ``None`` so that sources without them
    still structure cleanly.
    """

    name: str
    scrape_url: str
    priority: Priority
    fetch_type: FetchType
    category: Category
    tags: list[str] = field(factory=list)
    notes: str | None = None
    enabled: bool = True
    max_entries: int | None = None
    query: str | None = None
    source_type: SourceType | None = None


# --------------------------------------------------------------------------- #
# Engagement
# --------------------------------------------------------------------------- #


@frozen
class Engagement:
    """Social engagement metrics extracted from API responses.

    All fields are optional because most sources don't expose all three.
    """

    points: int | None = None
    comments: int | None = None
    upvotes: int | None = None


# --------------------------------------------------------------------------- #
# RawRecord
# --------------------------------------------------------------------------- #


@frozen
class RawRecord:
    """A fetched item before scoring or filtering.

    Produced by individual fetchers from RSS feeds, JSON APIs, sitemaps,
    etc.  Converted to :class:`Candidate` once it passes keyword filters
    and receives a score.
    """

    source: Source
    title: str
    url: str
    description: str
    pub_date: datetime | None = None
    engagement: Engagement = field(factory=Engagement)


# --------------------------------------------------------------------------- #
# ScoreBreakdown
# --------------------------------------------------------------------------- #


@frozen
class ScoreBreakdown:
    """Individual sub-scores and composite total.

    Mirrors the v1 ``score_reasons`` list but as a structured model so
    downstream code can access sub-scores by attribute instead of parsing
    strings.

    Composite formula (weights from PROJECT.md §3.4)::

        score = 32 * source_priority
              + 22 * novelty
              + 20 * general_relevance
              + 14 * engineering_relevance
              +  8 * research_relevance
              + 10 * engineering_workflow_ai_boost  (conditional)
              + 14 * log_scale(points, 1200)
              + 10 * log_scale(comments, 800)
              + 10 * log_scale(upvotes, 5000)
    """

    score: float
    source_priority: float = 0.0
    novelty: float = 0.0
    general_relevance: float = 0.0
    engineering_relevance: float = 0.0
    research_relevance: float = 0.0
    engineering_workflow_ai_boost: float = 0.0
    points_score: float = 0.0
    comments_score: float = 0.0
    upvotes_score: float = 0.0


# --------------------------------------------------------------------------- #
# Candidate
# --------------------------------------------------------------------------- #


@frozen
class Candidate:
    """A scored, filtered item ready for deduplication and selection.

    This is the central data type flowing through the pipeline after
    :class:`RawRecord`.  Serialised to ``YYYY-MM-DD-candidates.json``.
    """

    id: str
    title: str
    url: str
    source: Source
    category: Category
    pub_date: datetime | None = None
    text: str = ""
    description: str = ""
    matched_terms: list[str] = field(factory=list)
    engagement: Engagement = field(factory=Engagement)
    score_breakdown: ScoreBreakdown = field(factory=lambda: ScoreBreakdown(score=0.0))
    source_tags: list[str] = field(factory=list)
    registry_category: Category | None = None
    source_priority: Priority | None = None


# --------------------------------------------------------------------------- #
# Fetch results
# --------------------------------------------------------------------------- #


@frozen
class FetchSuccess:
    """Successful fetch outcome for a single source."""

    source: Source
    records: list[RawRecord]
    elapsed_ms: float = 0.0


@frozen
class FetchFailure:
    """Failed fetch outcome for a single source."""

    source: Source
    error: str
    elapsed_ms: float = 0.0


type FetchResult = FetchSuccess | FetchFailure
"""Union type returned by the concurrent fetcher orchestration."""

# --------------------------------------------------------------------------- #
# DigestIssue
# --------------------------------------------------------------------------- #


@frozen
class RunLog:
    """Pipeline execution metadata embedded in the candidates JSON."""

    generated_at: datetime = field(factory=lambda: datetime.now(tz=UTC))
    window_hours: int = 24
    source_count: int = 0
    fetched_count: int = 0
    filtered_count: int = 0
    duplicate_count: int = 0
    failures: list[dict[str, str]] = field(factory=list)


@frozen
class DigestIssue:
    """Final selection output — the four newsletter sections plus metadata.

    Written to ``YYYY-MM-DD-candidates.json`` and consumed by the report
    and site generators.
    """

    run_log: RunLog
    top_10_general_ai: list[Candidate] = field(factory=list)
    top_5_engineering_ai: list[Candidate] = field(factory=list)
    top_5_medical_bio_ai: list[Candidate] = field(factory=list)
    research_radar: list[Candidate] = field(factory=list)
    top_100_news_candidates: list[Candidate] = field(factory=list)
    supplemental_search_tasks: list[dict[str, Any]] = field(factory=list)
    watchlist_updates: list[dict[str, Any]] = field(factory=list)


# --------------------------------------------------------------------------- #
# Period (trend reports)
# --------------------------------------------------------------------------- #


@frozen
class Period:
    """Weekly or monthly reporting period anchor."""

    label: Literal["weekly", "monthly"]
    start: datetime
    end: datetime


# --------------------------------------------------------------------------- #
# RepoRecord (GitHub trend data)
# --------------------------------------------------------------------------- #


@frozen
class RepoRecord:
    """Normalised GitHub repository snapshot, one row in ``repos.jsonl``."""

    snapshot_date: str
    full_name: str
    url: str
    description: str = ""
    language: str = ""
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    last_update: str = ""
    created_at: str = ""
    pushed_at: str = ""
    author: str = ""
    category: str = ""
    matched_categories: list[str] = field(factory=list)
    topics: list[str] = field(factory=list)
    source: str = ""
    stars_gained_hint: int = 0
    forks_gained_hint: int = 0
    source_notes: list[str] = field(factory=list)


# --------------------------------------------------------------------------- #
# PaperPush (Friday arXiv results)
# --------------------------------------------------------------------------- #


@frozen
class Paper:
    """A single arXiv paper entry in the Friday push."""

    title: str
    url: str
    source: str = "arXiv"
    published: str = ""
    authors: list[str] = field(factory=list)
    summary_en: str = ""
    summary_zh: str = ""
    why: str = ""


@frozen
class PaperPush:
    """Friday arXiv paper push output.

    Written to ``YYYY-MM-DD-paper-push.json``.  Contains bilingual fields
    for the English + Chinese editions.
    """

    title_zh: str = ""
    title_en: str = ""
    intro_zh: str = ""
    intro_en: str = ""
    cae_sources_checked: list[str] = field(factory=list)
    cae_papers: list[Paper] = field(factory=list)
    biomedical_papers: list[Paper] = field(factory=list)
