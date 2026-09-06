"""Topic diversification and section selection (Goal 6.5).

Turns a score-sorted candidate list into the four digest sections:

======================  ======  ===============  ==================
Section                 Limit   Per-topic cap    Per-source cap
======================  ======  ===============  ==================
General AI                10          2                 2
Engineering AI             5          2                 1
Biomedical AI              5          2                 —
Research Radar             5          2                 —
======================  ======  ===============  ==================

:func:`select_unique_events` walks four relaxation passes so a thin news day
still fills the section instead of returning two items, and a final fallback
drops the ``guo_yichen_reference`` preference when curated sources run out.
All rules are v1 parity — PROJECT.md §3.7–§3.8.

Note
----
The ``guo_yichen_reference`` and ``trusted_discovery`` source tags drive the
preference and trust gates.  The v2 registry (``config/config.toml``) does
not carry them yet, so today every General AI item arrives through the
no-preference fallback; see GOALS.md → Known gaps.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from attrs import frozen

from .category import canonical_category
from .dedup import is_same_event
from .fetchers import fetch_kind
from .models import Candidate

# --------------------------------------------------------------------------- #
# Section policy
# --------------------------------------------------------------------------- #

GENERAL_AI_LIMIT: int = 10
ENGINEERING_AI_LIMIT: int = 5
MEDICAL_BIO_AI_LIMIT: int = 5
RESEARCH_RADAR_LIMIT: int = 5

#: Days of published issues a section dedupes against (PROJECT.md §3.7).
GENERAL_AI_LOOKBACK_DAYS: int = 7
ENGINEERING_AI_LOOKBACK_DAYS: int = 30
MEDICAL_BIO_AI_LOOKBACK_DAYS: int = 30
RESEARCH_LOOKBACK_DAYS: int = 30

#: Maximum selected items sharing one topic key.
MAX_PER_TOPIC: int = 2

#: Categories whose selection requires trusted/curated sources in pass 1 and
#: whose broad Google News discoveries are capped.
TRUST_REQUIRED_CATEGORIES: frozenset[str] = frozenset({"general_ai", "engineering_ai"})

#: Per-section caps for broad Google News discoveries and per-source counts.
GENERAL_AI_GOOGLE_NEWS_CAP: int = 2
GENERAL_AI_MAX_PER_SOURCE: int = 2
ENGINEERING_AI_GOOGLE_NEWS_CAP: int = 1
ENGINEERING_AI_MAX_PER_SOURCE: int = 1
MEDICAL_BIO_GOOGLE_NEWS_CAP: int = 1

# --------------------------------------------------------------------------- #
# Source tags and kinds
# --------------------------------------------------------------------------- #

GUO_REFERENCE_TAG: str = "guo_yichen_reference"
TRUSTED_DISCOVERY_TAG: str = "trusted_discovery"
GOOGLE_NEWS_KIND: str = "google_news_rss"
GOOGLE_NEWS_NAME_PREFIX: str = "google news"
BROAD_GOOGLE_COUNTER_KEY: str = "broad_google_news"

# --------------------------------------------------------------------------- #
# Topic keys
# --------------------------------------------------------------------------- #


@frozen
class TopicRule:
    """One topic classification rule, evaluated in order.

    ``engineering_only`` rules apply solely to engineering-AI candidates —
    that is how ``cae_simulation`` stays out of the General AI topic space.
    """

    key: str
    terms: tuple[str, ...]
    engineering_only: bool = False


TOPIC_RULES: tuple[TopicRule, ...] = (
    TopicRule(
        key="payments_agent_commerce",
        terms=(
            "payment",
            "payments",
            "agentic commerce",
            "wallet",
            "checkout",
            "stablecoin",
            "micropayment",
        ),
    ),
    TopicRule(
        key="policy_safety_governance",
        terms=(
            "regulation",
            "policy",
            "law",
            "senate",
            "washington",
            "government",
            "safety",
            "data retention",
            "data terms",
        ),
    ),
    TopicRule(
        key="infrastructure_compute",
        terms=(
            "data center",
            "datacenter",
            "compute",
            "gpu",
            "chip",
            "nvidia",
            "oracle",
            "power grid",
            "energy",
        ),
    ),
    TopicRule(
        key="software_development",
        terms=(
            "coding",
            "developer",
            "software engineering",
            "ai-native development",
            "programming",
        ),
    ),
    TopicRule(
        key="health_bio",
        terms=(
            "health",
            "medical",
            "medicine",
            "clinical",
            "hospital",
            "drug discovery",
        ),
    ),
    TopicRule(
        key="robotics_autonomy",
        terms=("robot", "robotics", "autonomous vehicle", "drone"),
    ),
    TopicRule(
        key="frontier_models",
        terms=(
            "model",
            "claude",
            "chatgpt",
            "openai",
            "anthropic",
            "deepmind",
            "llm",
            "benchmark",
        ),
    ),
    TopicRule(
        key="cae_simulation",
        terms=(
            "cfd",
            "fea",
            "cae",
            "simulation",
            "surrogate",
            "digital twin",
            "neural operator",
        ),
        engineering_only=True,
    ),
)

FALLBACK_TOPIC: str = "other"

# --------------------------------------------------------------------------- #
# Biomedical detection (PROJECT.md §3.8)
# --------------------------------------------------------------------------- #

MEDICAL_PATTERNS: tuple[str, ...] = (
    r"\bhealthcare\b",
    r"\bmedical\b",
    r"\bmedicine\b",
    r"\bclinical\b",
    r"\bhospital\b",
    r"\bpatient\b",
    r"\bphysician\b",
    r"\bdrug discovery\b",
    r"\bdrug development\b",
    r"\bpharma\b",
    r"\bpharmaceutical\b",
    r"\bbiotech\b",
    r"\bbiomedical\b",
    r"\bbioinformatics\b",
    r"\bgenomics\b",
    r"\bgenomic\b",
    r"\bgenetics\b",
    r"\bgenetic\b",
    r"\bgene therapy\b",
    r"\bgene editing\b",
    r"\bcrispr\b",
    r"\bbiology\b",
    r"\bbiological\b",
    r"\blife sciences\b",
    r"\bbiomarker\b",
    r"\btherapeutic\b",
    r"\bdiagnostic\b",
)

_MEDICAL_REGEXES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern) for pattern in MEDICAL_PATTERNS
)

#: Categories eligible for the biomedical section (v1 parity).
MEDICAL_ELIGIBLE_CATEGORIES: frozenset[str] = frozenset({"general_ai", "research"})

# --------------------------------------------------------------------------- #
# Engineering exclusion list (PROJECT.md §5.6)
# --------------------------------------------------------------------------- #

#: Finance/SEO noise that must never surface in the Engineering AI section.
#: v1 applies this at render time as a second net behind the keyword
#: ``exclude`` list, so it is *not* applied during selection — the candidates
#: artifact must stay comparable with v1's.
ENGINEERING_EXCLUDED_TERMS: frozenset[str] = frozenset(
    {
        "analysts offer insights",
        "industrial goods companies",
        "tsx:cae",
        "forex.com",
        "ai index cfd",
        "capital.com",
        "tradingview",
        "finance magnates",
        "traders",
        "trading",
        "brokers",
        "cfd access",
        "surrogate model virus",
        "chatbots in a simulation",
    }
)


# --------------------------------------------------------------------------- #
# Candidate predicates
# --------------------------------------------------------------------------- #


def topic_key(candidate: Candidate) -> str:
    """Classify a candidate into a diversification topic.

    Rules are evaluated in order over ``"{title} {text}"``; the first hit
    wins, so ``payments_agent_commerce`` beats ``frontier_models`` for a
    story about ChatGPT payments.
    """
    haystack = f"{candidate.title} {candidate.text}".lower()
    is_engineering = canonical_category(candidate.category) == "engineering_ai"
    for rule in TOPIC_RULES:
        if rule.engineering_only and not is_engineering:
            continue
        if any(term in haystack for term in rule.terms):
            return rule.key
    return FALLBACK_TOPIC


def is_medical_bio_ai(candidate: Candidate) -> bool:
    """Whether the candidate belongs in the biomedical section.

    Word-boundary regexes over title + text + source tags, so "genomic"
    matches but "genomicsoftware" does not.
    """
    haystack = " ".join(
        (candidate.title, candidate.text, *candidate.source.tags)
    ).lower()
    return any(pattern.search(haystack) for pattern in _MEDICAL_REGEXES)


def is_excluded_from_engineering(candidate: Candidate) -> bool:
    """Render-time guard against finance/SEO noise (PROJECT.md §5.6)."""
    haystack = f"{candidate.title} {candidate.text}".lower()
    return any(term in haystack for term in ENGINEERING_EXCLUDED_TERMS)


def source_kind(candidate: Candidate) -> str:
    """Resolved fetch kind — v1 stored it on the candidate as ``source_kind``."""
    return fetch_kind(candidate.source)


def is_trusted_or_curated(candidate: Candidate) -> bool:
    """Everything except broad Google News discovery counts as curated."""
    tags = set(candidate.source.tags)
    return source_kind(candidate) != GOOGLE_NEWS_KIND or TRUSTED_DISCOVERY_TAG in tags


def is_broad_google_discovery(candidate: Candidate) -> bool:
    """An untagged Google News search result — capped per section."""
    return (
        source_kind(candidate) == GOOGLE_NEWS_KIND
        and candidate.source.name.lower().startswith(GOOGLE_NEWS_NAME_PREFIX)
        and TRUSTED_DISCOVERY_TAG not in set(candidate.source.tags)
    )


def is_guo_yichen_reference(candidate: Candidate) -> bool:
    """Whether the source is one of the preferred reference outlets."""
    return GUO_REFERENCE_TAG in set(candidate.source.tags)


def selection_category_matches(candidate: Candidate, category: str) -> bool:
    """Whether a candidate is eligible for a section.

    General AI also accepts research items from preferred reference sources,
    which is how arXiv-adjacent stories reach the Top 10 (v1 parity).
    """
    candidate_category = canonical_category(candidate.category)
    if canonical_category(category) == "general_ai":
        return candidate_category == "general_ai" or (
            candidate_category == "research" and is_guo_yichen_reference(candidate)
        )
    return candidate_category == canonical_category(category)


def is_historical_repeat(
    candidate: Candidate, historical_items: Sequence[Candidate]
) -> bool:
    """Whether the candidate repeats an already-published story."""
    return any(is_same_event(candidate, previous) for previous in historical_items)


# --------------------------------------------------------------------------- #
# Selection bookkeeping
# --------------------------------------------------------------------------- #


@frozen
class _PassPolicy:
    """Which constraints one relaxation pass enforces.

    The four passes used by :func:`select_unique_events`, in order:

    1. trusted sources only, topic cap, source cap
    2. any source, topic cap, source cap, Google News cap
    3. any source, source cap, Google News cap — topic cap relaxed
    4. any source, topic cap, Google News cap — source cap relaxed for
       categories outside :data:`TRUST_REQUIRED_CATEGORIES`
    """

    require_trusted: bool
    enforce_topic_cap: bool
    enforce_source_cap_for_all: bool


_RELAXATION_PASSES: tuple[_PassPolicy, ...] = (
    _PassPolicy(
        require_trusted=True,
        enforce_topic_cap=True,
        enforce_source_cap_for_all=True,
    ),
    _PassPolicy(
        require_trusted=False,
        enforce_topic_cap=True,
        enforce_source_cap_for_all=True,
    ),
    _PassPolicy(
        require_trusted=False,
        enforce_topic_cap=False,
        enforce_source_cap_for_all=True,
    ),
    _PassPolicy(
        require_trusted=False,
        enforce_topic_cap=True,
        enforce_source_cap_for_all=False,
    ),
)


class _SelectionState:
    """Mutable counters shared by every pass of one selection run."""

    def __init__(self, limit: int, google_news_cap: int, max_per_source: int) -> None:
        self.limit = limit
        self.google_news_cap = google_news_cap
        self.max_per_source = max_per_source
        self.selected: list[Candidate] = []
        self.topic_counts: dict[str, int] = {}
        self.source_counts: dict[str, int] = {}
        self.broad_google_count = 0

    @property
    def full(self) -> bool:
        return len(self.selected) >= self.limit

    def topic_blocked(self, topic: str) -> bool:
        return self.topic_counts.get(topic, 0) >= MAX_PER_TOPIC

    def source_blocked(self, name: str) -> bool:
        return self.source_counts.get(name, 0) >= self.max_per_source

    def google_blocked(self) -> bool:
        return self.broad_google_count >= self.google_news_cap

    def duplicates(self, candidate: Candidate) -> bool:
        """Already selected, either identically or as the same event."""
        return candidate in self.selected or any(
            is_same_event(candidate, existing) for existing in self.selected
        )

    def record(self, candidate: Candidate, topic: str, *, count_topic: bool) -> None:
        self.selected.append(candidate)
        if count_topic:
            self.topic_counts[topic] = self.topic_counts.get(topic, 0) + 1
        name = candidate.source.name
        self.source_counts[name] = self.source_counts.get(name, 0) + 1
        if is_broad_google_discovery(candidate):
            self.broad_google_count += 1


def _caps_for(category: str, limit: int) -> tuple[int, int]:
    """Return ``(google_news_cap, max_per_source)`` for a section."""
    if category == "general_ai":
        return GENERAL_AI_GOOGLE_NEWS_CAP, GENERAL_AI_MAX_PER_SOURCE
    if category == "engineering_ai":
        return ENGINEERING_AI_GOOGLE_NEWS_CAP, ENGINEERING_AI_MAX_PER_SOURCE
    return limit, limit


def _run_pass(
    candidates: Sequence[Candidate],
    *,
    category: str,
    history: Sequence[Candidate],
    require_guo: bool,
    policy: _PassPolicy,
    state: _SelectionState,
) -> None:
    """Append candidates to ``state`` under one pass's constraints."""
    trust_gated = category in TRUST_REQUIRED_CATEGORIES
    for candidate in candidates:
        if state.full:
            return
        if not selection_category_matches(candidate, category):
            continue
        if (
            policy.require_trusted
            and trust_gated
            and not is_trusted_or_curated(candidate)
        ):
            continue
        if (
            category == "general_ai"
            and require_guo
            and not is_guo_yichen_reference(candidate)
        ):
            continue
        if is_historical_repeat(candidate, history):
            continue
        if (
            trust_gated
            and is_broad_google_discovery(candidate)
            and state.google_blocked()
        ):
            continue
        if policy.enforce_source_cap_for_all or trust_gated:
            if state.source_blocked(candidate.source.name):
                continue
        if state.duplicates(candidate):
            continue
        topic = topic_key(candidate)
        if policy.enforce_topic_cap and state.topic_blocked(topic):
            continue
        state.record(candidate, topic, count_topic=policy.enforce_topic_cap)


