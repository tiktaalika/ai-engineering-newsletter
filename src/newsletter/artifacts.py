"""Artifact serialization and the on-disk contract (Goal 8.4).

The v2 pipeline must keep producing byte-compatible ``*-candidates.json``
files so the report generator, site renderer and quality gate — plus the
historical dedup that reads previously published issues — keep working.

Schema (v1 parity, PROJECT.md §3.9–§3.10):

* one JSON object per issue with fixed top-level keys, in v1's order;
* one flat object per candidate (``source`` is the *name*, ``source_kind``
  the resolved fetch kind, sub-scores flattened next to ``score``);
* ``published_at`` as an ISO-8601 string or ``null``;
* ``engagement`` holding only the counters a source actually provided.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .category import canonical_category
from .fetchers import fetch_kind
from .models import (
    Candidate,
    DigestIssue,
    Engagement,
    Priority,
    RunLog,
    ScoreBreakdown,
    Source,
)
from .scoring import score_reasons

logger = logging.getLogger(__name__)

#: File name pattern for published issues, e.g. ``2026-06-17-candidates.json``.
CANDIDATES_SUFFIX: str = "-candidates.json"

#: Which sections each history lookback reads (v1 parity).  Engineering reads
#: both of its keys because older artifacts used the legacy section name.
HISTORY_SECTION_KEYS: dict[str, tuple[str, ...]] = {
    "general_ai": ("top_10_general_ai",),
    "engineering_ai": ("top_5_engineering_ai", "top_5_cae_ai_engineering"),
    "medical_bio_ai": ("top_5_medical_bio_ai",),
    "research": ("research_radar",),
}

#: Legacy section/category names accepted by :func:`history_category`.
_HISTORY_ALIASES: dict[str, str] = {"cae_ai_engineering": "engineering_ai"}

#: Explanatory block copied verbatim into every artifact (v1 parity), so the
#: digest stays self-documenting for the downstream agent.
SELECTION_POLICY: dict[str, str] = {
    "general_ai": (
        "top 10 scored English AI news items after event deduplication and "
        "topic diversification; Guo Yichen reference sources are preferred, "
        "then other curated sources fill remaining slots"
    ),
    "engineering_ai": (
        "top 5 scored engineering AI items covering simulation, CAD, CAE, "
        "SPDM, PLM, digital twin, physical AI, scientific ML, and industrial AI"
    ),
    "medical_bio_ai": (
        "top 5 scored medical, medicine, biotech, biology, genomics, and "
        "genetics AI items after event deduplication and topic diversification"
    ),
    "research_radar": "optional research items from research/community sources",
    "ranking_note": (
        "Score estimates readership/engagement when direct read counts are "
        "unavailable. Selection prefers topic diversity so one hot area does "
        "not crowd out the whole digest."
    ),
    "history_deduplication": (
        "General AI excludes similar selected items from the previous 7 days. "
        "Engineering AI, Biomedical AI, and Research Radar exclude similar "
        "selected items from the previous 30 days so long discovery windows "
        "do not cause repeated daily publication."
    ),
}


# --------------------------------------------------------------------------- #
# Candidate → dict
# --------------------------------------------------------------------------- #


def _engagement_dict(engagement: Engagement) -> dict[str, int]:
    """Only the counters a source actually provided (v1 wrote ``{}``)."""
    return {
        name: value
        for name, value in (
            ("points", engagement.points),
            ("comments", engagement.comments),
            ("upvotes", engagement.upvotes),
        )
        if value is not None
    }


def candidate_to_dict(candidate: Candidate) -> dict[str, Any]:
    """Flatten a candidate into the v1-compatible artifact object."""
    breakdown = candidate.score_breakdown
    return {
        "id": candidate.id,
        "title": candidate.title,
        "url": candidate.url,
        "source": candidate.source.name,
        "source_kind": fetch_kind(candidate.source),
        "category": candidate.category,
        "published_at": (
            candidate.pub_date.isoformat() if candidate.pub_date else None
        ),
        "text": candidate.text,
        "matched_terms": list(candidate.matched_terms),
        "engagement": _engagement_dict(candidate.engagement),
        "score": breakdown.score,
        "score_reasons": score_reasons(
            breakdown, candidate.matched_terms, candidate.engagement
        ),
        "general_ai_score": breakdown.general_relevance,
        "engineering_relevance_score": breakdown.engineering_relevance,
        "research_relevance_score": breakdown.research_relevance,
        "novelty_score": breakdown.novelty,
        "source_priority_score": breakdown.source_priority,
        "source_tags": list(candidate.source.tags),
        "registry_category": candidate.registry_category
        or canonical_category(candidate.source.category),
        "source_priority": candidate.source_priority or candidate.source.priority,
    }


# --------------------------------------------------------------------------- #
# dict → Candidate (historical dedup)
# --------------------------------------------------------------------------- #


def _as_priority(value: Any) -> Priority:
    """Validated priority label, defaulting to ``medium`` (v1 parity)."""
    if value == "high":
        return "high"
    if value == "low":
        return "low"
    return "medium"


def candidate_from_dict(item: dict[str, Any]) -> Candidate:
    """Rebuild a candidate from an artifact object.

    Only the fields the selection stage inspects need to survive: the
    headline, URL, category, source name/kind/tags and priority.  The
    registry URL is not part of the v1 schema, so the item URL stands in —
    history is only ever compared, never re-fetched.
    """
    registry_category = canonical_category(str(item.get("registry_category") or ""))
    source_kind = item.get("source_kind")

    source = Source(
        name=str(item.get("source") or ""),
        scrape_url=str(item.get("url") or ""),
        priority=_as_priority(item.get("source_priority")),
        category=registry_category,
        fetch_type=source_kind if source_kind else None,
        tags=[str(tag) for tag in (item.get("source_tags") or [])],
    )

    breakdown = ScoreBreakdown(
        score=float(item.get("score") or 0.0),
        source_priority=float(item.get("source_priority_score") or 0.0),
        novelty=float(item.get("novelty_score") or 0.0),
        general_relevance=float(item.get("general_ai_score") or 0.0),
        engineering_relevance=float(item.get("engineering_relevance_score") or 0.0),
        research_relevance=float(item.get("research_relevance_score") or 0.0),
    )
    engagement_raw = item.get("engagement") or {}
    text = str(item.get("text") or "")

    return Candidate(
        id=str(item.get("id") or ""),
        title=str(item.get("title") or ""),
        url=str(item.get("url") or ""),
        source=source,
        category=canonical_category(str(item.get("category") or "")),
        pub_date=_parse_published(item.get("published_at")),
        text=text,
        description=text,
        matched_terms=[str(term) for term in (item.get("matched_terms") or [])],
        engagement=Engagement(
            points=engagement_raw.get("points"),
            comments=engagement_raw.get("comments"),
            upvotes=engagement_raw.get("upvotes"),
        ),
        score_breakdown=breakdown,
        registry_category=registry_category,
        source_priority=source.priority,
    )


def _parse_published(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        logger.debug("Unparsable published_at in artifact: %r", value)
        return None


# --------------------------------------------------------------------------- #
# Issue → payload
# --------------------------------------------------------------------------- #


def run_log_to_dict(run_log: RunLog) -> dict[str, Any]:
    """Serialize run metadata in v1's key order."""
    return {
        "generated_at": run_log.generated_at.isoformat(),
        "window_hours": run_log.window_hours,
        "source_count": run_log.source_count,
        "fetched_count": run_log.fetched_count,
        "filtered_count": run_log.filtered_count,
        "duplicate_count": run_log.duplicate_count,
        "failures": [dict(failure) for failure in run_log.failures],
    }


