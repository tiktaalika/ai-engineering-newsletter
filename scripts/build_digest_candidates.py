#!/usr/bin/env python3
"""Build auditable daily AI news candidates.

The script intentionally separates evidence collection from summarization.
It fetches configured public sources, filters for English AI/Engineering AI relevance,
scores visible popularity signals, and writes JSON artifacts that a daily
agent can inspect before producing the Chinese digest.
"""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "news-push-ai-digest/0.1 (+auditable personal digest)"
MAX_ITEMS_PER_SOURCE = 25
MAX_CANDIDATES_TOTAL = 100
COMMON_EVENT_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "its",
    "new",
    "of",
    "on",
    "or",
    "s",
    "says",
    "the",
    "to",
    "with",
    "report",
    "reports",
    "reported",
    "exclusive",
    "breaking",
    "news",
    "via",
}
SOURCE_SUFFIXES = {
    "reuters",
    "bbc",
    "cnbc",
    "forbes",
    "techcrunch",
    "bloomberg",
    "wsj",
    "financial",
    "times",
    "guardian",
    "yahoo",
    "finance",
    "ap",
    "axios",
    "nytimes",
    "meta",
    "openai",
}


@dataclass
class Candidate:
    id: str
    title: str
    url: str
    source: str
    source_kind: str
    category: str
    published_at: str | None
    text: str
    matched_terms: list[str]
    engagement: dict[str, float | int | None]
    score: float
    score_reasons: list[str]
    general_ai_score: float = 0.0
    engineering_relevance_score: float = 0.0
    research_relevance_score: float = 0.0
    novelty_score: float = 0.0
    source_priority_score: float = 0.0
    source_tags: list[str] = field(default_factory=list)
    registry_category: str = ""
    source_priority: str = "medium"


@dataclass
class RunLog:
    generated_at: str
    window_hours: int
    source_count: int
    fetched_count: int = 0
    filtered_count: int = 0
    duplicate_count: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def canonical_category(category: str) -> str:
    if category in {"engineering_ai", "cae_ai_engineering"}:
        return "engineering_ai"
    if category in {"research", "startup", "vendor", "community"}:
        return category
    return "general_ai"


def keyword_bucket_name(category: str) -> str:
    if canonical_category(category) == "engineering_ai":
        return "cae_ai_engineering"
    return "general_ai"


def fetch_kind(source: dict[str, Any]) -> str:
    if source.get("fetch_type"):
        return source["fetch_type"]
    source_type = source.get("source_type") or source.get("kind")
    if source_type == "rss":
        return "rss"
    if source_type in {"manual", "website", "newsletter", "linkedin_manual", "x_api", "github", "arxiv"}:
        return "web_search_query"
    return source_type or "web_search_query"


def source_priority_score(source: dict[str, Any], priority_scores: dict[str, float]) -> float:
    return float(priority_scores.get(source.get("priority", "medium"), 0.65))


def load_source_registry() -> dict[str, Any]:
    yaml_path = ROOT / "config" / "sources.yaml"
    if yaml_path.exists():
        registry = load_yaml(yaml_path)
        registry["sources"] = [normalize_source(item) for item in registry.get("sources", []) if item.get("enabled", True)]
        return registry

    legacy = load_json(ROOT / "config" / "sources.json")
    priority_scores = {
        "high": 1.0,
        "medium": 0.65,
        "low": 0.35,
    }
    reach_to_priority = {
        "tier_1_global": "high",
        "tier_2_tech": "high",
        "company_blog": "medium",
        "research_lab": "medium",
        "community": "low",
        "cae_industry": "medium",
        "linkedin_public": "low",
        "curated_newsletter": "medium",
    }
    sources = []
    for source in legacy.get("sources", []):
        item = dict(source)
        item["source_type"] = source.get("kind", "manual")
        item["fetch_type"] = source.get("kind", "web_search_query")
        item["priority"] = reach_to_priority.get(source.get("reach"), "medium")
        item["tags"] = []
        item["notes"] = "Migrated from legacy sources.json"
        item["enabled"] = True
        item["category"] = "engineering_ai" if source.get("category") == "cae_ai_engineering" else source.get("category", "general_ai")
        sources.append(normalize_source(item))
    return {
        "source_priority_scores": priority_scores,
        "category_window_hours": {
            "general_ai": legacy.get("category_window_hours", {}).get("general_ai", 24),
            "engineering_ai": legacy.get("category_window_hours", {}).get("cae_ai_engineering", 720),
        },
        "sources": sources,
    }


