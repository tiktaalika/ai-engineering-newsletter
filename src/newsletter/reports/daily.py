"""Daily report generator — ``*-candidates.json`` → ``*-final.md`` (Goal 7.1).

Port of v1 ``scripts/generate_daily_report.py`` (PROJECT.md §3.11).  The
report is deliberately deterministic and templated: every day — even a day
with zero candidates — produces a readable Markdown file, so downstream
consumers (site renderer, LLM summary step, humans) never face a missing
issue.

The generator reads the **candidates JSON payload**, not typed models: the
``*-candidates.json`` schema is the cross-version interface (Goal 8.4), so
rendering from the dict guarantees byte-compatible output whether the
artifact was written by v1 or v2.  Chinese filler text is carried over
verbatim — the v1 report is bilingual by design (Chinese narration around
English sources, PROJECT.md §1).
"""

from __future__ import annotations

import json
import logging
from datetime import date as date_type
from pathlib import Path
from typing import Any

from ..artifacts import CANDIDATES_SUFFIX

logger = logging.getLogger(__name__)

#: Suffix of the generated report, e.g. ``2026-06-17-final.md``.
FINAL_SUFFIX: str = "-final.md"

#: Watchlist lines rendered per report (v1 parity).
_WATCHLIST_LIMIT: int = 10

#: Source failure lines rendered per report (v1 parity).
_FAILURE_LIMIT: int = 20

#: Title prefixes that read as a product launch in :func:`source_phrase`.
_LAUNCH_PREFIXES: tuple[str, ...] = (
    "introducing ",
    "introduce ",
    "launch",
    "announcing ",
    "announce ",
)

#: Title prefixes that read as a product/platform update in :func:`source_phrase`.
_UPDATE_PREFIXES: tuple[str, ...] = ("what's new", "whats new", "new in ")


# --------------------------------------------------------------------------- #
# Label + phrase inference
# --------------------------------------------------------------------------- #


def topic_label(item: dict[str, Any]) -> str:
    """Infer a human topic label from ``"{title} {text}"`` (v1 parity).

    The first matching term family wins, checked in a fixed order so the
    label is deterministic: CAE/simulation signals rank above generic
    agent/model chatter.
    """
    text = f"{item.get('title', '')} {item.get('text', '')}".lower()
    if any(
        term in text
        for term in (
            "cfd",
            "cae",
            "fea",
            "simulation",
            "surrogate",
            "digital twin",
            "physics ai",
        )
    ):
        return "CAE / simulation"
    if any(term in text for term in ("agent", "agentic", "workflow", "copilot")):
        return "agent workflow"
    if any(
        term in text
        for term in ("model", "llm", "benchmark", "evaluation", "reasoning")
    ):
        return "model / evaluation"
    if any(
        term in text
        for term in ("chip", "gpu", "compute", "data center", "infrastructure")
    ):
        return "AI infrastructure"
    if any(
        term in text
        for term in ("medical", "clinical", "pharma", "drug", "genomics", "health")
    ):
        return "medical / bio AI"
    if any(
        term in text
        for term in ("robot", "robotics", "humanoid", "manufacturing", "industrial")
    ):
        return "industrial / robotics"
    return "AI update"


def source_phrase(item: dict[str, Any]) -> str:
    """Narrate *what kind of* update the source published (v1 parity)."""
    source = str(item.get("source", "")).strip() or "该来源"
    title = str(item.get("title", "")).strip()
    if title.lower().startswith(_LAUNCH_PREFIXES):
        return f"{source} 发布了一条新内容"
    if title.lower().startswith(_UPDATE_PREFIXES):
        return f"{source} 给出一条产品/平台更新"
    return f"{source} 出现一条值得跟进的更新"


def reasons_phrase(item: dict[str, Any]) -> str:
    """Render the top score reasons as a selection rationale (v1 parity)."""
    reasons = list(item.get("score_reasons") or [])
    trimmed = reasons[:3]
    if not trimmed:
        return "入选主要因为相关性、时效性和来源优先级。"
    return "入选依据：" + "；".join(trimmed) + "。"


