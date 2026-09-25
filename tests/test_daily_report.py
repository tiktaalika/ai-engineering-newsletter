"""Tests for the daily report generator (Goal 7.1 / test plan 2.5).

Covers Markdown structure, section headings, topic labels, the Chinese
phrase helpers, failure/watchlist rendering, the file round-trip and the
``newsletter report`` CLI — all against v1's exact output contract
(``scripts/generate_daily_report.py`` on ``main``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from newsletter.artifacts import write_candidates_json
from newsletter.main import app
from newsletter.models import DigestIssue, RunLog, ScoreBreakdown
from newsletter.reports.daily import (
    build_report,
    final_report_path,
    generate_report,
    reasons_phrase,
    render_failures,
    render_section,
    source_phrase,
    summarize_item,
    topic_label,
)

runner = CliRunner()

DATE_SLUG = "2026-06-17"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _payload_with_run_log(**overrides: object) -> dict:
    """A minimal candidates payload with only the run log populated."""
    run_log: dict = {
        "generated_at": "2026-06-17T07:02:35+00:00",
        "window_hours": 24,
        "source_count": 0,
        "fetched_count": 0,
        "filtered_count": 0,
        "duplicate_count": 0,
        "failures": [],
    }
    run_log.update(overrides)
    return {"run_log": run_log}


def _write_artifact(
    digest_dir: Path,
    make_candidate,
    *,
    failures: list[dict[str, str]] | None = None,
) -> Path:
    """Write a real ``*-candidates.json`` via the production serializer."""
    candidates = [
        make_candidate(
            title="Introducing a new LLM benchmark",
            url=f"https://example.com/story-{i}",
            text="A model evaluation of reasoning.",
            score=10.0 + i,
            breakdown=ScoreBreakdown(
                score=10.0 + i,
                source_priority=1.0,
                novelty=0.5,
                general_relevance=0.2,
            ),
            matched_terms=["LLM", "benchmark"],
        )
        for i in range(3)
    ]
    run_log = RunLog(
        generated_at=datetime(2026, 6, 17, 7, 2, 35, tzinfo=UTC),
        failures=failures or [],
    )
    issue = DigestIssue(
        run_log=run_log,
        top_10_general_ai=candidates,
        top_5_engineering_ai=candidates[:1],
    )
    return write_candidates_json(issue, digest_dir / f"{DATE_SLUG}-candidates.json")


# --------------------------------------------------------------------------- #
# topic_label
# --------------------------------------------------------------------------- #


class TestTopicLabel:
    def test_cae_terms(self):
        assert topic_label({"title": "New solver", "text": "CFD and FEA study"}) == (
            "CAE / simulation"
        )

    def test_cae_prefers_simulation_family_over_agent(self):
        # "cfd" is checked before "agent" — CAE wins on overlap.
        assert topic_label({"title": "Agentic CFD", "text": ""}) == "CAE / simulation"

    @pytest.mark.parametrize("fragment", ["agent", "agentic", "workflow", "copilot"])
    def test_agent_workflow_terms(self, fragment: str):
        assert topic_label({"title": fragment, "text": ""}) == "agent workflow"

    @pytest.mark.parametrize("fragment", ["model", "llm", "benchmark", "reasoning"])
    def test_model_evaluation_terms(self, fragment: str):
        assert topic_label({"title": fragment, "text": ""}) == "model / evaluation"

    @pytest.mark.parametrize("fragment", ["chip", "gpu", "data center"])
    def test_infrastructure_terms(self, fragment: str):
        assert topic_label({"title": fragment, "text": ""}) == "AI infrastructure"

    @pytest.mark.parametrize("fragment", ["medical", "clinical", "genomics"])
    def test_medical_terms(self, fragment: str):
        assert topic_label({"title": fragment, "text": ""}) == "medical / bio AI"

    @pytest.mark.parametrize("fragment", ["robot", "humanoid", "manufacturing"])
    def test_industrial_terms(self, fragment: str):
        assert topic_label({"title": fragment, "text": ""}) == "industrial / robotics"

    def test_fallback_label(self):
        assert topic_label({"title": "Quarterly earnings", "text": "up 3%"}) == (
            "AI update"
        )

    def test_missing_fields_fall_back(self):
        assert topic_label({}) == "AI update"

    def test_label_is_case_insensitive(self):
        assert topic_label({"title": "SIMULATION breakthrough", "text": ""}) == (
            "CAE / simulation"
        )

    def test_v1_sample_prefers_cae_signals(self):
        # Ported from v1 test_generate_daily_report.py.
        item = {
            "title": "Open-source AI Datasets for AI Physics Model Training",
            "text": "simulation CFD surrogate model dataset",
        }
        assert topic_label(item) == "CAE / simulation"


# --------------------------------------------------------------------------- #
# source_phrase / reasons_phrase / summarize_item
# --------------------------------------------------------------------------- #


class TestSourcePhrase:
    @pytest.mark.parametrize(
        "title",
        ["Introducing GPT-9", "introduce a new tool", "Launch day", "Announcing X"],
    )
    def test_launch_prefixes(self, title: str):
        assert source_phrase({"title": title, "source": "Blog"}) == (
            "Blog 发布了一条新内容"
        )

    @pytest.mark.parametrize(
        "title", ["What's new in 2.0", "whats new this week", "New in v3"]
    )
    def test_update_prefixes(self, title: str):
        assert source_phrase({"title": title, "source": "Blog"}) == (
            "Blog 给出一条产品/平台更新"
        )

    def test_default_phrase(self):
        assert source_phrase({"title": "Quarterly results", "source": "Reuters"}) == (
            "Reuters 出现一条值得跟进的更新"
        )

    def test_blank_source_uses_placeholder(self):
        assert source_phrase({"title": "Anything", "source": "  "}) == (
            "该来源 出现一条值得跟进的更新"
        )


class TestReasonsPhrase:
    def test_no_reasons_falls_back(self):
        assert reasons_phrase({"score_reasons": []}) == (
            "入选主要因为相关性、时效性和来源优先级。"
        )
        assert reasons_phrase({}) == "入选主要因为相关性、时效性和来源优先级。"

    def test_reasons_joined_with_chinese_semicolon(self):
        reasons = ["a", "b", "c", "d"]
        assert reasons_phrase({"score_reasons": reasons}) == "入选依据：a；b；c。"

    def test_reasons_trimmed_to_three(self):
        assert reasons_phrase({"score_reasons": ["x", "y"]}) == "入选依据：x；y。"


class TestSummarizeItem:
    def test_headline_and_body_composition(self):
        item = {
            "title": "Launch of something",
            "text": "body text",
            "source": "Blog",
            "url": "https://example.com/a",
        }
        headline, body = summarize_item(item, "Top 10 General AI News")
        assert headline == "Blog 发布了一条新内容，主题偏向 AI update。"
        assert body == (
            "简要总结：本条来自 Blog，收录在 Top 10 General AI News。"
            " 标题为《Launch of something》。"
            "入选主要因为相关性、时效性和来源优先级。"
        )

    def test_empty_title_becomes_untitled(self):
        _headline, body = summarize_item({"title": "", "source": "S"}, "Section")
        assert "《Untitled》" in body


# --------------------------------------------------------------------------- #
# render_section / render_failures
# --------------------------------------------------------------------------- #


class TestRenderSection:
    def test_empty_section_keeps_placeholder(self):
        lines = render_section("Research Radar", [])
        assert lines == [
            "## Research Radar",
            "",
            "- 今日这一栏没有可发布条目，系统仍保留该 section 以避免日报断档。",
            "",
        ]

    def test_numbered_entries_with_link_and_body(self):
        item = {"title": "T", "url": "https://e.com/1", "source": "S", "score": 12.5}
        lines = render_section("Top 10 General AI News", [item])
        assert lines[0] == "## Top 10 General AI News"
        assert lines[2].startswith(
            "1. **S 出现一条值得跟进的更新，主题偏向 AI update。**"
        )
        assert lines[3] == "   English source: [T](https://e.com/1)"
        assert "   关注点：建议优先看标题、原文链接和来源" in lines[5]
        assert "score=12.5" in lines[5]

    def test_multiple_items_are_numbered(self):
        items = [
            {"title": f"t{i}", "url": f"https://e.com/{i}", "source": "S"}
            for i in range(4)
        ]
        lines = render_section("Research Radar", items)
        for i in range(4):
            assert lines[2 + i * 5].startswith(f"{i + 1}. **")


class TestRenderFailures:
    def test_no_failures_renders_nothing(self):
        assert render_failures([]) == []

    def test_failures_rendered_as_bullet_list(self):
        failures = [{"source": "Blog", "error": "HTTP 503"}]
        assert render_failures(failures) == [
            "## Source Failures",
            "",
            "- Blog: HTTP 503",
            "",
        ]

    def test_failures_capped_at_twenty(self):
        failures = [{"source": f"s{i}", "error": "boom"} for i in range(25)]
        lines = render_failures(failures)
        assert len(lines) == 2 + 20 + 1
        assert "- s19: boom" in lines
        assert "- s20: boom" not in lines


# --------------------------------------------------------------------------- #
# build_report
# --------------------------------------------------------------------------- #


class TestBuildReport:
    def test_empty_run_renders_every_section(self):
        # Ported from v1 test_generate_daily_report.py.
        report = build_report(DATE_SLUG, _payload_with_run_log())
        assert f"# AI Engineering Daily Report - {DATE_SLUG}" in report
        assert "今日这一栏没有可发布条目" in report
        assert "## Why It Matters" in report

    def test_section_order_and_headings(self):
        report = build_report(DATE_SLUG, _payload_with_run_log())
        positions = [
            report.index(h)
            for h in (
                "## Run Log",
                "## Top 10 General AI News",
                "## Top 5 Engineering AI News",
                "## Top 5 Medical, Medicine, and Bio/Genetics AI News",
                "## Research Radar",
                "## Watchlist Updates",
                "## Why It Matters",
            )
        ]
        assert positions == sorted(positions)

    def test_run_log_fields_rendered(self):
        payload = _payload_with_run_log(
            fetched_count=120,
            filtered_count=95,
            duplicate_count=7,
            source_count=30,
        )
        report = build_report(DATE_SLUG, payload)
        assert "- generated_at: 2026-06-17T07:02:35+00:00" in report
        assert "- fetched_count: 120" in report
        assert "- filtered_count: 95" in report
        assert "- duplicate_count: 7" in report
        assert "- source_count: 30" in report
        assert "- failures: 0" in report

    def test_empty_watchlist_message(self):
        report = build_report(DATE_SLUG, _payload_with_run_log())
        assert "- 今日没有额外 watchlist 任务。" in report

    def test_watchlist_lines_capped_at_ten(self):
        payload = _payload_with_run_log()
        payload["watchlist_updates"] = [
            {"source": f"site{i}", "query": f"q{i}"} for i in range(15)
        ]
        report = build_report(DATE_SLUG, payload)
        assert "- site0: q0" in report
        assert "- site9: q9" in report
        assert "- site10: q10" not in report

    def test_watchlist_falls_back_to_url(self):
        payload = _payload_with_run_log()
        payload["watchlist_updates"] = [{"source": "site", "url": "https://e.com"}]
        assert "- site: https://e.com" in build_report(DATE_SLUG, payload)

    def test_failures_count_and_block(self):
        payload = _payload_with_run_log()
        payload["run_log"]["failures"] = [
            {"source": "Blog", "error": "timeout"},
            {"source": "Wire", "error": "HTTP 429"},
        ]
        report = build_report(DATE_SLUG, payload)
        assert "- failures: 2" in report
        assert "## Source Failures" in report
        assert "- Blog: timeout" in report
        assert "- Wire: HTTP 429" in report
        # Failures block is last — nothing after it but whitespace.
        assert report.rstrip().endswith("- Wire: HTTP 429")

    def test_no_failures_section_when_clean(self):
        report = build_report(DATE_SLUG, _payload_with_run_log())
        assert "## Source Failures" not in report

    def test_missing_run_log_defaults(self):
        report = build_report(DATE_SLUG, {})
        assert "- generated_at: unknown" in report
        assert "- failures: 0" in report

    def test_ends_with_single_newline(self):
        report = build_report(DATE_SLUG, _payload_with_run_log())
        assert report.endswith("\n")
        assert not report.endswith("\n\n")


# --------------------------------------------------------------------------- #
# generate_report (file round-trip)
# --------------------------------------------------------------------------- #


class TestGenerateReport:
    def test_round_trip_from_real_artifact(self, tmp_path: Path, make_candidate):
        candidates_file = _write_artifact(tmp_path, make_candidate)
        assert candidates_file.exists()

        output = generate_report(DATE_SLUG, tmp_path)
        assert output == final_report_path(tmp_path, DATE_SLUG)
        assert output.name == f"{DATE_SLUG}-final.md"

        payload = json.loads(candidates_file.read_text(encoding="utf-8"))
        assert output.read_text(encoding="utf-8") == build_report(DATE_SLUG, payload)
        # Real candidates produced score reasons — the rationale must show up.
        assert "入选依据：source_priority=" in output.read_text(encoding="utf-8")

    def test_general_and_engineering_sections_populated(
        self, tmp_path: Path, make_candidate
    ):
        _write_artifact(tmp_path, make_candidate)
        output = generate_report(DATE_SLUG, tmp_path)
        report = output.read_text(encoding="utf-8")
        general = report.split("## Top 10 General AI News", 1)[1].split(
            "## Top 5 Engineering AI News", 1
        )[0]
        engineering = report.split("## Top 5 Engineering AI News", 1)[1].split(
            "## Top 5 Medical", 1
        )[0]
        assert "今日这一栏没有可发布条目" not in general
        assert general.count("English source:") == 3
        assert engineering.count("English source:") == 1

    def test_missing_candidates_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            generate_report(DATE_SLUG, tmp_path)

    def test_invalid_date_slug_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Invalid date slug"):
            generate_report("2026-6-17", tmp_path)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


class TestReportCLI:
    def _invoke(self, digest_dir: Path, *args: str):
        return runner.invoke(app, ["report", "--output-dir", str(digest_dir), *args])

    def test_report_writes_final_md(self, tmp_path: Path, make_candidate):
        _write_artifact(tmp_path, make_candidate)
        result = self._invoke(tmp_path, "--date", DATE_SLUG)
        assert result.exit_code == 0, result.output
        assert final_report_path(tmp_path, DATE_SLUG).exists()

    def test_report_defaults_to_today(self, tmp_path: Path, make_candidate):
        from datetime import date as date_type

        today = date_type.today().isoformat()
        (tmp_path / f"{today}-candidates.json").write_text(
            json.dumps(_payload_with_run_log()), encoding="utf-8"
        )
        result = self._invoke(tmp_path)
        assert result.exit_code == 0, result.output
        assert final_report_path(tmp_path, today).exists()

    def test_report_missing_artifact_exits_1(self, tmp_path: Path):
        result = self._invoke(tmp_path, "--date", DATE_SLUG)
        assert result.exit_code == 1

    def test_report_invalid_date_exits_1(self, tmp_path: Path):
        result = self._invoke(tmp_path, "--date", "not-a-date")
        assert result.exit_code == 1