def normalize_source(source: dict[str, Any]) -> dict[str, Any]:
    item = dict(source)
    item["category"] = canonical_category(item.get("category", "general_ai"))
    item["kind"] = fetch_kind(item)
    item["source_type"] = item.get("source_type") or item["kind"]
    item["priority"] = item.get("priority", "medium")
    item["tags"] = item.get("tags") or []
    if item["kind"] == "web_search_query" and not item.get("query"):
        item["query"] = f'site:{urllib.parse.urlsplit(item.get("url", "")).netloc} AI'
    return item


def fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=12) as response:
        return response.read().decode("utf-8", "replace")


def clean_text(value: str | None) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def iso_or_none(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def entry_id(url: str, title: str) -> str:
    raw = (url or title).lower().encode("utf-8", "replace")
    return hashlib.sha1(raw).hexdigest()[:16]


def event_tokens(title: str) -> set[str]:
    title = re.sub(r"\s+-\s+[^-]+$", "", title.lower())
    tokens = re.findall(r"[a-z0-9]+", title)
    return {
        token
        for token in tokens
        if len(token) > 2 and token not in COMMON_EVENT_WORDS and token not in SOURCE_SUFFIXES
    }


def canonical_event_key(title: str) -> str | None:
    text = title.lower()
    if "openai" in text and any(term in text for term in ("ipo", "initial public", "go public", "public offering", "stock market", "s-1", "sec")):
        return "openai-ipo"
    if "openai" in text and any(term in text for term in ("price cut", "price cuts", "slashing prices", "drastic price")) and "anthropic" in text:
        return "openai-anthropic-price-war"
    if "visa" in text and any(term in text for term in ("openai", "chatgpt")) and any(term in text for term in ("payment", "payments", "agentic commerce", "ai agent")):
        return "visa-openai-agent-payments"
    if "mastercard" in text and any(term in text for term in ("ai agent", "agent payments", "agentic commerce", "micropayments", "machine-to-machine", "coinbase", "ripple", "onchain")):
        return "mastercard-ai-agent-payments"
    if "microsoft" in text and "claude" in text and any(term in text for term in ("fable", "employee access", "data retention", "data terms", "restricts", "limited")):
        return "microsoft-claude-fable-access"
    if "anthropic" in text and any(term in text for term in ("regulation", "government", "block dangerous", "stronger regulation")):
        return "anthropic-regulation-call"
    if "anthropic" in text and any(term in text for term in ("walks back", "backlash", "restrictions", "sabotaged")):
        return "anthropic-model-restrictions-backlash"
    if "anthropic" in text and any(term in text for term in ("export control", "foreign access", "government order", "taken offline", "shuts down", "suspended", "security fears", "pulled the plug")):
        return "anthropic-export-controls-model-access"
    if "apple" in text and "siri" in text:
        return "apple-siri-ai"
    if "openai" in text and "data center" in text and any(term in text for term in ("ohio", "gigawatt", "nvidia")):
        return "openai-ohio-data-center"
    if "meta" in text and "reliance" in text and "data center" in text:
        return "meta-reliance-india-data-center"
    if "thea energy" in text and any(term in text for term in ("helios", "fusion", "surrogate", "digital twin")):
        return "thea-energy-fusion-digital-twin"
    if "synera" in text and "nvidia" in text and any(term in text for term in ("engineering simulation", "design")):
        return "synera-nvidia-engineering-agents"
    if "simcenter physicsai" in text and "cfd" in text:
        return "siemens-simcenter-physicsai-cfd"
    return None


def is_same_event(left: Candidate, right: Candidate) -> bool:
    left_key = canonical_event_key(left.title)
    right_key = canonical_event_key(right.title)
    if left_key and left_key == right_key:
        return True
    left_tokens = event_tokens(left.title)
    right_tokens = event_tokens(right.title)
    if not left_tokens or not right_tokens:
        return False
    intersection = left_tokens & right_tokens
    smaller = min(len(left_tokens), len(right_tokens))
    union = left_tokens | right_tokens
    if len(intersection) >= 5 and len(intersection) / max(smaller, 1) >= 0.5:
        return True
    if len(intersection) >= 4 and len(intersection) / max(len(union), 1) >= 0.42:
        return True
    return False


def topic_key(candidate: Candidate) -> str:
    text = f"{candidate.title} {candidate.text}".lower()
    if any(term in text for term in ("payment", "payments", "agentic commerce", "wallet", "checkout", "stablecoin", "micropayment")):
        return "payments_agent_commerce"
    if any(term in text for term in ("regulation", "policy", "law", "senate", "washington", "government", "safety", "data retention", "data terms")):
        return "policy_safety_governance"
    if any(term in text for term in ("data center", "datacenter", "compute", "gpu", "chip", "nvidia", "oracle", "power grid", "energy")):
        return "infrastructure_compute"
    if any(term in text for term in ("coding", "developer", "software engineering", "ai-native development", "programming")):
        return "software_development"
    if any(term in text for term in ("health", "medical", "medicine", "clinical", "hospital", "drug discovery")):
        return "health_bio"
    if any(term in text for term in ("robot", "robotics", "autonomous vehicle", "drone")):
        return "robotics_autonomy"
    if any(term in text for term in ("model", "claude", "chatgpt", "openai", "anthropic", "deepmind", "llm", "benchmark")):
        return "frontier_models"
    if candidate.category in {"engineering_ai", "cae_ai_engineering"}:
        if any(term in text for term in ("cfd", "fea", "cae", "simulation", "surrogate", "digital twin", "neural operator")):
            return "cae_simulation"
    return "other"


def is_medical_bio_ai(candidate: Candidate) -> bool:
    text = f"{candidate.title} {candidate.text} {' '.join(candidate.source_tags)}".lower()
    medical_patterns = (
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
    return any(re.search(pattern, text) for pattern in medical_patterns)


def select_unique_events(candidates: list[Candidate], category: str, limit: int) -> list[Candidate]:
    category = canonical_category(category)
    max_per_topic = 2
    selected: list[Candidate] = []
    topic_counts: dict[str, int] = {}
    for candidate in candidates:
        if canonical_category(candidate.category) != category:
            continue
        if any(is_same_event(candidate, existing) for existing in selected):
            continue
        topic = topic_key(candidate)
        if topic_counts.get(topic, 0) >= max_per_topic:
            continue
        selected.append(candidate)
        topic_counts[topic] = topic_counts.get(topic, 0) + 1
        if len(selected) == limit:
            break
    for candidate in candidates:
        if len(selected) == limit:
            break
        if canonical_category(candidate.category) != category:
            continue
        if candidate in selected or any(is_same_event(candidate, existing) for existing in selected):
            continue
        selected.append(candidate)
    return selected


def select_medical_bio_ai(candidates: list[Candidate], limit: int) -> list[Candidate]:
    selected: list[Candidate] = []
    topic_counts: dict[str, int] = {}
    for candidate in candidates:
        if canonical_category(candidate.category) not in {"general_ai", "research"}:
            continue
        if not is_medical_bio_ai(candidate):
            continue
        if any(is_same_event(candidate, existing) for existing in selected):
            continue
        topic = topic_key(candidate)
        if topic_counts.get(topic, 0) >= 2:
            continue
        selected.append(candidate)
        topic_counts[topic] = topic_counts.get(topic, 0) + 1
        if len(selected) == limit:
            break
    for candidate in candidates:
        if len(selected) == limit:
            break
        if canonical_category(candidate.category) not in {"general_ai", "research"}:
            continue
        if not is_medical_bio_ai(candidate):
            continue
        if candidate in selected or any(is_same_event(candidate, existing) for existing in selected):
            continue
        selected.append(candidate)
    return selected


def norm_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    kept = [(k, v) for k, v in query if not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), urllib.parse.urlencode(kept), "")
    )


