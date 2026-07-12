#!/usr/bin/env python3
"""Build a Friday AI-for-engineering paper section from the public arXiv API."""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DIGEST_DIR = ROOT / "data" / "digests"
ARXIV_API = "https://export.arxiv.org/api/query"
USER_AGENT = "ai-engineering-newsletter/1.0 (public weekly paper discovery)"
ENGINEERING_PATTERNS = (
    r"\bcad\b", r"\bcae\b", r"\bcfd\b", r"\bfea\b", r"finite elements?",
    r"digital twins?", r"physics[- ]informed", r"neural operators?",
    r"surrogate models?", r"\bpde[- ]constrained\b", r"topology optimization",
    r"engineering design", r"fluid dynamics", r"computational mechanics",
    r"multiphysics", r"turbulence", r"computational engineering",
)
AI_PATTERNS = (
    r"artificial intelligence", r"machine learning", r"deep learning",
    r"physics[- ]informed", r"neural", r"surrogate", r"foundation model",
    r"large language model", r"reinforcement learning", r"digital twins?",
)
EXCLUDED_PATTERNS = (
    r"\bofdm\b", r"wireless", r"telecommunication", r"ultra-dense network",
    r"quantum", r"rehabilitation", r"clinical", r"biomedical",
)


def canonical_url(url: str) -> str:
    match = re.search(r"arxiv\.org/(?:abs|pdf)/(\d+\.\d+)", url)
    return f"https://arxiv.org/abs/{match.group(1)}" if match else url.split("?", 1)[0]


def previous_urls(date_slug: str, lookback_days: int = 60) -> set[str]:
    current = datetime.strptime(date_slug, "%Y-%m-%d").date()
    urls: set[str] = set()
    for path in DIGEST_DIR.glob("*-paper-push.json"):
        try:
            issue_date = datetime.strptime(path.name[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if not timedelta(0) < current - issue_date <= timedelta(days=lookback_days):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload.get("cae_papers") or []:
            urls.add(canonical_url(str(item.get("url") or "")))
    return urls


def fetch_arxiv(max_results: int = 50) -> list[dict[str, Any]]:
    query = " OR ".join(
        [
            'all:"physics informed"',
            'all:"neural operator"',
            'all:"surrogate model"',
            'all:"computational fluid dynamics"',
            'all:"finite element"',
            'all:"topology optimization"',
            'all:"digital twin"',
            'all:"engineering design"',
        ]
    )
    params = urllib.parse.urlencode(
        {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    request = urllib.request.Request(f"{ARXIV_API}?{params}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    papers: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ns):
        title = " ".join((entry.findtext("atom:title", "", ns)).split())
        summary = " ".join((entry.findtext("atom:summary", "", ns)).split())
        url = canonical_url(entry.findtext("atom:id", "", ns))
        published = entry.findtext("atom:published", "", ns)[:10]
        authors = [node.findtext("atom:name", "", ns) for node in entry.findall("atom:author", ns)]
        papers.append(
            {
                "title": title,
                "url": url,
                "source": "arXiv",
                "published": published,
                "authors": authors,
                "abstract": summary,
            }
        )
    return papers


def select_papers(papers: list[dict[str, Any]], date_slug: str, limit: int = 10) -> list[dict[str, Any]]:
    issue_date = datetime.strptime(date_slug, "%Y-%m-%d").date()
    cutoff = issue_date - timedelta(days=8)
    seen = previous_urls(date_slug)
    selected: list[dict[str, Any]] = []
    for paper in papers:
        text = f"{paper['title']} {paper['abstract']}".lower()
        if not any(re.search(pattern, text) for pattern in ENGINEERING_PATTERNS):
            continue
        if not any(re.search(pattern, text) for pattern in AI_PATTERNS):
            continue
        if any(re.search(pattern, text) for pattern in EXCLUDED_PATTERNS):
            continue
        try:
            published = date.fromisoformat(paper["published"])
        except ValueError:
            continue
        if not cutoff <= published <= issue_date:
            continue
        if paper["url"] in seen:
            continue
        abstract = paper.pop("abstract")
        paper["summary_en"] = abstract[:500]
        paper["summary_zh"] = "英文摘要：" + abstract[:500]
        paper["why"] = "Selected for direct relevance to AI-enabled engineering analysis, design, or simulation."
        selected.append(paper)
        seen.add(paper["url"])
        if len(selected) == limit:
            break
    return selected


def build_payload(date_slug: str, papers: list[dict[str, Any]]) -> dict[str, Any]:
    start = (datetime.strptime(date_slug, "%Y-%m-%d").date() - timedelta(days=8)).isoformat()
    return {
        "title_zh": "每周 AI-for-Engineering 论文推送",
        "title_en": "Weekly AI-for-Engineering Paper Push",
        "intro_zh": f"本期通过 arXiv 公开 API 检索 {start} 至 {date_slug} 的 AI for engineering 新论文。",
        "intro_en": f"This issue uses the public arXiv API to discover AI-for-engineering papers from {start} to {date_slug}.",
        "cae_sources_checked": ["arXiv public Atom API"],
        "cae_papers": papers,
        "biomedical_papers": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--force", action="store_true", help="Allow generation on a day other than Friday.")
    args = parser.parse_args()
    issue_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    if issue_date.weekday() != 4 and not args.force:
        print(json.dumps({"status": "skipped", "reason": "not Friday"}))
        return 0
    papers = select_papers(fetch_arxiv(), args.date)
    if len(papers) < 3:
        raise RuntimeError(f"Only {len(papers)} fresh engineering papers found; existing files were left unchanged.")
    output = DIGEST_DIR / f"{args.date}-paper-push.json"
    output.write_text(json.dumps(build_payload(args.date, papers), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "written", "output": str(output.relative_to(ROOT)), "papers": len(papers)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
