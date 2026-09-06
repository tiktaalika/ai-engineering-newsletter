"""Tests for newsletter.artifacts — the candidates JSON contract (Goal 8.4)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from attrs import evolve

from newsletter.artifacts import (
    CANDIDATES_SUFFIX,
    SELECTION_POLICY,
    candidate_from_dict,
    candidate_to_dict,
    candidates_path,
    history_category,
    issue_to_payload,
    load_history,
    run_log_to_dict,
    write_candidates_json,
)
from newsletter.models import (
    Candidate,
    DigestIssue,
    Engagement,
    RunLog,
    ScoreBreakdown,
    Source,
)
from newsletter.selection import is_broad_google_discovery

CandidateFactory = Callable[..., Candidate]

#: Exact v1 candidate schema — keys *and* order (PROJECT.md §3.9).
V1_CANDIDATE_KEYS = (
    "id",
    "title",
    "url",
    "source",
    "source_kind",
    "category",
    "published_at",
    "text",
    "matched_terms",
    "engagement",
    "score",
    "score_reasons",
    "general_ai_score",
    "engineering_relevance_score",
    "research_relevance_score",
    "novelty_score",
    "source_priority_score",
    "source_tags",
    "registry_category",
    "source_priority",
)

#: Exact v1 issue payload — keys *and* order (PROJECT.md §3.10).
V1_PAYLOAD_KEYS = (
    "run_log",
    "selection_policy",
    "top_10_general_ai",
    "top_5_engineering_ai",
    "top_5_medical_bio_ai",
    "top_5_cae_ai_engineering",
    "research_radar",
    "supplemental_search_tasks",
    "watchlist_updates",
    "top_100_news_candidates",
)

PUBLISHED = datetime(2026, 8, 31, 8, 30, tzinfo=UTC)


def _item(
    title: str = "Nvidia unveils a GPU", url: str = "https://a.com/1", **overrides: Any
) -> dict[str, Any]:
    """A minimal v1-shaped candidate object for history artifacts."""
    base: dict[str, Any] = {
        "id": "abc123",
        "title": title,
        "url": url,
        "source": "Outlet A",
        "source_kind": "rss",
        "category": "general_ai",
        "published_at": None,
        "text": "",
        "matched_terms": [],
        "engagement": {},
        "score": 10.0,
        "score_reasons": [],
        "source_tags": [],
        "registry_category": "general_ai",
        "source_priority": "high",
    }
    base.update(overrides)
    return base


def _write_artifact(digest_dir: Path, date_slug: str, payload: Any) -> Path:
    path = candidates_path(digest_dir, date_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# candidate → dict
# --------------------------------------------------------------------------- #


class TestCandidateToDict:
    def test_schema_matches_v1(self, make_candidate: CandidateFactory) -> None:
        assert tuple(candidate_to_dict(make_candidate())) == V1_CANDIDATE_KEYS

    def test_source_is_flattened_to_name_and_kind(
        self, make_candidate: CandidateFactory
    ) -> None:
        payload = candidate_to_dict(
            make_candidate(source_name="MIT Technology Review", fetch_type="rss")
        )
        assert payload["source"] == "MIT Technology Review"
        assert payload["source_kind"] == "rss"

    def test_website_source_kind_is_resolved(
        self, make_candidate: CandidateFactory
    ) -> None:
        payload = candidate_to_dict(make_candidate(fetch_type="website"))
        assert payload["source_kind"] == "sitemap_or_search"

    def test_published_at_is_isoformat(self, make_candidate: CandidateFactory) -> None:
        payload = candidate_to_dict(make_candidate(pub_date=PUBLISHED))
        assert payload["published_at"] == "2026-08-31T08:30:00+00:00"

    def test_missing_published_at_is_null(
        self, make_candidate: CandidateFactory
    ) -> None:
        assert candidate_to_dict(make_candidate(pub_date=None))["published_at"] is None

    def test_engagement_omits_missing_counters(
        self, make_candidate: CandidateFactory
    ) -> None:
        assert candidate_to_dict(make_candidate())["engagement"] == {}
        partial = candidate_to_dict(make_candidate(engagement=Engagement(points=42)))[
            "engagement"
        ]
        assert partial == {"points": 42}
        full = candidate_to_dict(
            make_candidate(engagement=Engagement(points=1, comments=2, upvotes=3))
        )["engagement"]
        assert full == {"points": 1, "comments": 2, "upvotes": 3}

    def test_sub_scores_are_flattened(self, make_candidate: CandidateFactory) -> None:
        breakdown = ScoreBreakdown(
            score=88.5,
            source_priority=1.0,
            novelty=0.9,
            general_relevance=0.667,
            engineering_relevance=0.25,
            research_relevance=0.0,
        )
        payload = candidate_to_dict(make_candidate(breakdown=breakdown))
        assert payload["score"] == 88.5
        assert payload["source_priority_score"] == 1.0
        assert payload["novelty_score"] == 0.9
        assert payload["general_ai_score"] == 0.667
        assert payload["engineering_relevance_score"] == 0.25
        assert payload["research_relevance_score"] == 0.0

    def test_score_reasons_are_rendered(self, make_candidate: CandidateFactory) -> None:
        reasons = candidate_to_dict(make_candidate(matched_terms=["AI", "LLM"]))[
            "score_reasons"
        ]
        assert reasons[0].startswith("source_priority=")
        assert "matched_terms=2" in reasons
        assert reasons[-1].startswith("visible_engagement=")

    def test_registry_category_falls_back_to_the_source(
        self, make_candidate: CandidateFactory
    ) -> None:
        candidate = evolve(
            make_candidate(category="engineering_ai"), registry_category=None
        )
        assert candidate_to_dict(candidate)["registry_category"] == "engineering_ai"

    def test_source_priority_falls_back_to_the_source(
        self, make_candidate: CandidateFactory
    ) -> None:
        candidate = evolve(make_candidate(priority="low"), source_priority=None)
        assert candidate_to_dict(candidate)["source_priority"] == "low"

    def test_source_tags_are_copied(self, make_candidate: CandidateFactory) -> None:
        candidate = make_candidate(tags=["ai", "curated_rss"])
        payload = candidate_to_dict(candidate)
        assert payload["source_tags"] == ["ai", "curated_rss"]
        payload["source_tags"].append("mutated")
        assert candidate.source.tags == ["ai", "curated_rss"]


# --------------------------------------------------------------------------- #
# dict → candidate
# --------------------------------------------------------------------------- #


class TestCandidateFromDict:
    def test_round_trip_preserves_selection_fields(
        self, make_candidate: CandidateFactory
    ) -> None:
        original = make_candidate(
            title="OpenAI releases a model",
            url="https://a.com/story",
            source_name="Outlet A",
            category="general_ai",
            priority="high",
            tags=["curated_rss"],
            pub_date=PUBLISHED,
            text="Some body text",
            matched_terms=["AI", "OpenAI"],
            engagement=Engagement(points=10, comments=2),
            breakdown=ScoreBreakdown(score=77.0, novelty=0.8, general_relevance=0.5),
        )

        restored = candidate_from_dict(candidate_to_dict(original))

        assert restored.id == original.id
        assert restored.title == original.title
        assert restored.url == original.url
        assert restored.category == original.category
        assert restored.pub_date == PUBLISHED
        assert restored.text == "Some body text"
        assert restored.matched_terms == ["AI", "OpenAI"]
        assert restored.engagement.points == 10
        assert restored.score_breakdown.score == 77.0
        assert restored.score_breakdown.novelty == 0.8
        assert restored.source.name == "Outlet A"
        assert restored.source.tags == ["curated_rss"]
        assert restored.source.priority == "high"

    def test_empty_dict_yields_safe_defaults(self) -> None:
        restored = candidate_from_dict({})
        assert restored.id == ""
        assert restored.title == ""
        assert restored.url == ""
        assert restored.category == "general_ai"
        assert restored.pub_date is None
        assert restored.engagement == Engagement()
        assert restored.score_breakdown.score == 0.0
        assert restored.source.priority == "medium"

    def test_unknown_priority_falls_back_to_medium(self) -> None:
        assert candidate_from_dict(_item(source_priority="urgent")).source.priority == (
            "medium"
        )

    @pytest.mark.parametrize("priority", ["high", "medium", "low"])
    def test_known_priorities_round_trip(self, priority: str) -> None:
        restored = candidate_from_dict(_item(source_priority=priority))
        assert restored.source.priority == priority
        assert restored.source_priority == priority

    def test_unknown_category_falls_back_to_general_ai(self) -> None:
        assert candidate_from_dict(_item(category="lifestyle")).category == "general_ai"

    def test_legacy_category_alias_is_canonicalized(self) -> None:
        restored = candidate_from_dict(
            _item(category="cae_ai_engineering", registry_category="cae_ai_engineering")
        )
        assert restored.category == "engineering_ai"
        assert restored.source.category == "engineering_ai"
        assert restored.registry_category == "engineering_ai"

    def test_unparsable_published_at_is_ignored(self) -> None:
        assert candidate_from_dict(_item(published_at="yesterday")).pub_date is None

    def test_non_string_published_at_is_ignored(self) -> None:
        assert candidate_from_dict(_item(published_at=12345)).pub_date is None

    def test_source_kind_survives_for_selection_predicates(self) -> None:
        """History items must still work with the trust/discovery gates."""
        restored = candidate_from_dict(
            _item(
                source="Google News AI",
                source_kind="google_news_rss",
                source_tags=[],
            )
        )
        assert is_broad_google_discovery(restored)

    def test_missing_engagement_counters(self) -> None:
        restored = candidate_from_dict(_item(engagement={"points": 7}))
        assert restored.engagement.points == 7
        assert restored.engagement.comments is None
        assert restored.engagement.upvotes is None


# --------------------------------------------------------------------------- #
# run log / issue payload
# --------------------------------------------------------------------------- #


class TestRunLogToDict:
    def test_key_order_and_values(self) -> None:
        run_log = RunLog(
            generated_at=PUBLISHED,
            window_hours=48,
            source_count=125,
            fetched_count=3000,
            filtered_count=120,
            duplicate_count=7,
            failures=[{"source": "Ansys", "error": "timed out"}],
        )
        payload = run_log_to_dict(run_log)

        assert tuple(payload) == (
            "generated_at",
            "window_hours",
            "source_count",
            "fetched_count",
            "filtered_count",
            "duplicate_count",
            "failures",
        )
        assert payload["generated_at"] == "2026-08-31T08:30:00+00:00"
        assert payload["source_count"] == 125
        assert payload["failures"] == [{"source": "Ansys", "error": "timed out"}]

    def test_failures_are_copied(self) -> None:
        run_log = RunLog(failures=[{"source": "A", "error": "boom"}])
        payload = run_log_to_dict(run_log)
        payload["failures"][0]["error"] = "mutated"
        assert run_log.failures[0]["error"] == "boom"


class TestIssueToPayload:
    def test_schema_matches_v1(self, make_candidate: CandidateFactory) -> None:
        issue = DigestIssue(
            run_log=RunLog(),
            top_10_general_ai=[make_candidate(title="General item")],
            top_5_engineering_ai=[make_candidate(title="Engineering item")],
            top_5_medical_bio_ai=[make_candidate(title="Medical item")],
            research_radar=[make_candidate(title="Research item")],
            top_100_news_candidates=[make_candidate(title="Pool item")],
        )
        assert tuple(issue_to_payload(issue)) == V1_PAYLOAD_KEYS

    def test_legacy_engineering_alias_mirrors_the_section(
        self, make_candidate: CandidateFactory
    ) -> None:
        issue = DigestIssue(
            run_log=RunLog(),
            top_5_engineering_ai=[make_candidate(title="Engineering item")],
        )
        payload = issue_to_payload(issue)
        assert payload["top_5_cae_ai_engineering"] == payload["top_5_engineering_ai"]
        assert len(payload["top_5_cae_ai_engineering"]) == 1

    def test_selection_policy_is_a_copy(self) -> None:
        payload = issue_to_payload(DigestIssue(run_log=RunLog()))
        payload["selection_policy"]["general_ai"] = "mutated"
        assert SELECTION_POLICY["general_ai"] != "mutated"

    def test_selection_policy_documents_every_section(self) -> None:
        assert set(SELECTION_POLICY) == {
            "general_ai",
            "engineering_ai",
            "medical_bio_ai",
            "research_radar",
            "ranking_note",
            "history_deduplication",
        }

    def test_empty_issue_serializes(self) -> None:
        payload = issue_to_payload(DigestIssue(run_log=RunLog()))
        assert payload["top_10_general_ai"] == []
        assert payload["supplemental_search_tasks"] == []
        assert payload["watchlist_updates"] == []
        assert payload["top_100_news_candidates"] == []


# --------------------------------------------------------------------------- #
# Writing artifacts
# --------------------------------------------------------------------------- #


class TestWriteCandidatesJson:
    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "digests" / "2026-09-01-candidates.json"
        write_candidates_json(DigestIssue(run_log=RunLog()), target)
        assert target.is_file()

    def test_returns_the_path_and_writes_valid_json(self, tmp_path: Path) -> None:
        target = candidates_path(tmp_path, "2026-09-01")
        result = write_candidates_json(DigestIssue(run_log=RunLog()), target)

        assert result == target
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert tuple(payload) == V1_PAYLOAD_KEYS

    def test_filename_convention(self, tmp_path: Path) -> None:
        path = candidates_path(tmp_path, "2026-09-01")
        assert path.name == f"2026-09-01{CANDIDATES_SUFFIX}"
        assert path.parent == tmp_path

    def test_unicode_is_not_escaped(
        self, tmp_path: Path, make_candidate: CandidateFactory
    ) -> None:
        issue = DigestIssue(
            run_log=RunLog(),
            top_10_general_ai=[make_candidate(title="OpenAI 发布新模型")],
        )
        path = write_candidates_json(issue, candidates_path(tmp_path, "2026-09-01"))

        raw = path.read_text(encoding="utf-8")
        assert "发布新模型" in raw
        assert "\\u" not in raw

    def test_overwrites_an_existing_artifact(self, tmp_path: Path) -> None:
        target = candidates_path(tmp_path, "2026-09-01")
        target.write_text("not json", encoding="utf-8")

        write_candidates_json(DigestIssue(run_log=RunLog(source_count=3)), target)

        assert (
            json.loads(target.read_text(encoding="utf-8"))["run_log"]["source_count"]
            == 3
        )


# --------------------------------------------------------------------------- #
# Historical lookback
# --------------------------------------------------------------------------- #


class TestLoadHistory:
    def test_missing_directory(self, tmp_path: Path) -> None:
        assert load_history(tmp_path / "nope", "2026-09-01", "general_ai", 7) == []

    def test_invalid_date_slug(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "2026-08-31", {"top_10_general_ai": [_item()]})
        assert load_history(tmp_path, "not-a-date", "general_ai", 7) == []

    def test_unknown_category(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "2026-08-31", {"top_10_general_ai": [_item()]})
        assert load_history(tmp_path, "2026-09-01", "lifestyle", 7) == []

    def test_reads_items_within_the_lookback(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "2026-08-31", {"top_10_general_ai": [_item()]})
        history = load_history(tmp_path, "2026-09-01", "general_ai", 7)

        assert len(history) == 1
        assert history[0].title == "Nvidia unveils a GPU"
        assert history[0].source.name == "Outlet A"

    def test_skips_the_current_day(self, tmp_path: Path) -> None:
        """age <= 0 is skipped so a rerun never dedupes against itself."""
        _write_artifact(tmp_path, "2026-09-01", {"top_10_general_ai": [_item()]})
        assert load_history(tmp_path, "2026-09-01", "general_ai", 7) == []

    def test_skips_future_artifacts(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "2026-09-05", {"top_10_general_ai": [_item()]})
        assert load_history(tmp_path, "2026-09-01", "general_ai", 7) == []

    def test_skips_artifacts_beyond_the_lookback(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "2026-08-01", {"top_10_general_ai": [_item()]})
        assert load_history(tmp_path, "2026-09-01", "general_ai", 7) == []

    def test_engineering_uses_the_longer_lookback(self, tmp_path: Path) -> None:
        _write_artifact(
            tmp_path, "2026-08-10", {"top_5_engineering_ai": [_item(title="CFD story")]}
        )
        assert load_history(tmp_path, "2026-09-01", "general_ai", 7) == []
        assert len(load_history(tmp_path, "2026-09-01", "engineering_ai", 30)) == 1

    def test_engineering_reads_both_section_keys(self, tmp_path: Path) -> None:
        """Older artifacts used the legacy cae_ai_engineering section name."""
        item = _item(title="CFD story")
        _write_artifact(
            tmp_path,
            "2026-08-31",
            {"top_5_engineering_ai": [item], "top_5_cae_ai_engineering": [item]},
        )
        assert len(load_history(tmp_path, "2026-09-01", "engineering_ai", 30)) == 2

    def test_medical_section_key(self, tmp_path: Path) -> None:
        _write_artifact(
            tmp_path, "2026-08-31", {"top_5_medical_bio_ai": [_item(title="Trial")]}
        )
        history = load_history(tmp_path, "2026-09-01", "medical_bio_ai", 30)
        assert [candidate.title for candidate in history] == ["Trial"]

    def test_malformed_json_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "2026-08-31-candidates.json").write_text("{oops", encoding="utf-8")
        _write_artifact(tmp_path, "2026-08-30", {"top_10_general_ai": [_item()]})

        history = load_history(tmp_path, "2026-09-01", "general_ai", 7)
        assert len(history) == 1

    def test_non_object_payload_is_skipped(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "2026-08-31", ["not", "an", "object"])
        assert load_history(tmp_path, "2026-09-01", "general_ai", 7) == []

    def test_non_object_items_are_skipped(self, tmp_path: Path) -> None:
        _write_artifact(
            tmp_path, "2026-08-31", {"top_10_general_ai": ["junk", _item()]}
        )
        assert len(load_history(tmp_path, "2026-09-01", "general_ai", 7)) == 1

    def test_files_without_the_suffix_are_ignored(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "2026-08-31", {"top_10_general_ai": [_item()]})
        (tmp_path / "2026-08-30-final.md").write_text("# report", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")

        assert len(load_history(tmp_path, "2026-09-01", "general_ai", 7)) == 1

    def test_undated_filenames_are_skipped(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path, "2026-08-31", {"top_10_general_ai": [_item()]})
        (tmp_path / f"latest{CANDIDATES_SUFFIX}").write_text("{}", encoding="utf-8")

        assert len(load_history(tmp_path, "2026-09-01", "general_ai", 7)) == 1


class TestHistoryCategory:
    @pytest.mark.parametrize(
        ("category", "expected"),
        [
            ("general_ai", "general_ai"),
            ("engineering_ai", "engineering_ai"),
            ("cae_ai_engineering", "engineering_ai"),
            ("medical_bio_ai", "medical_bio_ai"),
            ("research", "research"),
            # No published section → no history (v1 parity).
            ("startup", ""),
            ("vendor", ""),
            ("community", ""),
            ("lifestyle", ""),
        ],
    )
    def test_mapping(self, category: str, expected: str) -> None:
        assert history_category(category) == expected


# --------------------------------------------------------------------------- #
# End-to-end artifact round trip
# --------------------------------------------------------------------------- #


class TestArtifactRoundTrip:
    def test_written_artifact_feeds_history(
        self, tmp_path: Path, make_candidate: CandidateFactory
    ) -> None:
        """Yesterday's selection must suppress today's repeat."""
        published = make_candidate(
            title="Nvidia unveils a GPU",
            url="https://a.com/1",
            source_name="Outlet A",
            pub_date=PUBLISHED,
        )
        issue = DigestIssue(
            run_log=RunLog(generated_at=PUBLISHED),
            top_10_general_ai=[published],
            top_100_news_candidates=[published],
        )
        write_candidates_json(issue, candidates_path(tmp_path, "2026-08-31"))

        history = load_history(tmp_path, "2026-09-01", "general_ai", 7)

        assert len(history) == 1
        assert history[0].url == "https://a.com/1"
        assert history[0].pub_date == PUBLISHED
        assert history[0].source.name == "Outlet A"

    def test_source_is_reconstructed_without_a_registry_url(
        self, tmp_path: Path, make_candidate: CandidateFactory
    ) -> None:
        """The v1 schema has no registry URL, so the item URL stands in."""
        published = make_candidate(url="https://a.com/story")
        write_candidates_json(
            DigestIssue(run_log=RunLog(), top_10_general_ai=[published]),
            candidates_path(tmp_path, "2026-08-31"),
        )

        restored = load_history(tmp_path, "2026-09-01", "general_ai", 7)[0]

        assert restored.source.scrape_url == "https://a.com/story"
        assert isinstance(restored.source, Source)
        assert isinstance(restored, Candidate)
