"""Collect stage: raw records → filtered, scored, deduplicated candidates.

This is the v2 home of v1's ``build_digest_candidates.build_candidates``
loop (PROJECT.md §3.3): clean the record, apply the language and recency
gates, run the keyword buckets, deduplicate by URL, score, infer the
section, then sort by score.

The stage is deliberately synchronous — fetching is async (Goal 3) but
scoring and filtering are cheap CPU work over a few thousand records, so
adding threads would only add noise.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from .category import canonical_category, infer_candidate_category
from .configuration import Configuration
from .dedup import dedup_key, norm_url
from .fetchers import fetch_kind
from .keywords import KeywordConfig, matches, matches_core_terms
from .models import (
    Candidate,
    DigestIssue,
    FetchFailure,
    FetchResult,
    FetchSuccess,
    RawRecord,
    RunLog,
)
from .scoring import score_candidate
from .selection import (
    ENGINEERING_AI_LIMIT,
    GENERAL_AI_LIMIT,
    MEDICAL_BIO_AI_LIMIT,
    RESEARCH_RADAR_LIMIT,
    select_medical_bio_ai,
    select_unique_events,
)
from .text import clean_text, entry_id, language_looks_english

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Limits (v1 parity)
# --------------------------------------------------------------------------- #

#: Characters of cleaned body text kept on a candidate.
TEXT_PREVIEW_LIMIT: int = 1200

#: Candidates retained in ``top_100_news_candidates``.
MAX_CANDIDATES_TOTAL: int = 100

#: Fetch kind whose window widens to the engineering window on a match.
DISCOVERY_KIND: str = "sitemap_or_search"


# --------------------------------------------------------------------------- #
# Recency window resolution
# --------------------------------------------------------------------------- #


def base_window_hours(
    source_category: str,
    config: Configuration,
    default: int,
) -> int:
    """Per-category look-back window from config, else the CLI default."""
    category = canonical_category(source_category)
    return int(config.category_window_hours.get(category, default))


def widens_to_engineering_window(
    source_category: str,
    kind: str,
    candidate_text: str,
    engineering_ok: bool,
    keywords: KeywordConfig,
) -> bool:
    """Whether a discovery source's item earns the long engineering window.

    Website/sitemap discovery yields undated or loosely dated links, so v1
    keeps an engineering-relevant discovery item for the whole engineering
    window (720h by default) instead of the source's own window.
    """
    if kind != DISCOVERY_KIND:
        return False
    if canonical_category(source_category) == "engineering_ai":
        return False
    if not engineering_ok:
        return False
    return matches_core_terms(candidate_text, keywords.engineering_ai.ai_include)


def window_hours_for(
    source_category: str,
    kind: str,
    candidate_text: str,
    engineering_ok: bool,
    *,
    config: Configuration,
    keywords: KeywordConfig,
    default: int,
) -> int:
    """Effective look-back window for one record (v1 parity)."""
    base = base_window_hours(source_category, config, default)
    if widens_to_engineering_window(
        source_category, kind, candidate_text, engineering_ok, keywords
    ):
        return int(config.category_window_hours.get("engineering_ai", base))
    return base


def is_stale(published_at: datetime | None, now: datetime, window_hours: int) -> bool:
    """Whether an item predates the look-back window.

    Undated items are never stale — discovery sources routinely omit dates
    and the novelty sub-score already penalises them.
    """
    if published_at is None:
        return False
    return published_at < now - timedelta(hours=window_hours)


# --------------------------------------------------------------------------- #
# Record → Candidate
# --------------------------------------------------------------------------- #


def candidate_from_record(
    record: RawRecord,
    *,
    config: Configuration,
    keywords: KeywordConfig,
    now: datetime,
    default_window_hours: int = 24,
) -> Candidate | None:
    """Clean, gate and score one record; ``None`` means "filtered out".

    Gate order matches v1 so the same feeds produce the same digest:

    1. clean title/url/text (HTML entities, tags, whitespace);
    2. recency cutoff for the resolved window;
    3. non-empty title *and* URL, plus the English heuristic;
    4. the source's keyword bucket — falling back to the engineering bucket
       when the general bucket rejects but engineering matches;
    5. the winning bucket's ``core_include`` and ``ai_include`` gates.

    The URL is normalized and the ID derived from it, so equivalent links
    collapse to one candidate downstream.
    """
    source = record.source
    source_category = canonical_category(source.category)
    kind = fetch_kind(source)

    title = clean_text(record.title)
    url = norm_url(record.url)
    text = clean_text(record.description or title)
    candidate_text = f"{title} {text}"

    engineering_filter = keywords.engineering_ai
    engineering_matches, engineering_ok = matches(candidate_text, engineering_filter)

    window_hours = window_hours_for(
        source_category,
        kind,
        candidate_text,
        engineering_ok,
        config=config,
        keywords=keywords,
        default=default_window_hours,
    )
    if is_stale(record.pub_date, now, window_hours):
        return None

    if not title or not url or not language_looks_english(candidate_text):
        return None

    keyword_filter = keywords.filter_for(source_category)
    matched, ok = matches(candidate_text, keyword_filter)
    if not ok and engineering_ok:
        keyword_filter = engineering_filter
        matched = engineering_matches
        ok = True
    if not ok:
        return None
    if not matches_core_terms(candidate_text, keyword_filter.core_include):
        return None
    if not matches_core_terms(candidate_text, keyword_filter.ai_include):
        return None

    breakdown = score_candidate(
        source,
        record.engagement,
        matched,
        record.pub_date,
        now,
        window_hours,
        candidate_text,
        priority_presets=config.priority_presets,
    )
    category = infer_candidate_category(source_category, candidate_text, breakdown)

    return Candidate(
        id=entry_id(url, title),
        title=title,
        url=url,
        source=source,
        category=category,
        pub_date=record.pub_date,
        text=text[:TEXT_PREVIEW_LIMIT],
        description=record.description,
        matched_terms=matched,
        engagement=record.engagement,
        score_breakdown=breakdown,
        registry_category=source_category,
        source_priority=source.priority,
    )


# --------------------------------------------------------------------------- #
# Batch collection
# --------------------------------------------------------------------------- #


def collect(
    results: Sequence[FetchResult],
    *,
    config: Configuration,
    keywords: KeywordConfig,
    now: datetime | None = None,
    default_window_hours: int = 24,
) -> tuple[list[Candidate], RunLog]:
    """Turn fetch results into a score-sorted candidate list plus a run log.

    Duplicates are dropped by :func:`~newsletter.dedup.dedup_key` (normalized
    URL, else lowercased title) in fetch order, so the highest-ranked copy of
    a story is the first one seen — matching v1.
    """
    timestamp = now or datetime.now(tz=UTC)
    seen: set[str] = set()
    candidates: list[Candidate] = []
    failures: list[dict[str, str]] = []
    fetched_count = 0
    duplicate_count = 0

    for result in results:
        if isinstance(result, FetchFailure):
            logger.warning(
                "Source %r failed (%.0f ms): %s",
                result.source.name,
                result.elapsed_ms,
                result.error,
            )
            failures.append({"source": result.source.name, "error": result.error})
            continue
        if not isinstance(result, FetchSuccess):
            continue

        fetched_count += len(result.records)
        for record in result.records:
            candidate = candidate_from_record(
                record,
                config=config,
                keywords=keywords,
                now=timestamp,
                default_window_hours=default_window_hours,
            )
            if candidate is None:
                continue
            key = dedup_key(candidate.title, candidate.url)
            if key in seen:
                duplicate_count += 1
                continue
            seen.add(key)
            candidates.append(candidate)

    candidates.sort(key=lambda item: item.score_breakdown.score, reverse=True)

    run_log = RunLog(
        generated_at=timestamp,
        window_hours=default_window_hours,
        source_count=len(config.sources),
        fetched_count=fetched_count,
        filtered_count=len(candidates),
        duplicate_count=duplicate_count,
        failures=failures,
    )
    logger.info(
        "Collected %d candidates from %d records (%d duplicates dropped, %d failures)",
        len(candidates),
        fetched_count,
        duplicate_count,
        len(failures),
    )
    return candidates, run_log


# --------------------------------------------------------------------------- #
# Section selection
# --------------------------------------------------------------------------- #


def build_issue(
    candidates: Sequence[Candidate],
    run_log: RunLog,
    *,
    history: Mapping[str, Sequence[Candidate]] | None = None,
) -> DigestIssue:
    """Select the four sections from a score-sorted candidate list.

    ``history`` maps a section key (``general_ai``, ``engineering_ai``,
    ``medical_bio_ai``, ``research``) to previously published items; see
    :func:`newsletter.artifacts.load_history`.

    Sections are selected independently, exactly as v1 does.  Categories are
    mutually exclusive, so the only intended overlap is biomedical: that
    section deliberately re-reads ``general_ai`` and ``research`` candidates.
    Cross-run repetition is what the history lookback suppresses.
    """
    lookback = history or {}
    return DigestIssue(
        run_log=run_log,
        top_10_general_ai=select_unique_events(
            candidates, "general_ai", GENERAL_AI_LIMIT, lookback.get("general_ai")
        ),
        top_5_engineering_ai=select_unique_events(
            candidates,
            "engineering_ai",
            ENGINEERING_AI_LIMIT,
            lookback.get("engineering_ai"),
        ),
        top_5_medical_bio_ai=select_medical_bio_ai(
            candidates, MEDICAL_BIO_AI_LIMIT, lookback.get("medical_bio_ai")
        ),
        research_radar=select_unique_events(
            candidates, "research", RESEARCH_RADAR_LIMIT, lookback.get("research")
        ),
        top_100_news_candidates=list(candidates[:MAX_CANDIDATES_TOTAL]),
    )