def language_looks_english(text: str) -> bool:
    letters = re.findall(r"[A-Za-z]", text)
    if len(letters) < 20:
        return False
    ascii_ratio = sum(1 for ch in text if ord(ch) < 128) / max(len(text), 1)
    return ascii_ratio > 0.82


def matched_terms(text: str, include: list[str], exclude: list[str]) -> tuple[list[str], bool]:
    haystack = text.lower()
    blocked = [term for term in exclude if term.lower() in haystack]
    if blocked:
        return [], False
    matches = [term for term in include if term.lower() in haystack]
    return matches, bool(matches)


def matches_core_terms(text: str, core_include: list[str] | None) -> bool:
    if not core_include:
        return True
    haystack = text.lower()
    return any(term.lower() in haystack for term in core_include)


def recency_boost(published_at: datetime | None, now: datetime, window_hours: int) -> float:
    if not published_at:
        return 0.35
    age_hours = max((now - published_at).total_seconds() / 3600, 0)
    if age_hours > window_hours:
        return 0.0
    return max(0.15, 1.0 - (age_hours / window_hours) * 0.75)


def log_scale(value: float | int | None, cap: float) -> float:
    if not value or value <= 0:
        return 0.0
    return min(math.log1p(float(value)) / math.log1p(cap), 1.0)


