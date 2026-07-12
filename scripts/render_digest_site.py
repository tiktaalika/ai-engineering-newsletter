#!/usr/bin/env python3
"""Render the bilingual AI engineering newsletter as a static HTML site."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DIGEST_DIR = ROOT / "data" / "digests"
REPORTS_DIR = ROOT / "reports"
SITE_DIR = ROOT / "site"
ROOT_OUT = SITE_DIR / "index.html"
ZH_OUT = SITE_DIR / "zh" / "index.html"
EN_OUT = SITE_DIR / "en" / "index.html"
TRENDS_OUT = SITE_DIR / "trends"
SUMMARY_CACHE = DIGEST_DIR / "site_summaries.json"
ARCHIVE_PAGE_SIZE = 7
HISTORY_DEDUP_START = datetime(2026, 7, 5).date()
PUBLISHED_SELECTIONS: dict[str, dict[str, list[dict[str, Any]]]] = {}
BUILDING_SELECTION_INDEX = False


COMMON_EVENT_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "is", "it", "its",
    "new", "of", "on", "or", "s", "says", "the", "to", "with", "report", "reports",
    "reported", "exclusive", "breaking", "news", "via",
}
SOURCE_SUFFIXES = {
    "reuters", "bbc", "cnbc", "forbes", "techcrunch", "bloomberg", "wsj", "financial",
    "times", "guardian", "yahoo", "finance", "ap", "axios", "nytimes", "meta", "openai",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def candidate_dates() -> list[str]:
    dates = []
    for path in DIGEST_DIR.glob("*-candidates.json"):
        match = re.match(r"(\d{4}-\d{2}-\d{2})-candidates\.json$", path.name)
        if match:
            dates.append(match.group(1))
    return sorted(set(dates), reverse=True)


def archive_entries() -> list[dict[str, Any]]:
    dates = candidate_dates()
    if not dates:
        return []
    parsed = [datetime.strptime(date, "%Y-%m-%d").date() for date in dates]
    available = {date.isoformat() for date in parsed}
    cursor = max(parsed)
    oldest = min(parsed)
    entries: list[dict[str, Any]] = []
    while cursor >= oldest:
        slug = cursor.isoformat()
        entries.append({"date": slug, "available": slug in available})
        cursor -= timedelta(days=1)
    return entries


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def effective_source(item: dict[str, Any]) -> str:
    source = str(item.get("source", "")).strip()
    title = str(item.get("title", "")).strip()
    if source.lower().startswith("google news") and " - " in title:
        inferred = title.rsplit(" - ", 1)[-1].strip()
        if inferred:
            return inferred
    return source or "unknown"


def organization_key(item: dict[str, Any]) -> str:
    text = f"{effective_source(item)} {item.get('title', '')} {item.get('url', '')}".lower()
    organizations = [
        "siemens", "simcenter", "rescale", "comsol", "ansys", "dassault", "autodesk",
        "altair", "hexagon", "msc", "ptc", "cadence", "synopsys", "simscale",
        "synera", "navasto", "physicsx", "luminary", "emmi", "diabatix",
        "neural concept", "monolith", "ntop", "colab", "esi group", "beta cae",
        "cadfem", "nafems", "arc advisory", "aerospace manufacturing",
    ]
    for organization in organizations:
        if organization in text:
            if organization == "simcenter":
                return "siemens"
            if organization == "msc":
                return "hexagon"
            return organization
    return effective_source(item).lower()


def site_relative_path(path: Path) -> str:
    return path.relative_to(SITE_DIR).as_posix()


def format_date(date_slug: str) -> str:
    try:
        return datetime.strptime(date_slug, "%Y-%m-%d").strftime("%A, %B %d, %Y")
    except ValueError:
        return date_slug


def canonical_category(category: str) -> str:
    if category in {"engineering_ai", "cae_ai_engineering"}:
        return "engineering_ai"
    return category


def is_guo_yichen_reference_item(item: dict[str, Any]) -> bool:
    return "guo_yichen_reference" in set(item.get("source_tags") or [])


def item_matches_section_category(item: dict[str, Any], category: str) -> bool:
    item_category = canonical_category(item.get("category", ""))
    if category == "general_ai":
        return item_category == "general_ai" or (
            item_category == "research" and is_guo_yichen_reference_item(item)
        )
    return item_category == category


def load_summaries() -> dict[str, str]:
    if not SUMMARY_CACHE.exists():
        return {}
    return load_json(SUMMARY_CACHE)


def load_paper_push(date_slug: str) -> dict[str, Any] | None:
    path = DIGEST_DIR / f"{date_slug}-paper-push.json"
    if not path.exists():
        return None
    data = load_json(path)
    if not (data.get("cae_papers") or data.get("biomedical_papers")):
        return None
    return data


def parse_final_sections(markdown: str) -> dict[str, list[dict[str, str]]]:
    sections = {"general_ai": [], "engineering_ai": [], "medical_bio_ai": []}
    current: str | None = None
    pending: dict[str, str] | None = None
    rich_item_re = re.compile(r"^\d+\.\s+\*\*(.+?)\*\*\s*$")
    source_re = re.compile(r"^English source:\s+\[([^\]]+)\]\((https?://[^)]+)\)")
    compact_re = re.compile(r"^\d+\.\s+(.+?)。原文：\[([^\]]+)\]\((https?://[^)]+)\)")
    for raw in markdown.splitlines():
        line = raw.strip()
        heading = line.strip("# ").strip()
        if heading in {"Top 10 General AI News", "**Top 10 General AI News**", "**AI Top 10**"}:
            current = "general_ai"
            pending = None
            continue
        if heading in {"Top 5 Engineering AI News", "**Top 5 Engineering AI News**", "**CAE / AI for Engineering Top 5**"}:
            current = "engineering_ai"
            pending = None
            continue
        if heading in {"Top 5 Medical, Medicine, and Bio/Genetics AI News", "**Top 5 Medical, Medicine, and Bio/Genetics AI News**", "**Top 5 Medical AI News**"}:
            current = "medical_bio_ai"
            pending = None
            continue
        if heading in {"Research Radar", "Watchlist Updates", "Why It Matters", "Audit Note"}:
            current = None
            pending = None
            continue
        compact = compact_re.match(line)
        if current and compact:
            headline, source_label, url = compact.groups()
            sections[current].append({"headline": headline, "source_label": source_label, "url": url})
            continue
        rich = rich_item_re.match(line)
        if current and rich:
            pending = {"headline": rich.group(1)}
            continue
        source = source_re.match(line)
        if current and pending and source:
            source_label, url = source.groups()
            sections[current].append({"headline": pending["headline"], "source_label": source_label, "url": url})
            pending = None
    return sections


def find_candidate_by_url(data: dict[str, Any], url: str) -> dict[str, Any] | None:
    for key in ("top_100_news_candidates", "top_10_general_ai", "top_5_engineering_ai", "top_5_cae_ai_engineering", "top_5_medical_bio_ai"):
        for item in data.get(key, []):
            if item.get("url") == url:
                return item
    return None


def hydrate_final_items(data: dict[str, Any], final_path: Path) -> dict[str, list[dict[str, Any]]]:
    parsed = parse_final_sections(final_path.read_text(encoding="utf-8"))
    hydrated: dict[str, list[dict[str, Any]]] = {"general_ai": [], "engineering_ai": [], "medical_bio_ai": []}
    for category, rows in parsed.items():
        for row in rows:
            candidate = find_candidate_by_url(data, row["url"]) or {}
            item = dict(candidate)
            item["url"] = row["url"]
            item["source"] = candidate.get("source") or row["source_label"]
            item["title"] = candidate.get("title") or row["source_label"]
            item["zh_summary"] = row["headline"]
            item["category"] = category
            hydrated[category].append(item)
    return hydrated


def event_tokens(title: str) -> set[str]:
    title = re.sub(r"\s+-\s+[^-]+$", "", title.lower())
    return {
        token
        for token in re.findall(r"[a-z0-9]+", title)
        if len(token) > 2 and token not in COMMON_EVENT_WORDS and token not in SOURCE_SUFFIXES
    }


def is_same_event(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("url") and right.get("url") and normalize_url(left.get("url", "")) == normalize_url(right.get("url", "")):
        return True
    left_tokens = event_tokens(left.get("title", ""))
    right_tokens = event_tokens(right.get("title", ""))
    if not left_tokens or not right_tokens:
        return False
    intersection = left_tokens & right_tokens
    smaller = min(len(left_tokens), len(right_tokens))
    union = left_tokens | right_tokens
    if effective_source(left).lower() == effective_source(right).lower() and len(intersection) >= 2 and len(intersection) / max(smaller, 1) >= 0.67:
        return True
    return (len(intersection) >= 5 and len(intersection) / max(smaller, 1) >= 0.5) or (
        len(intersection) >= 4 and len(intersection) / max(len(union), 1) >= 0.42
    )


def normalize_url(url: str) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    parsed = re.sub(r"#.*$", "", url)
    parsed = re.sub(r"[?&](utm_[^=&]+|fbclid|gclid|mc_cid|mc_eid)=[^&]+", "", parsed, flags=re.IGNORECASE)
    parsed = parsed.rstrip("/")
    return parsed.lower()


def topic_key(item: dict[str, Any]) -> str:
    text = f"{item.get('title', '')} {item.get('text', '')}".lower()
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
    if canonical_category(item.get("category", "")) == "engineering_ai":
        if any(term in text for term in ("cfd", "fea", "cae", "simulation", "surrogate", "digital twin", "neural operator")):
            return "cae_simulation"
    return "other"


def is_excluded(item: dict[str, Any], category: str) -> bool:
    if canonical_category(category) != "engineering_ai":
        return False
    text = f"{item.get('title', '')} {item.get('source', '')} {item.get('text', '')}".lower()
    excluded_terms = {
        "analysts offer insights", "industrial goods companies", "tsx:cae", "forex.com",
        "ai index cfd", "capital.com", "tradingview", "finance magnates", "traders",
        "trading", "brokers", "cfd access", "surrogate model virus", "chatbots in a simulation",
    }
    return any(term in text for term in excluded_terms)


def is_medical_bio_ai_item(item: dict[str, Any]) -> bool:
    text = f"{item.get('title', '')} {item.get('source', '')} {item.get('text', '')} {' '.join(item.get('source_tags', []))}".lower()
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


def historical_reference_items(date_slug: str, lookback_days: int = 7) -> list[dict[str, Any]]:
    try:
        current = datetime.strptime(date_slug, "%Y-%m-%d").date()
    except ValueError:
        return []
    references: list[dict[str, Any]] = []
    for previous_date in candidate_dates():
        try:
            previous = datetime.strptime(previous_date, "%Y-%m-%d").date()
        except ValueError:
            continue
        age = (current - previous).days
        if age <= 0 or age > lookback_days:
            continue
        data = load_json(DIGEST_DIR / f"{previous_date}-candidates.json")
        final_path = DIGEST_DIR / f"{previous_date}-final.md"
        if final_path.exists():
            hydrated = hydrate_final_items(data, final_path)
            for category_items in hydrated.values():
                references.extend(category_items)
        for key in (
            "top_10_general_ai",
            "top_5_engineering_ai",
            "top_5_cae_ai_engineering",
            "top_5_medical_bio_ai",
            "research_radar",
        ):
            references.extend(data.get(key, []))
    return references


def historical_published_items(date_slug: str, lookback_days: int = 7) -> list[dict[str, Any]]:
    try:
        current = datetime.strptime(date_slug, "%Y-%m-%d").date()
    except ValueError:
        return []
    references: list[dict[str, Any]] = []
    for previous_date, sections in PUBLISHED_SELECTIONS.items():
        try:
            previous = datetime.strptime(previous_date, "%Y-%m-%d").date()
        except ValueError:
            continue
        age = (current - previous).days
        if age <= 0 or age > lookback_days:
            continue
        for items in sections.values():
            references.extend(items)
    return references


def ensure_published_selection_index() -> None:
    global BUILDING_SELECTION_INDEX
    if PUBLISHED_SELECTIONS or BUILDING_SELECTION_INDEX:
        return
    BUILDING_SELECTION_INDEX = True
    try:
        for date_slug in sorted(candidate_dates()):
            data, general, engineering, medical, research, _paper_push = day_items(date_slug)
            del data
            PUBLISHED_SELECTIONS[date_slug] = {
                "general_ai": general,
                "engineering_ai": engineering,
                "medical_bio_ai": medical,
                "research": research,
            }
    finally:
        BUILDING_SELECTION_INDEX = False


def is_recent_repeat(item: dict[str, Any], historical_items: list[dict[str, Any]]) -> bool:
    return any(is_same_event(item, previous) for previous in historical_items)


def select_unique(
    items: list[dict[str, Any]],
    category: str,
    limit: int,
    historical_items: list[dict[str, Any]] | None = None,
    require_guo_general: bool = True,
) -> list[dict[str, Any]]:
    category = canonical_category(category)
    historical_items = historical_items or []
    selected: list[dict[str, Any]] = []
    topic_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    max_per_source_first_pass = 1 if category == "engineering_ai" else 2
    for item in items:
        if not item_matches_section_category(item, category) or is_excluded(item, category):
            continue
        if category == "general_ai" and require_guo_general and not is_guo_yichen_reference_item(item):
            continue
        if is_recent_repeat(item, historical_items):
            continue
        if any(is_same_event(item, existing) for existing in selected):
            continue
        topic = topic_key(item)
        if topic_counts.get(topic, 0) >= 2:
            continue
        source = effective_source(item).lower()
        if source_counts.get(source, 0) >= max_per_source_first_pass:
            continue
        selected.append(item)
        topic_counts[topic] = topic_counts.get(topic, 0) + 1
        source_counts[source] = source_counts.get(source, 0) + 1
        if len(selected) == limit:
            break
    for item in items:
        if len(selected) == limit:
            break
        if not item_matches_section_category(item, category) or is_excluded(item, category):
            continue
        if category == "general_ai" and require_guo_general and not is_guo_yichen_reference_item(item):
            continue
        if is_recent_repeat(item, historical_items):
            continue
        if item in selected or any(is_same_event(item, existing) for existing in selected):
            continue
        source = effective_source(item).lower()
        if source_counts.get(source, 0) >= max_per_source_first_pass:
            continue
        selected.append(item)
        source_counts[source] = source_counts.get(source, 0) + 1
    for item in items:
        if len(selected) == limit:
            break
        if not item_matches_section_category(item, category) or is_excluded(item, category):
            continue
        if category == "general_ai" and require_guo_general and not is_guo_yichen_reference_item(item):
            continue
        if is_recent_repeat(item, historical_items):
            continue
        if item in selected or any(is_same_event(item, existing) for existing in selected):
            continue
        source = effective_source(item).lower()
        if category in {"general_ai", "engineering_ai"} and source_counts.get(source, 0) >= max_per_source_first_pass:
            continue
        selected.append(item)
        source_counts[source] = source_counts.get(source, 0) + 1
    return selected


def dedupe_and_fill_items(
    primary: list[dict[str, Any]],
    data: dict[str, Any],
    category: str,
    limit: int,
    fallback_key: str,
    historical_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    category = canonical_category(category)
    if category == "general_ai":
        primary_items = primary or data.get(fallback_key, [])
        require_guo = any(is_guo_yichen_reference_item(item) for item in primary_items)
        pool = primary_items + data.get("top_100_news_candidates", []) + data.get(fallback_key, [])
        selected = select_unique(pool, category, limit, historical_items, require_guo_general=require_guo)
        if len(selected) < limit:
            selected = select_unique(pool, category, limit, historical_items, require_guo_general=False)
        return selected
    pool: list[dict[str, Any]] = []
    for item in primary + data.get("top_100_news_candidates", []) + data.get(fallback_key, []):
        candidate = dict(item)
        candidate["category"] = canonical_category(candidate.get("category", category))
        pool.append(candidate)
    return select_unique(pool, category, limit, historical_items)


def section_items(
    data: dict[str, Any],
    category: str,
    limit: int,
    fallback_key: str,
    historical_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    category = canonical_category(category)
    if category == "general_ai":
        fallback_items = data.get(fallback_key, [])
        require_guo = any(is_guo_yichen_reference_item(item) for item in fallback_items)
        pool = fallback_items + data.get("top_100_news_candidates", [])
        selected = select_unique(pool, category, limit, historical_items, require_guo_general=require_guo)
        if len(selected) < limit:
            selected = select_unique(pool, category, limit, historical_items, require_guo_general=False)
        return selected
    pool = data.get("top_100_news_candidates", [])
    selected = select_unique(pool, category, limit, historical_items)
    if len(selected) >= limit:
        return selected
    for item in data.get(fallback_key, []):
        item = dict(item)
        item["category"] = canonical_category(item.get("category", category))
        if category == "general_ai" and not is_guo_yichen_reference_item(item):
            continue
        if is_recent_repeat(item, historical_items or []):
            continue
        if any(is_same_event(item, existing) for existing in selected):
            continue
        selected.append(item)
        if len(selected) == limit:
            break
    return selected


def medical_bio_items(
    data: dict[str, Any],
    limit: int = 5,
    historical_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    historical_items = historical_items or []
    pool = data.get("top_100_news_candidates", [])
    selected: list[dict[str, Any]] = []
    topic_counts: dict[str, int] = {}
    for item in pool:
        if canonical_category(item.get("category", "")) not in {"general_ai", "research"}:
            continue
        if not is_medical_bio_ai_item(item):
            continue
        if is_recent_repeat(item, historical_items):
            continue
        if any(is_same_event(item, existing) for existing in selected):
            continue
        topic = topic_key(item)
        if topic_counts.get(topic, 0) >= 2:
            continue
        selected.append(item)
        topic_counts[topic] = topic_counts.get(topic, 0) + 1
        if len(selected) == limit:
            break
    for item in data.get("top_5_medical_bio_ai", []):
        if len(selected) == limit:
            break
        if is_recent_repeat(item, historical_items):
            continue
        if any(is_same_event(item, existing) for existing in selected):
            continue
        selected.append(item)
    return selected


def research_items(
    data: dict[str, Any],
    limit: int = 5,
    historical_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    historical_items = historical_items or []
    selected = select_unique(data.get("top_100_news_candidates", []), "research", limit, historical_items)
    if len(selected) >= limit:
        return selected
    for item in data.get("research_radar", []):
        if is_recent_repeat(item, historical_items):
            continue
        if any(is_same_event(item, existing) for existing in selected):
            continue
        selected.append(item)
        if len(selected) == limit:
            break
    return selected


def day_items(date_slug: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    data = load_json(DIGEST_DIR / f"{date_slug}-candidates.json")
    paper_push = load_paper_push(date_slug)
    try:
        issue_date = datetime.strptime(date_slug, "%Y-%m-%d").date()
    except ValueError:
        issue_date = HISTORY_DEDUP_START
    if issue_date >= HISTORY_DEDUP_START and PUBLISHED_SELECTIONS:
        historical_items = historical_published_items(date_slug)
    elif issue_date >= HISTORY_DEDUP_START:
        historical_items = historical_reference_items(date_slug)
    else:
        historical_items = []
    final_path = DIGEST_DIR / f"{date_slug}-final.md"
    if final_path.exists():
        final_items = hydrate_final_items(data, final_path)
        general = dedupe_and_fill_items(
            final_items["general_ai"], data, "general_ai", 10, "top_10_general_ai", historical_items
        )
        engineering = dedupe_and_fill_items(
            final_items["engineering_ai"],
            data,
            "engineering_ai",
            5,
            "top_5_engineering_ai",
            historical_items + general,
        )
        medical_history = historical_items + general + engineering
        medical = final_items["medical_bio_ai"] or medical_bio_items(data, historical_items=medical_history)
        medical = [
            item
            for item in medical
            if not any(is_same_event(item, previous) for previous in medical_history)
        ][:5]
        research = research_items(data, historical_items=historical_items + general + engineering + medical)
        return (
            data,
            general,
            engineering,
            medical,
            research,
            paper_push,
        )
    general = section_items(data, "general_ai", 10, "top_10_general_ai", historical_items)
    engineering = section_items(data, "engineering_ai", 5, "top_5_engineering_ai", historical_items + general)
    medical = medical_bio_items(data, historical_items=historical_items + general + engineering)
    research = research_items(data, historical_items=historical_items + general + engineering + medical)
    return (
        data,
        general,
        engineering,
        medical,
        research,
        paper_push,
    )


def english_summary(item: dict[str, Any]) -> str:
    text = re.sub(r"\s+", " ", item.get("text", "")).strip()
    title = item.get("title", "").strip()
    if title and text.lower().startswith(title.lower()):
        text = text[len(title):].strip(" -:.,")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    summary = " ".join(sentence for sentence in sentences[:2] if sentence)
    if not summary:
        summary = "Selected for its relevance, source priority, recency, and cross-source/topic evidence."
    if len(summary) > 340:
        summary = summary[:337].rstrip() + "..."
    return summary


def item_card_zh(item: dict[str, Any], idx: int, summaries: dict[str, str]) -> str:
    summary = esc(item.get("zh_summary") or summaries.get(item.get("id", ""), ""))
    summary_html = f'<p class="zh-summary">{summary}</p>' if summary else ""
    return f"""
      <article class="item">
        <div class="rank">{idx:02d}</div>
        <div>
          {summary_html}
          <h4><a href="{esc(item.get("url", "#"))}">{esc(item.get("title", "Untitled"))}</a></h4>
          <div class="meta"><span>{esc(effective_source(item))}</span><span>score {esc(item.get("score", ""))}</span></div>
          <p class="reason">{esc("; ".join(item.get("score_reasons", [])[:2]))}</p>
        </div>
      </article>
    """


def item_card_en(item: dict[str, Any], idx: int) -> str:
    return f"""
      <article class="item">
        <div class="rank">{idx:02d}</div>
        <div>
          <h4><a href="{esc(item.get("url", "#"))}">{esc(item.get("title", "Untitled"))}</a></h4>
          <p class="en-summary">{esc(english_summary(item))}</p>
          <div class="meta"><span>{esc(effective_source(item))}</span><span>score {esc(item.get("score", ""))}</span></div>
          <p class="reason">{esc("; ".join(item.get("score_reasons", [])[:2]))}</p>
        </div>
      </article>
    """


def empty_note(language: str, section: str) -> str:
    if language == "zh":
        messages = {
            "engineering": "发布前检查发现，本周前几天已经发过相似 Engineering AI 内容；今天没有足够新的非重复条目，所以不硬凑满 5 条。",
            "general": "发布前检查后，今天没有足够新的非重复条目。",
        }
    else:
        messages = {
            "engineering": "Pre-publish history checks found that similar Engineering AI items were already covered earlier this week, so this issue does not force-fill duplicates.",
            "general": "Pre-publish history checks did not find enough fresh non-duplicate items for this section.",
        }
    return f'<p class="empty-note">{esc(messages.get(section, messages["general"]))}</p>'


def render_research_radar(items: list[dict[str, Any]], language: str, summaries: dict[str, str]) -> str:
    if not items:
        return ""
    title = "Research Radar" if language == "en" else "Research Radar"
    cards = (
        "".join(item_card_en(item, idx) for idx, item in enumerate(items, 1))
        if language == "en"
        else "".join(item_card_zh(item, idx, summaries) for idx, item in enumerate(items, 1))
    )
    return f"""
      <section class="medical-section">
        <h3>{esc(title)}</h3>
        {cards}
      </section>
    """


def render_right_column(
    engineering_title: str,
    engineering_html: str,
    medical_title: str,
    medical_html: str,
) -> str:
    return f"""
      <section>
        <h3>{esc(engineering_title)}</h3>
        {engineering_html}
        <div class="subsection">
          <h3>{esc(medical_title)}</h3>
          {medical_html}
        </div>
      </section>
    """


def render_paper_push(paper_push: dict[str, Any] | None, language: str) -> str:
    if not paper_push:
        return ""
    title = paper_push.get("title_zh") if language == "zh" else paper_push.get("title_en")
    intro = paper_push.get("intro_zh") if language == "zh" else paper_push.get("intro_en")
    cae_papers = list(paper_push.get("cae_papers") or [])
    bio_papers = list(paper_push.get("biomedical_papers") or [])
    papers = cae_papers + bio_papers
    if not papers:
        return ""

    cards = []
    for idx, paper in enumerate(papers, 1):
        summary = paper.get("summary_zh") if language == "zh" else paper.get("summary_en")
        meta = " · ".join(
            part
            for part in [
                paper.get("source", ""),
                paper.get("published", ""),
            ]
            if part
        )
        why = paper.get("why", "")
        cards.append(
            f"""
          <article class="paper-item">
            <div class="rank">{idx:02d}</div>
            <div>
              <h4><a href="{esc(paper.get("url", "#"))}">{esc(paper.get("title", "Untitled"))}</a></h4>
              <p class="en-summary">{esc(summary)}</p>
              <div class="meta"><span>{esc(meta)}</span></div>
              <p class="reason">{esc(why)}</p>
            </div>
          </article>
            """
        )
    return f"""
      <section class="paper-push">
        <p class="eyebrow">Friday Paper Push</p>
        <h3>{esc(title or "Weekly AI-for-CAE Paper Push")}</h3>
        <p class="paper-intro">{esc(intro or "")}</p>
        {''.join(cards)}
      </section>
    """


def render_day_zh(date_slug: str, summaries: dict[str, str]) -> str:
    data, general, cae, medical, _research, paper_push = day_items(date_slug)
    general_html = "".join(item_card_zh(item, idx, summaries) for idx, item in enumerate(general, 1))
    engineering_html = "".join(item_card_zh(item, idx, summaries) for idx, item in enumerate(cae, 1))
    medical_html = "".join(item_card_zh(item, idx, summaries) for idx, item in enumerate(medical, 1))
    return render_day_shell(
        date_slug,
        data,
        "AI Top 10",
        general_html or empty_note("zh", "general"),
        render_right_column(
            "Engineering AI Top 5",
            engineering_html or empty_note("zh", "engineering"),
            "Biomedical AI Top 5",
            medical_html or empty_note("zh", "general"),
        ),
        render_paper_push(paper_push, "zh"),
    )


def render_day_en(date_slug: str) -> str:
    data, general, cae, medical, _research, paper_push = day_items(date_slug)
    general_html = "".join(item_card_en(item, idx) for idx, item in enumerate(general, 1))
    engineering_html = "".join(item_card_en(item, idx) for idx, item in enumerate(cae, 1))
    medical_html = "".join(item_card_en(item, idx) for idx, item in enumerate(medical, 1))
    return render_day_shell(
        date_slug,
        data,
        "Top 10 General AI News",
        general_html or empty_note("en", "general"),
        render_right_column(
            "Top 5 Engineering AI News",
            engineering_html or empty_note("en", "engineering"),
            "Top 5 Biomedical AI News",
            medical_html or empty_note("en", "general"),
        ),
        render_paper_push(paper_push, "en"),
    )


def render_day_shell(
    date_slug: str,
    data: dict[str, Any],
    general_title: str,
    general_html: str,
    right_column_html: str,
    paper_push_html: str,
) -> str:
    log = data.get("run_log", {})
    return f"""
    <section class="day" id="{date_slug}">
      <header class="day-head">
        <div>
          <p class="eyebrow">{esc(format_date(date_slug))}</p>
          <h2>{esc(date_slug)}</h2>
        </div>
        <div class="audit">
          <span>{esc(log.get("fetched_count", 0))} fetched</span>
          <span>{esc(log.get("filtered_count", 0))} candidates</span>
          <span>{len(log.get("failures", []))} failures</span>
        </div>
      </header>
      <div class="columns">
        <section>
          <h3>{esc(general_title)}</h3>
          {general_html}
        </section>
        {right_column_html}
      </div>
      {paper_push_html}
    </section>
    """


def render_missing_day(date_slug: str, language: str) -> str:
    eyebrow = format_date(date_slug)
    if language == "zh":
        title = "当日归档缺失"
        body = "当前站点里没有这一天的 digest 文件。页面会保留这个日期，避免时间线看起来像是连续的。"
    else:
        title = "Issue missing for this date"
        body = "No digest file is currently available for this date. The archive keeps the date visible so the timeline does not silently skip it."
    return f"""
    <section class="day missing" id="{date_slug}">
      <header class="day-head">
        <div>
          <p class="eyebrow">{esc(eyebrow)}</p>
          <h2>{esc(date_slug)}</h2>
        </div>
      </header>
      <div class="missing-note">
        <h3>{esc(title)}</h3>
        <p>{esc(body)}</p>
      </div>
    </section>
    """


def latest_trend_reports() -> dict[str, Path | None]:
    reports: dict[str, Path | None] = {"weekly": None, "monthly": None}
    for kind in reports:
        paths = sorted((REPORTS_DIR / kind).glob("*-github-trends.md"), reverse=True)
        reports[kind] = paths[0] if paths else None
    return reports


def trend_report_title(path: Path | None, kind: str) -> str:
    if not path:
        return "No report yet"
    date_match = re.match(r"(\d{4}-\d{2}-\d{2})-", path.name)
    label = "Weekly" if kind == "weekly" else "Monthly"
    return f"{label} report: {date_match.group(1) if date_match else path.stem}"


def trend_report_output_path(path: Path) -> Path:
    kind = path.parent.name
    slug = path.stem.replace("-github-trends", "")
    return TRENDS_OUT / kind / slug / "index.html"


def trend_report_href(path: Path | None, from_dir: str) -> str:
    if not path:
        return "#"
    output_path = trend_report_output_path(path)
    relative = site_relative_path(output_path)
    if from_dir == "root":
        return relative
    if from_dir in {"en", "zh"}:
        return "../" + relative
    return relative


def heading_id(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def trend_panel(language: str, from_dir: str) -> str:
    reports = latest_trend_reports()
    weekly = reports["weekly"]
    monthly = reports["monthly"]
    if language == "zh":
        eyebrow = "GitHub 趋势监控"
        title = "开源项目趋势雷达"
        body = "每周和每月跟踪 AI Agent、MCP、RAG、LLM Infrastructure、Simulation、Engineering AI 六类 GitHub 仓库。"
        weekly_label = "查看最新周报"
        monthly_label = "查看最新月报"
        agent_label = "直达 Agent 榜单"
    else:
        eyebrow = "GitHub Trend Monitor"
        title = "Open-source repository radar"
        body = "Weekly and monthly tracking across AI Agent, MCP, RAG, LLM Infrastructure, Simulation, and Engineering AI repositories."
        weekly_label = "Open latest weekly"
        monthly_label = "Open latest monthly"
        agent_label = "Jump to Agent ranking"
    agent_href = trend_report_href(weekly, from_dir)
    if agent_href != "#":
        agent_href += "#ai-agent"
    return f"""
    <section class="trend-panel" id="github-trends">
      <div>
        <p class="eyebrow">{esc(eyebrow)}</p>
        <h2>{esc(title)}</h2>
        <p>{esc(body)}</p>
      </div>
      <div class="trend-actions">
        <a href="{esc(trend_report_href(weekly, from_dir))}"><strong>{esc(weekly_label)}</strong><span>{esc(trend_report_title(weekly, "weekly"))}</span></a>
        <a href="{esc(trend_report_href(monthly, from_dir))}"><strong>{esc(monthly_label)}</strong><span>{esc(trend_report_title(monthly, "monthly"))}</span></a>
        <a href="{esc(agent_href)}"><strong>{esc(agent_label)}</strong><span>AI Agent / multi-agent / browser-use / LangGraph / AutoGen</span></a>
      </div>
    </section>
    """


def markdown_inline(value: str) -> str:
    escaped = esc(value)
    escaped = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped


def markdown_report_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    html_lines: list[str] = []
    paragraph: list[str] = []
    idx = 0

    def flush_paragraph() -> None:
        if paragraph:
            html_lines.append(f"<p>{markdown_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    while idx < len(lines):
        line = lines[idx].rstrip()
        if not line.strip():
            flush_paragraph()
            idx += 1
            continue
        if line.startswith("#"):
            flush_paragraph()
            level = min(len(line) - len(line.lstrip("#")), 4)
            text = line.lstrip("#").strip()
            html_lines.append(f'<h{level} id="{esc(heading_id(text))}">{markdown_inline(text)}</h{level}>')
            idx += 1
            continue
        if line.startswith("- "):
            flush_paragraph()
            html_lines.append("<ul>")
            while idx < len(lines) and lines[idx].startswith("- "):
                html_lines.append(f"<li>{markdown_inline(lines[idx][2:].strip())}</li>")
                idx += 1
            html_lines.append("</ul>")
            continue
        if line.startswith("|") and idx + 1 < len(lines) and lines[idx + 1].startswith("|"):
            flush_paragraph()
            table_rows: list[list[str]] = []
            while idx < len(lines) and lines[idx].startswith("|"):
                cells = [cell.strip() for cell in lines[idx].strip("|").split("|")]
                if cells and all(set(cell) <= {"-", ":", " "} for cell in cells):
                    idx += 1
                    continue
                table_rows.append(cells)
                idx += 1
            if table_rows:
                header, *body = table_rows
                html_lines.append('<div class="report-table-wrap"><table class="report-table"><thead><tr>')
                html_lines.extend(f"<th>{markdown_inline(cell)}</th>" for cell in header)
                html_lines.append("</tr></thead><tbody>")
                for row in body:
                    html_lines.append("<tr>")
                    html_lines.extend(f"<td>{markdown_inline(cell)}</td>" for cell in row)
                    html_lines.append("</tr>")
                html_lines.append("</tbody></table></div>")
            continue
        paragraph.append(line.strip())
        idx += 1
    flush_paragraph()
    return "\n".join(html_lines)


def render_trend_report_page(report_path: Path) -> str:
    markdown = report_path.read_text(encoding="utf-8")
    title_line = next((line.lstrip("#").strip() for line in markdown.splitlines() if line.startswith("# ")), report_path.stem)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title_line)}</title>
  <style>{site_css()}</style>
</head>
<body>
  <header class="hero">
    <div class="hero-inner">
      <div>
        <h1>{esc(title_line)}</h1>
        <p class="subtitle">GitHub repository trend monitoring report.</p>
        <div class="language-switch"><a href="../../../en/index.html#github-trends">Back to Newsletter</a><a href="../../../zh/index.html#github-trends">返回中文页</a></div>
      </div>
      <div class="stamp">Trend Monitor<br><strong>{esc(report_path.parent.name.title())}</strong></div>
    </div>
  </header>
  <main class="shell">
    <article class="report-document">
      {markdown_report_to_html(markdown)}
    </article>
  </main>
</body>
</html>
"""


