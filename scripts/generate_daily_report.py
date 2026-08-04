#!/usr/bin/env python3
"""Generate a deterministic daily markdown report from digest candidates."""  # noqa: EXE001

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DIGEST_DIR = ROOT / "data" / "digests"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def topic_label(item: dict[str, Any]) -> str:
    text = f"{item.get('title', '')} {item.get('text', '')}".lower()
    if any(term in text for term in ("cfd", "cae", "fea", "simulation", "surrogate", "digital twin", "physics ai")):
        return "CAE / simulation"
    if any(term in text for term in ("agent", "agentic", "workflow", "copilot")):
        return "agent workflow"
    if any(term in text for term in ("model", "llm", "benchmark", "evaluation", "reasoning")):
        return "model / evaluation"
    if any(term in text for term in ("chip", "gpu", "compute", "data center", "infrastructure")):
        return "AI infrastructure"
    if any(term in text for term in ("medical", "clinical", "pharma", "drug", "genomics", "health")):
        return "medical / bio AI"
    if any(term in text for term in ("robot", "robotics", "humanoid", "manufacturing", "industrial")):
        return "industrial / robotics"
    return "AI update"


def source_phrase(item: dict[str, Any]) -> str:
    source = str(item.get("source", "")).strip() or "该来源"
    title = str(item.get("title", "")).strip()
    if title.lower().startswith(("introducing ", "introduce ", "launch", "announcing ", "announce ")):
        return f"{source} 发布了一条新内容"
    if title.lower().startswith(("what's new", "whats new", "new in ")):
        return f"{source} 给出一条产品/平台更新"
    return f"{source} 出现一条值得跟进的更新"


def reasons_phrase(item: dict[str, Any]) -> str:
    reasons = list(item.get("score_reasons") or [])
    trimmed = reasons[:3]
    if not trimmed:
        return "入选主要因为相关性、时效性和来源优先级。"
    return "入选依据：" + "；".join(trimmed) + "。"


def summarize_item(item: dict[str, Any], section_name: str) -> tuple[str, str]:
    topic = topic_label(item)
    source_text = source_phrase(item)
    title = str(item.get("title", "")).strip() or "Untitled"
    headline = f"{source_text}，主题偏向 {topic}。"
    body = (
        f"简要总结：本条来自 {item.get('source', 'unknown')}，收录在 {section_name}。"
        f" 标题为《{title}》。{reasons_phrase(item)}"
    )
    return headline, body


def render_section(title: str, items: list[dict[str, Any]]) -> list[str]:
    lines = [f"## {title}", ""]
    if not items:
        lines.extend(["- 今日这一栏没有可发布条目，系统仍保留该 section 以避免日报断档。", ""])
        return lines
    for idx, item in enumerate(items, 1):
        headline, body = summarize_item(item, title)
        lines.extend(
            [
                f"{idx}. **{headline}**",
                f"   English source: [{item.get('title', 'Untitled')}]({item.get('url', '#')})",
                f"   {body}",
                f"   关注点：建议优先看标题、原文链接和来源，再结合 score={item.get('score', '')} 判断是否进入人工精读。",
                "",
            ]
        )
    return lines


def render_failures(failures: list[dict[str, Any]]) -> list[str]:
    if not failures:
        return []
    lines = ["## Source Failures", ""]
    for failure in failures[:20]:
        lines.append(f"- {failure.get('source', 'unknown')}: {failure.get('error', 'unknown error')}")
    lines.append("")
    return lines


def build_report(date_slug: str, payload: dict[str, Any]) -> str:
    run_log = payload.get("run_log") or {}
    lines = [
        f"# AI Engineering Daily Report - {date_slug}",
        "",
        "这是一份自动生成的日报。它保证每天有一份可读 markdown 落地；当日若候选很少，也会明确写出空结果或数据缺口，而不是静默缺席。",
        "",
        "## Run Log",
        f"- generated_at: {run_log.get('generated_at', 'unknown')}",
        f"- fetched_count: {run_log.get('fetched_count', 0)}",
        f"- filtered_count: {run_log.get('filtered_count', 0)}",
        f"- duplicate_count: {run_log.get('duplicate_count', 0)}",
        f"- source_count: {run_log.get('source_count', 0)}",
        f"- failures: {len(run_log.get('failures') or [])}",
        "",
    ]
    lines.extend(render_section("Top 10 General AI News", list(payload.get("top_10_general_ai") or [])))
    lines.extend(render_section("Top 5 Engineering AI News", list(payload.get("top_5_engineering_ai") or [])))
    lines.extend(render_section("Top 5 Medical, Medicine, and Bio/Genetics AI News", list(payload.get("top_5_medical_bio_ai") or [])))
    lines.extend(render_section("Research Radar", list(payload.get("research_radar") or [])))
    watchlist = list(payload.get("watchlist_updates") or [])
    lines.extend(["## Watchlist Updates", ""])
    if watchlist:
        for item in watchlist[:10]:
            lines.append(f"- {item.get('source', 'manual')}: {item.get('query', item.get('url', ''))}")
    else:
        lines.append("- 今日没有额外 watchlist 任务。")
    lines.extend(
        [
            "",
            "## Why It Matters",
            "",
            "- 这份日报的目标是每天都给出一个稳定落地结果，而不是只有候选 JSON。",
            "- 如果 `final.md` 存在，站点渲染会优先用它；因此这份文件也是站点上的可读日报输入。",
            "- 当日完全空跑时，日报会把空结果显式写出来，方便排查调度问题、源站故障或过滤过严。",
            "",
        ]
    )
    lines.extend(render_failures(list(run_log.get("failures") or [])))
    return "\n".join(lines).rstrip() + "\n"


def generate_report(date_slug: str) -> Path:
    candidates_path = DIGEST_DIR / f"{date_slug}-candidates.json"
    if not candidates_path.exists():
        raise FileNotFoundError(f"Missing candidates file: {candidates_path}")
    payload = load_json(candidates_path)
    output_path = DIGEST_DIR / f"{date_slug}-final.md"
    output_path.write_text(build_report(date_slug, payload), encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()
    output_path = generate_report(args.date)
    print(json.dumps({"output": str(output_path.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