def score_candidate(
    source: dict[str, Any],
    engagement: dict[str, float | int | None],
    matches: list[str],
    published_at: datetime | None,
    now: datetime,
    window_hours: int,
    priority_scores: dict[str, float],
    text: str,
) -> tuple[float, list[str], dict[str, float]]:
    priority = source_priority_score(source, priority_scores)
    novelty = recency_boost(published_at, now, window_hours)
    points = engagement.get("points")
    comments = engagement.get("comments")
    upvotes = engagement.get("upvotes")
    lower = text.lower()
    general_relevance = min(len(matches) / 6, 1.0)
    engineering_terms = (
        "cae", "computer-aided engineering", "engineering simulation", "simulation", "cad",
        "spdm", "plm", "digital twin", "physical ai", "scientific ml", "industrial ai",
        "cfd", "fea", "surrogate", "neural operator", "physics-informed",
    )
    workflow_ai_terms = (
        "agentic ai", "ai agent", "agents", "llm", "natural language", "post-processing",
        "result browser", "report template", "code generation", "sandboxed environment",
        "simulation workflow", "simulation automation", "plot agent", "variable metadata",
    )
    research_terms = (
        "arxiv", "paper", "research", "benchmark", "dataset", "model release", "nature",
        "science robotics", "papers with code", "hugging face papers",
    )
    engineering_relevance = 1.0 if source["category"] == "engineering_ai" else min(sum(1 for term in engineering_terms if term in lower) / 4, 1.0)
    research_relevance = 1.0 if source["category"] == "research" else min(sum(1 for term in research_terms if term in lower) / 3, 1.0)
    engineering_workflow_ai = (
        canonical_category(source["category"]) == "engineering_ai"
        and any(term in lower for term in workflow_ai_terms)
        and any(term in lower for term in ("simulation", "cae", "simcenter", "amesim", "cfd", "fea", "digital twin"))
    )
    score = 0.0
    score += 32 * priority
    score += 22 * novelty
    score += 20 * general_relevance
    score += 14 * engineering_relevance
    score += 8 * research_relevance
    if engineering_workflow_ai:
        score += 10
    score += 14 * log_scale(points, 1200)
    score += 10 * log_scale(comments, 800)
    score += 10 * log_scale(upvotes, 5000)
    reasons = [
        f"source_priority={priority:.2f}",
        f"novelty={novelty:.2f}",
        f"matched_terms={len(matches)}",
        f"engineering_relevance={engineering_relevance:.2f}",
        f"research_relevance={research_relevance:.2f}",
    ]
    if engineering_workflow_ai:
        reasons.append("engineering_workflow_ai_boost=10")
    visible = {k: v for k, v in engagement.items() if v}
    if visible:
        reasons.append(f"visible_engagement={visible}")
    else:
        reasons.append("visible_engagement=unavailable")
    return round(score, 3), reasons, {
        "general_ai_score": round(general_relevance, 3),
        "engineering_relevance_score": round(engineering_relevance, 3),
        "research_relevance_score": round(research_relevance, 3),
        "novelty_score": round(novelty, 3),
        "source_priority_score": round(priority, 3),
    }


def parse_rss(source: dict[str, Any]) -> list[dict[str, Any]]:
    raw = fetch_text(source["url"])
    raw = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)", "&amp;", raw)
    root = ET.fromstring(raw)
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    records = []
    for item in items:
        get = lambda name: item.findtext(name) or item.findtext(f"{{http://www.w3.org/2005/Atom}}{name}")
        title = clean_text(get("title"))
        link = clean_text(get("link"))
        if not link:
            link_el = item.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.attrib.get("href", "") if link_el is not None else ""
        summary = clean_text(get("description") or get("summary") or get("content"))
        published = get("pubDate") or get("published") or get("updated")
        records.append(
            {
                "title": title,
                "url": link,
                "published_at": parse_datetime(published),
                "text": f"{title} {summary}",
                "engagement": {},
            }
        )
    return records