def render_trend_report_pages() -> list[Path]:
    written: list[Path] = []
    for report_path in sorted(REPORTS_DIR.glob("*/*-github-trends.md")):
        output_path = trend_report_output_path(report_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render_trend_report_page(report_path), encoding="utf-8")
        written.append(output_path)
    return written


def site_css() -> str:
    return """
    :root {
      color-scheme: light;
      --ink: #191815;
      --muted: #6f6a60;
      --line: #d7d0c2;
      --paper: #f8f5ee;
      --panel: #fffdf8;
      --accent: #0b6b5a;
      --accent-2: #c1492e;
      --shadow: 0 22px 70px rgba(47, 38, 24, .11);
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      font-family: Charter, "Iowan Old Style", Georgia, serif;
      background:
        linear-gradient(90deg, rgba(25,24,21,.035) 1px, transparent 1px) 0 0/38px 38px,
        linear-gradient(#fbf8f1, #eee7d8);
      color: var(--ink);
    }
    .shell { max-width: 1180px; margin: 0 auto; padding: 34px 22px 80px; }
    .hero { position: sticky; top: 0; z-index: 5; padding: 22px 0 20px; backdrop-filter: blur(18px); background: color-mix(in srgb, var(--paper) 78%, transparent); border-bottom: 1px solid rgba(25,24,21,.1); }
    .hero-inner { max-width: 1180px; margin: 0 auto; padding: 0 22px; display: grid; grid-template-columns: 1fr auto; gap: 20px; align-items: end; }
    h1 { margin: 0; font-size: clamp(30px, 4vw, 56px); line-height: 1; letter-spacing: 0; font-weight: 700; }
    .subtitle { margin: 12px 0 0; color: var(--muted); font-size: 17px; max-width: 760px; }
    .stamp { text-align: right; font-size: 14px; color: var(--muted); }
    .nav, .language-switch, .pager { display: flex; gap: 8px; flex-wrap: wrap; margin: 24px 0 28px; }
    .nav { margin-bottom: 16px; }
    .nav a, .nav span, .language-switch a, .pager a, .pager span { color: var(--ink); border: 1px solid var(--line); padding: 7px 10px; text-decoration: none; background: rgba(255,255,255,.55); }
    .nav span, .pager span { color: var(--muted); }
    .language-switch a.active { background: var(--ink); color: var(--panel); border-color: var(--ink); }
    .day { background: var(--panel); border: 1px solid var(--line); box-shadow: var(--shadow); margin: 28px 0; padding: 24px; }
    .day.missing { border-style: dashed; }
    .day-head { display: flex; justify-content: space-between; gap: 20px; border-bottom: 2px solid var(--ink); padding-bottom: 16px; margin-bottom: 22px; }
    .eyebrow { margin: 0 0 5px; color: var(--accent-2); font-size: 13px; text-transform: uppercase; letter-spacing: .08em; font-family: "Avenir Next", Verdana, sans-serif; }
    h2 { margin: 0; font-size: 38px; }
    h3 { margin: 0 0 14px; font-size: 21px; font-family: "Avenir Next", Verdana, sans-serif; }
    .audit { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; align-content: start; }
    .audit span { border: 1px solid var(--line); padding: 7px 10px; color: var(--muted); font-family: "Avenir Next", Verdana, sans-serif; font-size: 13px; }
    .columns { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(300px, .85fr); gap: 24px; }
    .medical-section { margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--line); }
    .subsection { margin-top: 22px; padding-top: 18px; border-top: 2px solid var(--ink); }
    .item { display: grid; grid-template-columns: 42px 1fr; gap: 12px; padding: 15px 0; border-top: 1px solid var(--line); }
    .paper-push { margin-top: 26px; padding-top: 20px; border-top: 2px solid var(--ink); }
    .paper-intro { margin: 0 0 8px; color: var(--muted); line-height: 1.5; max-width: 820px; }
    .paper-item { display: grid; grid-template-columns: 42px 1fr; gap: 12px; padding: 15px 0; border-top: 1px solid var(--line); }
    .rank { font-family: "Avenir Next", Verdana, sans-serif; color: var(--accent); font-weight: 700; }
    h4 { margin: 0; font-size: 18px; line-height: 1.25; }
    .zh-summary { margin: 0 0 7px; font-size: 18px; line-height: 1.38; font-weight: 700; color: var(--ink); }
    .en-summary { margin: 8px 0 0; font-size: 15px; line-height: 1.46; color: var(--muted); }
    a { color: var(--ink); text-decoration-color: color-mix(in srgb, var(--accent), transparent 40%); text-underline-offset: 3px; }
    .meta { margin-top: 7px; display: flex; flex-wrap: wrap; gap: 8px; font-family: "Avenir Next", Verdana, sans-serif; font-size: 12px; color: var(--muted); }
    .meta span { border: 1px solid var(--line); padding: 4px 7px; }
    .reason { margin: 8px 0 0; color: var(--muted); font-size: 14px; line-height: 1.4; }
    .empty-note { margin: 0; border: 1px dashed var(--line); padding: 14px; color: var(--muted); line-height: 1.45; background: rgba(255,255,255,.42); }
    .missing-note h3 { margin: 0 0 10px; font-size: 21px; font-family: "Avenir Next", Verdana, sans-serif; }
    .missing-note p { margin: 0; color: var(--muted); line-height: 1.5; max-width: 760px; }
    .landing { min-height: 100vh; display: grid; align-items: center; }
    .landing-panel { max-width: 980px; margin: 0 auto; padding: 44px 22px; }
    .landing h1 { font-size: clamp(38px, 7vw, 86px); }
    .landing-links { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 34px; }
    .edition { display: block; border: 1px solid var(--line); background: var(--panel); padding: 24px; text-decoration: none; box-shadow: var(--shadow); }
    .edition strong { display: block; font-size: 28px; margin-bottom: 8px; }
    .edition span { color: var(--muted); line-height: 1.45; }
    .trend-panel { background: var(--ink); color: var(--panel); margin: 0 0 28px; padding: 24px; display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, .8fr); gap: 24px; align-items: end; }
    .trend-panel .eyebrow { color: #f0b45f; }
    .trend-panel h2 { font-size: 32px; }
    .trend-panel p { margin: 10px 0 0; color: rgba(255,253,248,.76); line-height: 1.5; max-width: 720px; }
    .trend-actions { display: grid; gap: 10px; }
    .trend-actions a { border: 1px solid rgba(255,253,248,.28); color: var(--panel); padding: 14px; text-decoration: none; background: rgba(255,253,248,.08); }
    .trend-actions strong { display: block; font-family: "Avenir Next", Verdana, sans-serif; font-size: 14px; margin-bottom: 4px; }
    .trend-actions span { display: block; color: rgba(255,253,248,.72); font-size: 14px; }
    .report-document { background: var(--panel); border: 1px solid var(--line); box-shadow: var(--shadow); padding: 24px; }
    .report-document h1 { font-size: 40px; margin-bottom: 14px; }
    .report-document h2 { border-top: 2px solid var(--ink); margin-top: 30px; padding-top: 18px; font-size: 28px; }
    .report-document h3 { margin-top: 24px; }
    .report-document h4 { margin-top: 18px; font-family: "Avenir Next", Verdana, sans-serif; }
    .report-document p, .report-document li { line-height: 1.5; color: var(--muted); }
    .report-table-wrap { overflow-x: auto; border: 1px solid var(--line); margin: 14px 0 22px; }
    .report-table { width: 100%; border-collapse: collapse; min-width: 980px; font-family: "Avenir Next", Verdana, sans-serif; font-size: 12px; }
    .report-table th, .report-table td { border-bottom: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }
    .report-table th { background: #eee7d8; color: var(--ink); position: sticky; top: 0; }
    code { background: rgba(11,107,90,.08); padding: 1px 4px; }
    @media (max-width: 860px) {
      .hero-inner, .day-head, .columns, .landing-links, .trend-panel { grid-template-columns: 1fr; }
      .stamp { text-align: left; }
      .day { padding: 18px; }
      h2 { font-size: 30px; }
    }
  """


