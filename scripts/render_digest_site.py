#!/usr/bin/env python3
"""Render the bilingual AI engineering newsletter as a static HTML site."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DIGEST_DIR = ROOT / "data" / "digests"
SITE_DIR = ROOT / "site"
ROOT_OUT = SITE_DIR / "index.html"
ZH_OUT = SITE_DIR / "zh" / "index.html"
EN_OUT = SITE_DIR / "en" / "index.html"
SUMMARY_CACHE = DIGEST_DIR / "site_summaries.json"


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


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def format_date(date_slug: str) -> str:
    try:
        return datetime.strptime(date_slug, "%Y-%m-%d").strftime("%A, %B %d, %Y")
    except ValueError:
        return date_slug


def canonical_category(category: str) -> str:
    if category in {"engineering_ai", "cae_ai_engineering"}:
        return "engineering_ai"
    return category


def load_summaries() -> dict[str, str]:
    if not SUMMARY_CACHE.exists():
        return {}
    return load_json(SUMMARY_CACHE)


def parse_final_sections(markdown: str) -> dict[str, list[dict[str, str]]]:
    sections = {"general_ai": [], "engineering_ai": []}
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
    for key in ("top_100_news_candidates", "top_10_general_ai", "top_5_engineering_ai", "top_5_cae_ai_engineering"):
        for item in data.get(key, []):
            if item.get("url") == url:
                return item
    return None


def hydrate_final_items(data: dict[str, Any], final_path: Path) -> dict[str, list[dict[str, Any]]]:
    parsed = parse_final_sections(final_path.read_text(encoding="utf-8"))
    hydrated: dict[str, list[dict[str, Any]]] = {"general_ai": [], "engineering_ai": []}
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
    left_tokens = event_tokens(left.get("title", ""))
    right_tokens = event_tokens(right.get("title", ""))
    if not left_tokens or not right_tokens:
        return False
    intersection = left_tokens & right_tokens
    smaller = min(len(left_tokens), len(right_tokens))
    union = left_tokens | right_tokens
    return (len(intersection) >= 5 and len(intersection) / max(smaller, 1) >= 0.5) or (
        len(intersection) >= 4 and len(intersection) / max(len(union), 1) >= 0.42
    )


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


def select_unique(items: list[dict[str, Any]], category: str, limit: int) -> list[dict[str, Any]]:
    category = canonical_category(category)
    selected: list[dict[str, Any]] = []
    topic_counts: dict[str, int] = {}
    for item in items:
        if canonical_category(item.get("category", "")) != category or is_excluded(item, category):
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
    for item in items:
        if len(selected) == limit:
            break
        if canonical_category(item.get("category", "")) != category or is_excluded(item, category):
            continue
        if item in selected or any(is_same_event(item, existing) for existing in selected):
            continue
        selected.append(item)
    return selected


def section_items(data: dict[str, Any], category: str, limit: int, fallback_key: str) -> list[dict[str, Any]]:
    pool = data.get("top_100_news_candidates", [])
    selected = select_unique(pool, category, limit)
    if len(selected) >= limit:
        return selected
    for item in data.get(fallback_key, []):
        item = dict(item)
        item["category"] = canonical_category(item.get("category", category))
        if any(is_same_event(item, existing) for existing in selected):
            continue
        selected.append(item)
        if len(selected) == limit:
            break
    return selected


def day_items(date_slug: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    data = load_json(DIGEST_DIR / f"{date_slug}-candidates.json")
    final_path = DIGEST_DIR / f"{date_slug}-final.md"
    if final_path.exists():
        final_items = hydrate_final_items(data, final_path)
        return data, final_items["general_ai"], final_items["engineering_ai"]
    return (
        data,
        section_items(data, "general_ai", 10, "top_10_general_ai"),
        section_items(data, "engineering_ai", 5, "top_5_engineering_ai"),
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
          <div class="meta"><span>{esc(item.get("source", "unknown"))}</span><span>score {esc(item.get("score", ""))}</span></div>
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
          <div class="meta"><span>{esc(item.get("source", "unknown"))}</span><span>score {esc(item.get("score", ""))}</span></div>
          <p class="reason">{esc("; ".join(item.get("score_reasons", [])[:2]))}</p>
        </div>
      </article>
    """


def render_day_zh(date_slug: str, summaries: dict[str, str]) -> str:
    data, general, cae = day_items(date_slug)
    return render_day_shell(
        date_slug,
        data,
        "AI Top 10",
        "Engineering AI Top 5",
        "".join(item_card_zh(item, idx, summaries) for idx, item in enumerate(general, 1)),
        "".join(item_card_zh(item, idx, summaries) for idx, item in enumerate(cae, 1)),
    )


def render_day_en(date_slug: str) -> str:
    data, general, cae = day_items(date_slug)
    return render_day_shell(
        date_slug,
        data,
        "Top 10 General AI News",
        "Top 5 Engineering AI News",
        "".join(item_card_en(item, idx) for idx, item in enumerate(general, 1)),
        "".join(item_card_en(item, idx) for idx, item in enumerate(cae, 1)),
    )