def parse_hn(source: dict[str, Any], keywords: dict[str, Any], window_hours: int) -> list[dict[str, Any]]:
    terms = keywords["general_ai"]["include"][:18]
    query = " OR ".join(terms)
    cutoff = int(time.time() - window_hours * 3600)
    params = urllib.parse.urlencode({"query": query, "tags": "story", "numericFilters": f"created_at_i>{cutoff}"})
    payload = fetch_json(f"{source['url']}?{params}")
    records = []
    for hit in payload.get("hits", []):
        title = clean_text(hit.get("title") or hit.get("story_title"))
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        created = parse_datetime(hit.get("created_at"))
        records.append(
            {
                "title": title,
                "url": url,
                "published_at": created,
                "text": title,
                "engagement": {"points": hit.get("points"), "comments": hit.get("num_comments")},
            }
        )
    return records


def parse_reddit(source: dict[str, Any]) -> list[dict[str, Any]]:
    payload = fetch_json(source["url"])
    records = []
    for child in payload.get("data", {}).get("children", []):
        data = child.get("data", {})
        title = clean_text(data.get("title"))
        url = data.get("url") or f"https://reddit.com{data.get('permalink', '')}"
        created = datetime.fromtimestamp(data.get("created_utc", 0), tz=timezone.utc)
        records.append(
            {
                "title": title,
                "url": url,
                "published_at": created,
                "text": f"{title} {clean_text(data.get('selftext'))}",
                "engagement": {"upvotes": data.get("ups"), "comments": data.get("num_comments")},
            }
        )
    return records


def web_search_placeholder(source: dict[str, Any]) -> list[dict[str, Any]]:
    query = urllib.parse.quote(source["query"])
    return [
        {
            "title": f"Manual/search source: {source['name']}",
            "url": f"https://www.google.com/search?q={query}",
            "published_at": None,
            "text": source["query"],
            "engagement": {},
            "manual_search": True,
        }
    ]


def fetch_source(source: dict[str, Any], keywords: dict[str, Any], window_hours: int) -> list[dict[str, Any]]:
    kind = source["kind"]
    if kind == "rss":
        return parse_rss(source)[:MAX_ITEMS_PER_SOURCE]
    if kind == "google_news_rss":
        query = urllib.parse.quote(source["query"])
        rss_source = dict(source)
        rss_source["url"] = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        return parse_rss(rss_source)[:MAX_ITEMS_PER_SOURCE]
    if kind == "hn_algolia":
        return parse_hn(source, keywords, window_hours)[:MAX_ITEMS_PER_SOURCE]
    if kind == "reddit_json":
        return parse_reddit(source)[:MAX_ITEMS_PER_SOURCE]
    if kind == "web_search_query":
        return web_search_placeholder(source)[:MAX_ITEMS_PER_SOURCE]
    raise ValueError(f"unsupported source kind: {kind}")