def archive_page_path(language: str, page_number: int) -> Path:
    if language == "zh":
        return ZH_OUT if page_number == 1 else SITE_DIR / "zh" / "page" / str(page_number) / "index.html"
    return EN_OUT if page_number == 1 else SITE_DIR / "en" / "page" / str(page_number) / "index.html"


def archive_page_href(language: str, current_page: int, target_page: int) -> str:
    del language
    if current_page == target_page:
        return "./index.html"
    if current_page == 1:
        return f"page/{target_page}/index.html" if target_page > 1 else "./index.html"
    if target_page == 1:
        return "../../index.html"
    return f"../{target_page}/index.html"


def switch_href(language: str, page_number: int) -> str:
    if page_number == 1:
        return "../en/index.html" if language == "zh" else "../zh/index.html"
    return (
        f"../../../en/page/{page_number}/index.html"
        if language == "zh"
        else f"../../../zh/page/{page_number}/index.html"
    )


def render_archive_page(language: str, page_number: int, total_pages: int, entries: list[dict[str, Any]]) -> str:
    ensure_published_selection_index()
    summaries = load_summaries()
    latest = next((entry["date"] for entry in entries if entry["available"]), "No newsletters yet")
    start = (page_number - 1) * ARCHIVE_PAGE_SIZE
    page_entries = entries[start:start + ARCHIVE_PAGE_SIZE]
    page_range = ""
    if page_entries:
        page_range = f"{page_entries[-1]['date']} — {page_entries[0]['date']}"
    nav = "".join(
        (
            f'<a href="#{esc(entry["date"])}">{esc(entry["date"])}</a>'
            if entry["available"]
            else f'<span>{esc(entry["date"])}</span>'
        )
        for entry in page_entries
    )
    pager_bits: list[str] = []
    if page_number < total_pages:
        label = "Older week" if language == "en" else "上一周"
        pager_bits.append(f'<a href="{esc(archive_page_href(language, page_number, page_number + 1))}">{esc(label)}</a>')
    else:
        label = "Older week" if language == "en" else "上一周"
        pager_bits.append(f'<span>{esc(label)}</span>')
    if page_number > 1:
        label = "Newer week" if language == "en" else "下一周"
        pager_bits.append(f'<a href="{esc(archive_page_href(language, page_number, page_number - 1))}">{esc(label)}</a>')
    else:
        label = "Newer week" if language == "en" else "下一周"
        pager_bits.append(f'<span>{esc(label)}</span>')
    pager = "".join(pager_bits)
    if language == "zh":
        lang_attr = "zh-CN"
        title = "AI Engineering Newsletter 中文版"
        subtitle = "一个页面聚合 News Push 和 GitHub Trend Monitor。覆盖 General AI、Engineering AI、CAE、CAD、simulation、digital twin、industrial AI 与 scientific ML；最新日期在最上面。"
        switch = f'<a class="active" href="{esc(archive_page_href("zh", page_number, page_number))}">中文版</a><a href="{esc(switch_href("zh", page_number))}">English</a>'
        days = "\n".join(
            render_day_zh(entry["date"], summaries) if entry["available"] else render_missing_day(entry["date"], "zh")
            for entry in page_entries
        )
        stamp = f'Latest Issued<br><strong>{esc(latest)}</strong><br><span>{esc(page_range)}</span>'
    else:
        lang_attr = "en"
        title = "AI Engineering Newsletter"
        subtitle = "One public page for News Push and GitHub Trend Monitor across general AI, engineering AI, CAE, CAD, simulation, digital twins, industrial AI, and scientific ML."
        switch = f'<a href="{esc(switch_href("en", page_number))}">中文版</a><a class="active" href="{esc(archive_page_href("en", page_number, page_number))}">English</a>'
        days = "\n".join(
            render_day_en(entry["date"]) if entry["available"] else render_missing_day(entry["date"], "en")
            for entry in page_entries
        )
        stamp = f'Latest Issued<br><strong>{esc(latest)}</strong><br><span>{esc(page_range)}</span>'
    return f"""<!doctype html>
<html lang="{lang_attr}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>{site_css()}</style>
</head>
<body>
  <header class="hero">
    <div class="hero-inner">
      <div>
        <h1>{esc(title)}</h1>
        <p class="subtitle">{esc(subtitle)}</p>
        <div class="language-switch">{switch}</div>
      </div>
      <div class="stamp">{stamp}</div>
    </div>
  </header>
  <main class="shell">
    {trend_panel(language, language) if page_number == 1 else ""}
    <nav class="nav">{nav}</nav>
    <nav class="pager">{pager}</nav>
    {days}
    <nav class="pager">{pager}</nav>
  </main>
</body>
</html>
"""