def summarize_item(item: dict[str, Any], section_name: str) -> tuple[str, str]:
    """Build the ``(headline, body)`` pair for one list entry (v1 parity)."""
    topic = topic_label(item)
    source_text = source_phrase(item)
    title = str(item.get("title", "")).strip() or "Untitled"
    headline = f"{source_text}，主题偏向 {topic}。"
    body = (
        f"简要总结：本条来自 {item.get('source', 'unknown')}，收录在 {section_name}。"
        f" 标题为《{title}》。{reasons_phrase(item)}"
    )
    return headline, body


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def render_section(title: str, items: list[dict[str, Any]]) -> list[str]:
    """Render one numbered section; empty sections stay visible (v1 parity)."""
    lines = [f"## {title}", ""]
    if not items:
        lines.extend(
            ["- 今日这一栏没有可发布条目，系统仍保留该 section 以避免日报断档。", ""]
        )
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
    """Render the trailing ``## Source Failures`` block (absent when empty)."""
    if not failures:
        return []
    lines = ["## Source Failures", ""]
    for failure in failures[:_FAILURE_LIMIT]:
        lines.append(
            f"- {failure.get('source', 'unknown')}: {failure.get('error', 'unknown error')}"
        )
    lines.append("")
    return lines


def build_report(date_slug: str, payload: dict[str, Any]) -> str:
    """Compose the full ``*-final.md`` content from a candidates payload.

    The section headings and order are v1's contract with the site renderer:
    Run Log → Top 10 General AI News → Top 5 Engineering AI News →
    Top 5 Medical, Medicine, and Bio/Genetics AI News → Research Radar →
    Watchlist Updates → Why It Matters → Source Failures (only when the run
    had failures).
    """
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
    lines.extend(
        render_section(
            "Top 10 General AI News", list(payload.get("top_10_general_ai") or [])
        )
    )
    lines.extend(
        render_section(
            "Top 5 Engineering AI News",
            list(payload.get("top_5_engineering_ai") or []),
        )
    )
    lines.extend(
        render_section(
            "Top 5 Medical, Medicine, and Bio/Genetics AI News",
            list(payload.get("top_5_medical_bio_ai") or []),
        )
    )
    lines.extend(
        render_section("Research Radar", list(payload.get("research_radar") or []))
    )
    watchlist = list(payload.get("watchlist_updates") or [])
    lines.extend(["## Watchlist Updates", ""])
    if watchlist:
        for item in watchlist[:_WATCHLIST_LIMIT]:
            lines.append(
                f"- {item.get('source', 'manual')}: {item.get('query', item.get('url', ''))}"
            )
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


# --------------------------------------------------------------------------- #
# File handling
# --------------------------------------------------------------------------- #


def final_report_path(digest_dir: Path, date_slug: str) -> Path:
    """Report path for a run date (``YYYY-MM-DD-final.md``)."""
    return digest_dir / f"{date_slug}{FINAL_SUFFIX}"


def generate_report(date_slug: str, digest_dir: Path) -> Path:
    """Read ``{date_slug}-candidates.json`` and write ``{date_slug}-final.md``.

    Raises
    ------
    ValueError
        If ``date_slug`` is not a ``YYYY-MM-DD`` date.
    FileNotFoundError
        If the candidates artifact does not exist.
    """
    try:
        date_type.fromisoformat(date_slug)
    except ValueError:
        raise ValueError(f"Invalid date slug: {date_slug!r}") from None

    candidates_file = digest_dir / f"{date_slug}{CANDIDATES_SUFFIX}"
    if not candidates_file.exists():
        raise FileNotFoundError(f"Missing candidates file: {candidates_file}")

    payload = json.loads(candidates_file.read_text(encoding="utf-8"))
    output_path = final_report_path(digest_dir, date_slug)
    output_path.write_text(build_report(date_slug, payload), encoding="utf-8")
    logger.info("Wrote daily report: %s", output_path)
    return output_path