def build_candidates(args: argparse.Namespace) -> tuple[list[Candidate], RunLog, list[dict[str, str]]]:
    now = datetime.now(timezone.utc)
    sources_config = load_source_registry()
    keywords = load_json(ROOT / "config" / "keywords.json")
    priority_scores = sources_config.get("source_priority_scores", {"high": 1.0, "medium": 0.65, "low": 0.35})
    category_window_hours = sources_config.get("category_window_hours", {})
    sources = sources_config["sources"]
    log = RunLog(now.isoformat(), args.window_hours, len(sources))
    seen: set[str] = set()
    candidates: list[Candidate] = []
    search_tasks: list[dict[str, str]] = []

    for source in sources:
        source_category = canonical_category(source["category"])
        source_window_hours = int(category_window_hours.get(source_category, args.window_hours))
        try:
            records = fetch_source(source, keywords, source_window_hours)
            log.fetched_count += len(records)
        except Exception as exc:  # noqa: BLE001 - log source failure and continue.
            log.failures.append({"source": source["name"], "error": str(exc)})
            continue

        for record in records:
            if record.get("manual_search"):
                search_tasks.append(
                    {
                        "source": source["name"],
                        "category": source_category,
                        "query": source["query"],
                        "url": record["url"],
                        "source_type": source.get("source_type", "manual"),
                        "priority": source.get("priority", "medium"),
                        "tags": ", ".join(source.get("tags", [])),
                        "note": "Use as a watchlist/manual review task; do not rank the placeholder as a news item.",
                    }
                )
                continue
            title = clean_text(record.get("title"))
            url = norm_url(record.get("url") or "")
            text = clean_text(record.get("text") or title)
            published_at = record.get("published_at")
            source_cutoff = now - timedelta(hours=source_window_hours)
            if published_at and published_at < source_cutoff:
                continue
            if not title or not url or not language_looks_english(f"{title} {text}"):
                continue
            bucket = keywords[keyword_bucket_name(source_category)]
            matches, ok = matched_terms(f"{title} {text}", bucket["include"], bucket["exclude"])
            if not ok:
                continue
            if not matches_core_terms(f"{title} {text}", bucket.get("core_include")):
                continue
            if not matches_core_terms(f"{title} {text}", bucket.get("ai_include")):
                continue
            unique_key = norm_url(url) or title.lower()
            if unique_key in seen:
                log.duplicate_count += 1
                continue
            seen.add(unique_key)
            score, reasons, score_parts = score_candidate(
                source,
                record.get("engagement", {}),
                matches,
                published_at,
                now,
                source_window_hours,
                priority_scores,
                f"{title} {text}",
            )
            log.filtered_count += 1
            candidates.append(
                Candidate(
                    id=entry_id(url, title),
                    title=title,
                    url=url,
                    source=source["name"],
                    source_kind=source["kind"],
                    category="engineering_ai" if source_category == "engineering_ai" else ("research" if source_category == "research" else "general_ai"),
                    published_at=iso_or_none(published_at),
                    text=text[:1200],
                    matched_terms=matches,
                    engagement=record.get("engagement", {}),
                    score=score,
                    score_reasons=reasons,
                    general_ai_score=score_parts["general_ai_score"],
                    engineering_relevance_score=score_parts["engineering_relevance_score"],
                    research_relevance_score=score_parts["research_relevance_score"],
                    novelty_score=score_parts["novelty_score"],
                    source_priority_score=score_parts["source_priority_score"],
                    source_tags=source.get("tags", []),
                    registry_category=source_category,
                    source_priority=source.get("priority", "medium"),
                )
            )

    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates, log, search_tasks