def render_day_shell(date_slug: str, data: dict[str, Any], general_title: str, engineering_title: str, general_html: str, engineering_html: str) -> str:
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
        <section>
          <h3>{esc(engineering_title)}</h3>
          {engineering_html}
        </section>
      </div>
    </section>
    """


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
    .nav, .language-switch { display: flex; gap: 8px; flex-wrap: wrap; margin: 24px 0 28px; }
    .nav a, .language-switch a { color: var(--ink); border: 1px solid var(--line); padding: 7px 10px; text-decoration: none; background: rgba(255,255,255,.55); }
    .language-switch a.active { background: var(--ink); color: var(--panel); border-color: var(--ink); }
    .day { background: var(--panel); border: 1px solid var(--line); box-shadow: var(--shadow); margin: 28px 0; padding: 24px; }
    .day-head { display: flex; justify-content: space-between; gap: 20px; border-bottom: 2px solid var(--ink); padding-bottom: 16px; margin-bottom: 22px; }
    .eyebrow { margin: 0 0 5px; color: var(--accent-2); font-size: 13px; text-transform: uppercase; letter-spacing: .08em; font-family: "Avenir Next", Verdana, sans-serif; }
    h2 { margin: 0; font-size: 38px; }
    h3 { margin: 0 0 14px; font-size: 21px; font-family: "Avenir Next", Verdana, sans-serif; }
    .audit { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; align-content: start; }
    .audit span { border: 1px solid var(--line); padding: 7px 10px; color: var(--muted); font-family: "Avenir Next", Verdana, sans-serif; font-size: 13px; }
    .columns { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(300px, .85fr); gap: 24px; }
    .item { display: grid; grid-template-columns: 42px 1fr; gap: 12px; padding: 15px 0; border-top: 1px solid var(--line); }
    .rank { font-family: "Avenir Next", Verdana, sans-serif; color: var(--accent); font-weight: 700; }
    h4 { margin: 0; font-size: 18px; line-height: 1.25; }
    .zh-summary { margin: 0 0 7px; font-size: 18px; line-height: 1.38; font-weight: 700; color: var(--ink); }
    .en-summary { margin: 8px 0 0; font-size: 15px; line-height: 1.46; color: var(--muted); }
    a { color: var(--ink); text-decoration-color: color-mix(in srgb, var(--accent), transparent 40%); text-underline-offset: 3px; }
    .meta { margin-top: 7px; display: flex; flex-wrap: wrap; gap: 8px; font-family: "Avenir Next", Verdana, sans-serif; font-size: 12px; color: var(--muted); }
    .meta span { border: 1px solid var(--line); padding: 4px 7px; }
    .reason { margin: 8px 0 0; color: var(--muted); font-size: 14px; line-height: 1.4; }
    .landing { min-height: 100vh; display: grid; align-items: center; }
    .landing-panel { max-width: 980px; margin: 0 auto; padding: 44px 22px; }
    .landing h1 { font-size: clamp(38px, 7vw, 86px); }
    .landing-links { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 34px; }
    .edition { display: block; border: 1px solid var(--line); background: var(--panel); padding: 24px; text-decoration: none; box-shadow: var(--shadow); }
    .edition strong { display: block; font-size: 28px; margin-bottom: 8px; }
    .edition span { color: var(--muted); line-height: 1.45; }
    @media (max-width: 860px) {
      .hero-inner, .day-head, .columns, .landing-links { grid-template-columns: 1fr; }
      .stamp { text-align: left; }
      .day { padding: 18px; }
      h2 { font-size: 30px; }
    }
  """


def render_archive_page(language: str) -> str:
    dates = candidate_dates()
    summaries = load_summaries()
    latest = dates[0] if dates else "No newsletters yet"
    nav = "".join(f'<a href="#{esc(date)}">{esc(date)}</a>' for date in dates[:20])
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    if language == "zh":
        lang_attr = "zh-CN"
        title = "AI Engineering Newsletter 中文版"
        subtitle = "每日 General AI 与 Engineering AI 中文汇总。覆盖 CAE、CAD、simulation、digital twin、industrial AI 与 scientific ML；最新日期在最上面。"
        switch = '<a class="active" href="../zh/">中文版</a><a href="../en/">English</a>'
        days = "\n".join(render_day_zh(date, summaries) for date in dates)
    else:
        lang_attr = "en"
        title = "AI Engineering Newsletter"
        subtitle = "A daily English newsletter on general AI and engineering AI, covering CAE, CAD, simulation, digital twins, industrial AI, and scientific ML."
        switch = '<a href="../zh/">中文版</a><a class="active" href="../en/">English</a>'
        days = "\n".join(render_day_en(date) for date in dates)
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
      <div class="stamp">Latest<br><strong>{esc(latest)}</strong><br>Generated {esc(generated)}</div>
    </div>
  </header>
  <main class="shell">
    <nav class="nav">{nav}</nav>
    {days}
  </main>
</body>
</html>
"""


def render_landing_page() -> str:
    dates = candidate_dates()
    latest = dates[0] if dates else "No newsletters yet"
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
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
      <p class="subtitle">Daily coverage of general AI and engineering AI, including CAE, CAD, simulation, digital twins, industrial AI, and scientific ML. Latest issue: <strong>{esc(latest)}</strong>. Generated {esc(generated)}.</p>
      <div class="landing-links">
        <a class="edition" href="en/"><strong>English Edition</strong><span>Public-facing newsletter with English titles, summaries, source links, and audit metadata.</span></a>
        <a class="edition" href="zh/"><strong>中文版</strong><span>中文摘要版，方便日常阅读；每天自动提醒使用这个入口。</span></a>
      </div>
    </div>
  </main>
</body>
</html>
"""


def main() -> int:
    ZH_OUT.parent.mkdir(parents=True, exist_ok=True)
    EN_OUT.parent.mkdir(parents=True, exist_ok=True)
    ROOT_OUT.write_text(render_landing_page(), encoding="utf-8")
    ZH_OUT.write_text(render_archive_page("zh"), encoding="utf-8")
    EN_OUT.write_text(render_archive_page("en"), encoding="utf-8")
    print(ROOT_OUT)
    print(ZH_OUT)
    print(EN_OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
