"""Output renderers (Goal 7).

Each module here turns a pipeline artifact into a human-readable file:

- :mod:`newsletter.reports.daily` — ``*-candidates.json`` → ``*-final.md``
  (the deterministic daily Markdown report, PROJECT.md §3.11).
"""

from .daily import (
    build_report,
    final_report_path,
    generate_report,
    render_failures,
    render_section,
    source_phrase,
    summarize_item,
    topic_label,
)

__all__ = [
    "build_report",
    "final_report_path",
    "generate_report",
    "render_failures",
    "render_section",
    "source_phrase",
    "summarize_item",
    "topic_label",
]