def write_outputs(candidates: list[Candidate], log: RunLog, search_tasks: list[dict[str, str]], date_slug: str) -> None:
    logs_dir = ROOT / "data" / "logs"
    digest_dir = ROOT / "data" / "digests"
    logs_dir.mkdir(parents=True, exist_ok=True)
    digest_dir.mkdir(parents=True, exist_ok=True)

    all_candidates = [asdict(item) for item in candidates[:100]]
    general_top = [asdict(item) for item in select_unique_events(candidates, "general_ai", 10)]
    engineering_top = [asdict(item) for item in select_unique_events(candidates, "engineering_ai", 5)]
    medical_bio_top = [asdict(item) for item in select_medical_bio_ai(candidates, 5)]
    research_radar = [asdict(item) for item in select_unique_events(candidates, "research", 5)]
    payload = {
        "run_log": asdict(log),
        "selection_policy": {
            "general_ai": "top 10 scored English AI news items after event deduplication and topic diversification",
            "engineering_ai": "top 5 scored engineering AI items covering simulation, CAD, CAE, SPDM, PLM, digital twin, physical AI, scientific ML, and industrial AI",
            "medical_bio_ai": "top 5 scored medical, medicine, biotech, biology, genomics, and genetics AI items after event deduplication and topic diversification",
            "research_radar": "optional research items from research/community sources",
            "ranking_note": "Score estimates readership/engagement when direct read counts are unavailable. Selection prefers topic diversity so one hot area does not crowd out the whole digest.",
        },
        "top_10_general_ai": general_top,
        "top_5_engineering_ai": engineering_top,
        "top_5_medical_bio_ai": medical_bio_top,
        "top_5_cae_ai_engineering": engineering_top,
        "research_radar": research_radar,
        "supplemental_search_tasks": search_tasks,
        "watchlist_updates": search_tasks,
        "top_100_news_candidates": all_candidates,
    }
    out_json = digest_dir / f"{date_slug}-candidates.json"
    out_md = digest_dir / f"{date_slug}-briefing-input.md"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# AI Engineering Newsletter - {date_slug}",
        "",
        "Use this file as briefing input. Produce Chinese headline, five-sentence Chinese summary, original link, Chinese translation, and Why It Matters for each selected item.",
        "",
        "## Run Log",
        f"- fetched_count: {log.fetched_count}",
        f"- filtered_count: {log.filtered_count}",
        f"- duplicate_count: {log.duplicate_count}",
        f"- failures: {len(log.failures)}",
        "",
        "## Top 10 General AI News",
    ]
    for idx, item in enumerate(general_top, 1):
        lines.extend(
            [
                f"{idx}. [{item['title']}]({item['url']})",
                f"   - source: {item['source']}",
                f"   - score: {item['score']}",
                f"   - score_breakdown: general={item['general_ai_score']}; engineering={item['engineering_relevance_score']}; research={item['research_relevance_score']}; novelty={item['novelty_score']}; source_priority={item['source_priority_score']}",
                f"   - reasons: {'; '.join(item['score_reasons'])}",
            ]
        )
    lines.extend(["", "## Top 5 Engineering AI News"])
    for idx, item in enumerate(engineering_top, 1):
        lines.extend(
            [
                f"{idx}. [{item['title']}]({item['url']})",
                f"   - source: {item['source']}",
                f"   - score: {item['score']}",
                f"   - score_breakdown: general={item['general_ai_score']}; engineering={item['engineering_relevance_score']}; research={item['research_relevance_score']}; novelty={item['novelty_score']}; source_priority={item['source_priority_score']}",
                f"   - reasons: {'; '.join(item['score_reasons'])}",
            ]
        )
    lines.extend(["", "## Top 5 Medical, Medicine, and Bio/Genetics AI News"])
    for idx, item in enumerate(medical_bio_top, 1):
        lines.extend(
            [
                f"{idx}. [{item['title']}]({item['url']})",
                f"   - source: {item['source']}",
                f"   - score: {item['score']}",
                f"   - score_breakdown: general={item['general_ai_score']}; engineering={item['engineering_relevance_score']}; research={item['research_relevance_score']}; novelty={item['novelty_score']}; source_priority={item['source_priority_score']}",
                f"   - reasons: {'; '.join(item['score_reasons'])}",
            ]
        )
    lines.extend(["", "## Research Radar"])
    if research_radar:
        for idx, item in enumerate(research_radar, 1):
            lines.extend(
                [
                    f"{idx}. [{item['title']}]({item['url']})",
                    f"   - source: {item['source']}",
                    f"   - score: {item['score']}",
                    f"   - score_breakdown: general={item['general_ai_score']}; engineering={item['engineering_relevance_score']}; research={item['research_relevance_score']}; novelty={item['novelty_score']}; source_priority={item['source_priority_score']}",
                ]
            )
    else:
        lines.append("- No ranked research items in this run.")
    lines.extend(["", "## Watchlist Updates"])
    if search_tasks:
        for task in search_tasks:
            lines.append(f"- [{task['source']}]({task['url']}): {task['query']} ({task.get('source_type', 'manual')}, {task.get('priority', 'medium')})")
    else:
        lines.append("- No manual watchlist items.")
    lines.extend(
        [
            "",
            "## Why It Matters",
            "- The digest is selected from an extensible curated source registry, not a closed hard-coded source list.",
            "- Ranking combines general AI relevance, engineering relevance, research relevance, novelty, source priority, and visible engagement when available.",
            "- Similar-title and canonical-URL duplicate detection is applied before final selection.",
        ]
    )
    if log.failures:
        lines.extend(["", "## Source Failures"])
        for failure in log.failures:
            lines.append(f"- {failure['source']}: {failure['error']}")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window-hours", type=int, default=24)
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()
    candidates, log, search_tasks = build_candidates(args)
    write_outputs(candidates, log, search_tasks, args.date)
    print(
        json.dumps(
            {
                "generated_at": log.generated_at,
                "fetched_count": log.fetched_count,
                "filtered_count": log.filtered_count,
                "failures": len(log.failures),
                "outputs": [
                    f"data/digests/{args.date}-candidates.json",
                    f"data/digests/{args.date}-briefing-input.md",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