def render_landing_page() -> str:
    dates = candidate_dates()
    latest = dates[0] if dates else "No newsletters yet"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Engineering Newsletter</title>
  <style>{site_css()}</style>
</head>
<body>
  <main class="landing">
    <div class="landing-panel">
      <p class="eyebrow">Bilingual daily archive</p>
      <h1>AI Engineering Newsletter</h1>
      <p class="subtitle">One static public site for News Push and GitHub Trend Monitor. Latest Issued: <strong>{esc(latest)}</strong>.</p>
      <div class="landing-links">
        <a class="edition" href="en/index.html"><strong>English Edition</strong><span>Public-facing newsletter with English titles, summaries, source links, and audit metadata.</span></a>
        <a class="edition" href="zh/index.html"><strong>中文版</strong><span>中文摘要版，方便日常阅读；每天自动提醒使用这个入口。</span></a>
      </div>
      {trend_panel("en", "root")}
    </div>
  </main>
</body>
</html>
"""


def main() -> int:
    entries = archive_entries()
    total_pages = max((len(entries) + ARCHIVE_PAGE_SIZE - 1) // ARCHIVE_PAGE_SIZE, 1)
    ZH_OUT.parent.mkdir(parents=True, exist_ok=True)
    EN_OUT.parent.mkdir(parents=True, exist_ok=True)
    ROOT_OUT.write_text(render_landing_page(), encoding="utf-8")
    trend_paths = render_trend_report_pages()
    for page_number in range(1, total_pages + 1):
        zh_path = archive_page_path("zh", page_number)
        en_path = archive_page_path("en", page_number)
        zh_path.parent.mkdir(parents=True, exist_ok=True)
        en_path.parent.mkdir(parents=True, exist_ok=True)
        zh_path.write_text(render_archive_page("zh", page_number, total_pages, entries), encoding="utf-8")
        en_path.write_text(render_archive_page("en", page_number, total_pages, entries), encoding="utf-8")
    print(ROOT_OUT)
    print(ZH_OUT)
    print(EN_OUT)
    for path in trend_paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
