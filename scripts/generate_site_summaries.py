#!/usr/bin/env python3
"""Generate cached Chinese news summaries for one published digest date."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]
DIGEST_DIR = ROOT / "data" / "digests"
CACHE_PATH = DIGEST_DIR / "site_summaries.json"
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


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def candidate_dates() -> list[str]:
    dates = []
    for path in DIGEST_DIR.glob("*-candidates.json"):
        dates.append(path.name.removesuffix("-candidates.json"))
    return sorted(dates, reverse=True)


def canonical_category(category: str) -> str:
    if category in {"engineering_ai", "cae_ai_engineering"}:
        return "engineering_ai"
    return category


def event_tokens(title: str) -> set[str]:
    title = re.sub(r"\s+-\s+[^-]+$", "", title.lower())
    return {
        token
        for token in re.findall(r"[a-z0-9]+", title)
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


def is_same_event(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_key = canonical_event_key(left.get("title", ""))
    right_key = canonical_event_key(right.get("title", ""))
    if left_key and left_key == right_key:
        return True
    left_tokens = event_tokens(left.get("title", ""))
    right_tokens = event_tokens(right.get("title", ""))
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
        "ended the world",
    }
    return any(term in text for term in excluded_terms)


def select_unique(items: list[dict[str, Any]], category: str, limit: int) -> list[dict[str, Any]]:
    category = canonical_category(category)
    max_per_topic = 2
    selected: list[dict[str, Any]] = []
    topic_counts: dict[str, int] = {}
    for item in items:
        if canonical_category(item.get("category", "")) != category:
            continue
        if is_excluded(item, category):
            continue
        if any(is_same_event(item, existing) for existing in selected):
            continue
        topic = topic_key(item)
        if topic_counts.get(topic, 0) >= max_per_topic:
            continue
        selected.append(item)
        topic_counts[topic] = topic_counts.get(topic, 0) + 1
        if len(selected) == limit:
            break
    for item in items:
        if len(selected) == limit:
            break
        if canonical_category(item.get("category", "")) != category:
            continue
        if is_excluded(item, category):
            continue
        if item in selected or any(is_same_event(item, existing) for existing in selected):
            continue
        selected.append(item)
    return selected


def selected_items(date_slug: str) -> list[dict[str, str]]:
    from scripts import render_digest_site as site

    site.ensure_published_selection_index()
    _data, general, engineering, medical, _research, _paper_push = site.day_items(date_slug)
    rows: list[dict[str, str]] = []
    for section, items in (
        ("general_ai", general),
        ("engineering_ai", engineering),
        ("medical_bio_ai", medical),
    ):
        for item in items:
            rows.append(
                {
                    "date": date_slug,
                    "section": section,
                    "id": item.get("id") or item.get("url", ""),
                    "title": item.get("title", ""),
                    "source": item.get("source", ""),
                    "text": item.get("text", "")[:1100],
                }
            )
    return rows


def make_prompt(batch: list[dict[str, str]]) -> str:
    return (
        "为下面每条英文 AI 新闻写 2-4 句中文摘要。摘要必须直接说明发生了什么、关键事实或数据、"
        "以及它对行业或工程实践的重要性。每条约 80-160 个中文字符，准确、克制，不要编造，"
        "不要使用‘值得跟进’、‘主题偏向’、‘建议关注’、‘出现一条更新’等空泛模板。"
        "如果输入只是市场观点而非技术进展，要明确说明；如果材料不足，不要补充输入中没有的事实。"
        "只返回 JSON 数组，每个对象包含 id 和 zh_summary。\n\n"
        + json.dumps(batch, ensure_ascii=False)
    )


def parse_json_array(text: str) -> list[dict[str, str]]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    return json.loads(text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="Digest date as YYYY-MM-DD; defaults to latest available date.")
    parser.add_argument("--force", action="store_true", help="Regenerate summaries already present in the cache.")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    dates = candidate_dates()
    date_slug = args.date or (dates[0] if dates else datetime.now().strftime("%Y-%m-%d"))
    if date_slug not in dates:
        raise FileNotFoundError(f"No candidate digest found for {date_slug}")
    cache = load_json(CACHE_PATH) if CACHE_PATH.exists() else {}
    rows = selected_items(date_slug)
    missing = rows if args.force else [row for row in rows if row["id"] not in cache]
    if not missing:
        print(f"no missing summaries for {date_slug}; cache={CACHE_PATH}")
        return 0

    client = OpenAI()
    for start in range(0, len(missing), 10):
        batch = missing[start : start + 10]
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是严谨的中文科技新闻编辑，只输出有效 JSON。"},
                {"role": "user", "content": make_prompt(batch)},
            ],
            temperature=0.2,
            max_completion_tokens=4000,
        )
        content = response.choices[0].message.content or "[]"
        for row in parse_json_array(content):
            if row.get("id") and row.get("zh_summary"):
                cache[row["id"]] = row["zh_summary"].strip()
        write_json(CACHE_PATH, cache)
        print(f"cached {min(start + len(batch), len(missing))}/{len(missing)}")

    print(CACHE_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