# --------------------------------------------------------------------------- #
# Public selection API
# --------------------------------------------------------------------------- #


def select_unique_events(
    candidates: Sequence[Candidate],
    category: str,
    limit: int,
    historical_items: Sequence[Candidate] | None = None,
    require_guo_general: bool = True,
) -> list[Candidate]:
    """Select up to ``limit`` distinct events for one section.

    ``candidates`` must already be sorted by score descending — selection
    preserves that order and never re-ranks.

    Four relaxation passes run in sequence (see :class:`_PassPolicy`); if a
    General AI section is still short and the preferred-source requirement
    was on, the whole selection reruns without it and the extra items are
    appended.
    """
    canonical = canonical_category(category)
    history = historical_items or []
    google_news_cap, max_per_source = _caps_for(canonical, limit)
    state = _SelectionState(limit, google_news_cap, max_per_source)

    for policy in _RELAXATION_PASSES:
        if state.full:
            break
        _run_pass(
            candidates,
            category=canonical,
            history=history,
            require_guo=require_guo_general,
            policy=policy,
            state=state,
        )

    if canonical == "general_ai" and require_guo_general and not state.full:
        expanded = select_unique_events(
            candidates,
            canonical,
            limit,
            history,
            require_guo_general=False,
        )
        for candidate in expanded:
            if state.full:
                break
            if any(is_same_event(candidate, existing) for existing in state.selected):
                continue
            state.selected.append(candidate)

    return state.selected