def issue_to_payload(issue: DigestIssue) -> dict[str, Any]:
    """Build the full ``*-candidates.json`` payload."""
    engineering = [candidate_to_dict(c) for c in issue.top_5_engineering_ai]
    return {
        "run_log": run_log_to_dict(issue.run_log),
        "selection_policy": dict(SELECTION_POLICY),
        "top_10_general_ai": [candidate_to_dict(c) for c in issue.top_10_general_ai],
        "top_5_engineering_ai": engineering,
        "top_5_medical_bio_ai": [
            candidate_to_dict(c) for c in issue.top_5_medical_bio_ai
        ],
        # Legacy alias kept for v1 consumers (report + site renderer).
        "top_5_cae_ai_engineering": engineering,
        "research_radar": [candidate_to_dict(c) for c in issue.research_radar],
        "supplemental_search_tasks": list(issue.supplemental_search_tasks),
        "watchlist_updates": list(issue.watchlist_updates),
        "top_100_news_candidates": [
            candidate_to_dict(c) for c in issue.top_100_news_candidates
        ],
    }


def write_candidates_json(issue: DigestIssue, path: Path) -> Path:
    """Write the issue artifact, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = issue_to_payload(issue)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote candidates artifact: %s", path)
    return path


def candidates_path(digest_dir: Path, date_slug: str) -> Path:
    """Artifact path for a run date (``YYYY-MM-DD-candidates.json``)."""
    return digest_dir / f"{date_slug}{CANDIDATES_SUFFIX}"


# --------------------------------------------------------------------------- #
# Historical dedup input
# --------------------------------------------------------------------------- #


def load_history(
    digest_dir: Path,
    date_slug: str,
    category: str,
    lookback_days: int,
) -> list[Candidate]:
    """Read previously *selected* items for one section (v1 parity).

    Only issues strictly older than ``date_slug`` and within
    ``lookback_days`` contribute.  Missing directories and unreadable or
    malformed artifacts are skipped, so a corrupt file can never block a
    run — it only weakens dedup for that day.
    """
    try:
        current = date.fromisoformat(date_slug)
    except ValueError:
        logger.warning("Invalid date slug for history lookup: %r", date_slug)
        return []

    section_keys = HISTORY_SECTION_KEYS.get(history_category(category), ())
    if not section_keys or not digest_dir.is_dir():
        return []

    history: list[Candidate] = []
    for path in sorted(digest_dir.glob(f"*{CANDIDATES_SUFFIX}"), reverse=True):
        previous_slug = path.name.removesuffix(CANDIDATES_SUFFIX)
        try:
            previous = date.fromisoformat(previous_slug)
        except ValueError:
            continue
        age = (current - previous).days
        if age <= 0 or age > lookback_days:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping unreadable history artifact %s: %s", path, exc)
            continue
        if not isinstance(payload, dict):
            continue
        for key in section_keys:
            for item in payload.get(key) or []:
                if isinstance(item, dict):
                    history.append(candidate_from_dict(item))

    logger.info(
        "Loaded %d historical items for %s (%dd lookback)",
        len(history),
        category,
        lookback_days,
    )
    return history


def history_category(category: str) -> str:
    """Map a section name onto its :data:`HISTORY_SECTION_KEYS` key.

    ``medical_bio_ai`` is a *section*, not a source category, and the legacy
    ``cae_ai_engineering`` name maps onto the engineering section.  Anything
    else — ``startup``, ``vendor``, ``community``, typos — maps to ``""`` and
    therefore to no history, matching v1's ``dict.get(category, ())``.
    """
    if category in HISTORY_SECTION_KEYS:
        return category
    alias = _HISTORY_ALIASES.get(category, "")
    return alias if alias in HISTORY_SECTION_KEYS else ""
