#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import render_digest_site as site  # noqa: E402


def item_label(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "(untitled)")
    source = str(item.get("source") or "unknown source")
    url = str(item.get("url") or "")
    return f"{source}: {title} <{url}>"


def current_sections(date_slug: str) -> dict[str, list[dict[str, Any]]]:
    site.ensure_published_selection_index()
    _data, general, engineering, medical, research, _paper_push = site.day_items(date_slug)
    return {
        "general_ai": general,
        "engineering_ai": engineering,
        "medical_bio_ai": medical,
        "research": research,
    }


def find_quality_problems(date_slug: str) -> list[str]:
    data_path = site.DIGEST_DIR / f"{date_slug}-candidates.json"
    if not data_path.exists():
        return [f"Missing candidate file: {data_path}"]

    data = site.load_json(data_path)
    run_log = data.get("run_log") or {}
    source_count = int(run_log.get("source_count") or 0)
    fetched_count = int(run_log.get("fetched_count") or 0)
    top_candidates = data.get("top_100_news_candidates") or []
    note = str(run_log.get("note") or "")

    problems: list[str] = []
    if source_count <= 0:
        problems.append(
            f"Candidate file has source_count={source_count}; this usually means the news source registry was not loaded."
        )
    if fetched_count <= 0 and not top_candidates:
        problems.append("Candidate file has no fetched records and no top news candidates.")
    if "placeholder" in note.lower():
        problems.append(f"Candidate file is marked as a placeholder: {note}")
    sections = current_sections(date_slug)
    if len(sections["general_ai"]) < 5:
        problems.append(
            f"General AI has only {len(sections['general_ai'])} publishable items; at least 5 are required."
        )
    if sum(len(items) for items in sections.values()) < 10:
        problems.append("The issue has fewer than 10 publishable items across all news sections.")
    return problems


def find_duplicates(date_slug: str, lookback_days: int) -> list[str]:
    sections = current_sections(date_slug)
    current_items: list[tuple[str, dict[str, Any]]] = [
        (section, item) for section, items in sections.items() for item in items
    ]
    problems: list[str] = []

    for idx, (left_section, left) in enumerate(current_items):
        for right_section, right in current_items[idx + 1 :]:
            if site.is_same_event(left, right):
                problems.append(
                    "Current issue duplicate: "
                    f"{left_section} {item_label(left)} == {right_section} {item_label(right)}"
                )

    historical = site.historical_published_items(date_slug, lookback_days=lookback_days)
    for section, item in current_items:
        for previous in historical:
            if site.is_same_event(item, previous):
                problems.append(
                    f"Recent-history duplicate within {lookback_days} days: "
                    f"{section} {item_label(item)} == previous {item_label(previous)}"
                )
                break

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail if a newsletter issue repeats recent published items.")
    parser.add_argument("--date", required=True, help="Issue date as YYYY-MM-DD.")
    parser.add_argument("--lookback-days", type=int, default=7)
    args = parser.parse_args()

    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print(f"Invalid --date: {args.date}", file=sys.stderr)
        return 2

    problems = find_quality_problems(args.date)
    problems.extend(find_duplicates(args.date, args.lookback_days))
    if problems:
        print(f"Pre-publish check failed for {args.date}:")
        for problem in problems:
            print(f"- {problem}")
        return 1

    print(
        f"No empty candidate file or duplicate news items found for {args.date} "
        f"against the previous {args.lookback_days} days."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