def select_medical_bio_ai(
    candidates: Sequence[Candidate],
    limit: int = MEDICAL_BIO_AI_LIMIT,
    historical_items: Sequence[Candidate] | None = None,
) -> list[Candidate]:
    """Select the biomedical section (v1 ``select_medical_bio_ai``).

    Two passes: trusted/curated sources with a topic cap first, then any
    source with a single-slot cap on broad Google News discovery.  Only
    ``general_ai`` and ``research`` candidates are eligible — engineering
    items stay in their own section.
    """
    history = historical_items or []
    state = _SelectionState(limit, MEDICAL_BIO_GOOGLE_NEWS_CAP, limit)

    for enforce_trusted, enforce_topic_cap in ((True, True), (False, False)):
        for candidate in candidates:
            if state.full:
                break
            if (
                canonical_category(candidate.category)
                not in MEDICAL_ELIGIBLE_CATEGORIES
            ):
                continue
            if not is_medical_bio_ai(candidate):
                continue
            if enforce_trusted and not is_trusted_or_curated(candidate):
                continue
            if (
                not enforce_trusted
                and is_broad_google_discovery(candidate)
                and state.google_blocked()
            ):
                continue
            if is_historical_repeat(candidate, history):
                continue
            if state.duplicates(candidate):
                continue
            topic = topic_key(candidate)
            if enforce_topic_cap and state.topic_blocked(topic):
                continue
            state.record(candidate, topic, count_topic=enforce_topic_cap)

    return state.selected
