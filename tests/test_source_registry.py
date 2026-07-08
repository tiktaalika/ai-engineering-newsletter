import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_digest_candidates import (  # noqa: E402
    Candidate,
    infer_candidate_category,
    load_source_registry,
    score_candidate,
    select_medical_bio_ai,
    select_unique_events,
    title_from_url,
    topic_key,
)


class SourceRegistryTest(unittest.TestCase):
    def test_sources_yaml_has_required_fields(self) -> None:
        registry = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
        required = {"name", "url", "source_type", "category", "priority", "tags", "notes", "enabled"}
        self.assertGreater(len(registry["sources"]), 50)
        for source in registry["sources"]:
            self.assertTrue(required.issubset(source.keys()), source.get("name"))

    def test_registry_loader_normalizes_enabled_sources(self) -> None:
        registry = load_source_registry()
        self.assertIn("sources", registry)
        self.assertTrue(all(source.get("enabled", True) for source in registry["sources"]))
        self.assertTrue(any(source["category"] == "engineering_ai" for source in registry["sources"]))
        self.assertTrue(any(source["kind"] == "web_search_query" for source in registry["sources"]))
        self.assertTrue(any(source["name"] == "Simon Willison" and source["max_entries"] == 5 for source in registry["sources"]))
        self.assertTrue(
            any(
                source["name"] == "Cursor / Anysphere"
                and source["kind"] == "sitemap_or_search"
                for source in registry["sources"]
            )
        )
        self.assertTrue(
            any(
                source["name"] == "Siemens Art of the Possible"
                and source["kind"] == "rss"
                and source["priority"] == "high"
                for source in registry["sources"]
            )
        )

    def test_sitemap_slug_discovery_supports_industrial_ai_pages(self) -> None:
        title = title_from_url("https://cursor.com/de/lp-team/industrial-ai-forum")
        self.assertEqual(title, "Industrial Ai Forum")
        inferred = infer_candidate_category(
            "startup",
            "Industrial AI Forum https://cursor.com/de/lp-team/industrial-ai-forum",
            {"engineering_relevance_score": 0.25},
        )
        self.assertEqual(inferred, "engineering_ai")

    def test_user_requested_engineering_sources_are_curated(self) -> None:
        registry = load_source_registry()
        sources = {source["name"]: source for source in registry["sources"]}

        for name in [
            "Engineering.com",
            "Engineering.com Artificial Intelligence",
            "Engineering24",
            "Industrial AI Network",
            "Industrial AI Network News",
            "Industrial AI Network Knowledge Center",
        ]:
            self.assertIn(name, sources)
            self.assertEqual(sources[name]["category"], "engineering_ai")
            self.assertTrue(sources[name]["enabled"])

        self.assertEqual(sources["Engineering.com"]["priority"], "high")
        self.assertEqual(sources["Industrial AI Network"]["priority"], "high")
        self.assertIn("url_pending_verification", sources["Engineering24"]["tags"])

        trusted_media = sources["Trusted Engineering Media Discovery"]
        self.assertEqual(trusted_media["kind"], "google_news_rss")
        self.assertEqual(trusted_media["priority"], "high")
        self.assertIn("trusted_discovery", trusted_media["tags"])
        self.assertIn("site:engineering.com", trusted_media["query"])
        self.assertIn("site:industrial-ai-network.com", trusted_media["query"])

    def test_biomedical_sources_are_curated(self) -> None:
        registry = load_source_registry()
        sources = {source["name"]: source for source in registry["sources"]}
        expected = [
            "STAT Health Tech",
            "Healthcare IT News",
            "MobiHealthNews",
            "MedCity News",
            "Fierce Biotech",
            "Fierce Healthcare",
            "Bio-IT World",
            "Drug Target Review",
            "GenomeWeb",
            "Pharmaceutical Technology",
            "NEJM AI",
            "The Lancet Digital Health",
            "Nature Medicine",
            "Nature Biotechnology",
            "Cell Patterns",
        ]
        for name in expected:
            self.assertIn(name, sources)
            self.assertTrue(sources[name]["enabled"])
            self.assertTrue({"medical_ai", "bio_ai", "healthcare_ai", "digital_health", "clinical_ai", "genomics_ai"} & set(sources[name]["tags"]), name)

        trusted_bio = sources["Trusted Biomedical AI Source Discovery"]
        self.assertIn("site:ai.nejm.org", trusted_bio["query"])
        self.assertIn("site:healthcareitnews.com", trusted_bio["query"])
        self.assertIn("site:bio-itworld.com", trusted_bio["query"])

    def test_guo_yichen_reference_sources_are_marked(self) -> None:
        registry = load_source_registry()
        sources = {source["name"]: source for source in registry["sources"]}
        expected = {
            "Anthropic News RSS",
            "Anthropic Engineering Blog RSS",
            "Anthropic Research RSS",
            "OpenAI",
            "OpenAI Research RSS",
            "Google DeepMind",
            "Google Research",
            "Cursor Blog RSS",
            "Windsurf Blog RSS",
            "GitHub Blog AI and ML",
            "Hugging Face",
            "Simon Willison",
            "Latent Space",
            "The Pragmatic Engineer",
            "Ahead of AI",
            "Lilian Weng",
            "Hamel Husain",
            "Chain of Thought",
            "Context Window",
            "Argmin Gravitas",
            "Chips and Cheese",
            "South Park Commons",
            "Paul Graham Essays",
            "Sunday Letters",
            "Naval",
            "The Leverage",
            "Garry Tan YouTube",
            "Elad Gil Blog",
            "Fred Wilson AVC",
            "Harry Stebbings 20VC",
        }

        self.assertTrue(expected.issubset(sources.keys()))
        for name in expected:
            self.assertIn("guo_yichen_reference", sources[name]["tags"], name)

    def test_engineering_workflow_ai_gets_scoring_boost(self) -> None:
        source = {
            "category": "engineering_ai",
            "priority": "high",
        }
        now = datetime(2026, 7, 2, tzinfo=timezone.utc)
        published_at = datetime(2026, 6, 15, 13, 55, tzinfo=timezone.utc)
        score, reasons, _ = score_candidate(
            source=source,
            engagement={},
            matches=["AI", "simulation", "LLM"],
            published_at=published_at,
            now=now,
            window_hours=720,
            priority_scores={"high": 1.0, "medium": 0.65, "low": 0.35},
            text=(
                "Ask, don't click: Agentic AI takes the pain out of simulation post-processing. "
                "An LLM uses variable metadata, code generation, and a sandboxed environment "
                "to automate Simcenter Amesim simulation workflow reports."
            ),
        )
        self.assertIn("engineering_workflow_ai_boost=10", reasons)
        self.assertGreater(score, 70)

    def test_topic_diversification_limits_initial_selection(self) -> None:
        def item(idx: int, title: str, score: float) -> Candidate:
            return Candidate(
                id=str(idx),
                title=title,
                url=f"https://example.com/{idx}",
                source=f"test-{idx}",
                source_kind="rss",
                category="general_ai",
                published_at=None,
                text=title,
                matched_terms=["AI"],
                engagement={},
                score=score,
                score_reasons=[],
                source_tags=["guo_yichen_reference"],
            )

        candidates = [
            item(1, "Visa and OpenAI partner on AI payments", 100),
            item(2, "Mastercard launches AI agent payments", 99),
            item(3, "Stripe launches AI agent payments", 98),
            item(4, "Anthropic calls for AI regulation", 80),
            item(5, "OpenAI releases a new frontier model", 79),
        ]
        selected = select_unique_events(candidates, "general_ai", 4)
        topics = [topic_key(candidate) for candidate in selected]
        self.assertEqual(topics.count("payments_agent_commerce"), 2)
        self.assertIn("policy_safety_governance", topics)
        self.assertIn("frontier_models", topics)

    def test_google_news_is_capped_in_general_selection(self) -> None:
        def item(idx: int, title: str, source: str, source_kind: str, score: float) -> Candidate:
            return Candidate(
                id=str(idx),
                title=title,
                url=f"https://example.com/{idx}",
                source=source,
                source_kind=source_kind,
                category="general_ai",
                published_at=None,
                text=title,
                matched_terms=["AI"],
                engagement={},
                score=score,
                score_reasons=[],
                source_tags=["guo_yichen_reference"],
            )

        candidates = [
            item(1, "OpenAI and Visa launch AI agent payments", "Google News General AI Discovery", "google_news_rss", 100),
            item(2, "Meta AI data center infrastructure expands", "Google News General AI Discovery", "google_news_rss", 99),
            item(3, "Anthropic regulation proposal draws attention", "Google News General AI Discovery", "google_news_rss", 98),
            item(4, "OpenAI releases a new frontier model", "OpenAI", "rss", 80),
            item(5, "Anthropic publishes a new safety report", "Anthropic News RSS", "rss", 79),
        ]
        candidates[3].source_tags = ["guo_yichen_reference"]
        candidates[4].source_tags = ["guo_yichen_reference"]

        selected = select_unique_events(candidates, "general_ai", 5)

        self.assertLessEqual(sum(1 for candidate in selected if candidate.source_kind == "google_news_rss"), 2)
        self.assertTrue(any(candidate.source == "OpenAI" for candidate in selected))

    def test_general_selection_caps_repeated_sources(self) -> None:
        def item(idx: int, title: str, source: str, score: float) -> Candidate:
            return Candidate(
                id=str(idx),
                title=title,
                url=f"https://example.com/{idx}",
                source=source,
                source_kind="rss",
                category="general_ai",
                published_at=None,
                text=title,
                matched_terms=["AI"],
                engagement={},
                score=score,
                score_reasons=[],
                source_tags=["guo_yichen_reference"],
            )

        candidates = [
            item(1, "Expert post about AI coding tools", "Simon Willison", 100),
            item(2, "Expert post about AI model behavior", "Simon Willison", 99),
            item(3, "Expert post about AI database tooling", "Simon Willison", 98),
            item(4, "OpenAI releases a platform update", "OpenAI", 80),
            item(5, "The Verge covers an AI product update", "The Verge AI", 79),
        ]

        selected = select_unique_events(candidates, "general_ai", 5)

        self.assertEqual(sum(1 for candidate in selected if candidate.source == "Simon Willison"), 2)
        self.assertTrue(any(candidate.source == "OpenAI" for candidate in selected))

    def test_general_selection_prefers_guo_yichen_sources(self) -> None:
        def item(idx: int, title: str, source: str, score: float, tags: Optional[list[str]] = None, category: str = "general_ai") -> Candidate:
            return Candidate(
                id=str(idx),
                title=title,
                url=f"https://example.com/{idx}",
                source=source,
                source_kind="rss",
                category=category,
                published_at=None,
                text=title,
                matched_terms=["AI"],
                engagement={},
                score=score,
                score_reasons=[],
                source_tags=tags or [],
            )

        candidates = [
            item(1, "Reuters reports a broad AI market story", "Reuters Technology", 100),
            item(2, "Guardian reports a broad AI policy story", "The Guardian Technology", 99),
            item(3, "OpenAI publishes a model update", "OpenAI", 80, ["guo_yichen_reference"]),
            item(4, "Google Research publishes an AI systems result", "Google Research", 79, ["guo_yichen_reference"], "research"),
            item(5, "Simon Willison analyzes an LLM agent tool", "Simon Willison", 78, ["guo_yichen_reference"]),
        ]

        selected = select_unique_events(candidates, "general_ai", 5)

        self.assertEqual([candidate.source for candidate in selected], ["OpenAI", "Google Research", "Simon Willison"])

    def test_engineering_prefers_curated_sources_before_broad_google(self) -> None:
        def item(idx: int, title: str, source: str, source_kind: str, tags: Optional[list[str]] = None) -> Candidate:
            return Candidate(
                id=str(idx),
                title=title,
                url=f"https://example.com/eng/{idx}",
                source=source,
                source_kind=source_kind,
                category="engineering_ai",
                published_at=None,
                text=title,
                matched_terms=["AI", "simulation"],
                engagement={},
                score=100 - idx,
                score_reasons=[],
                source_tags=tags or [],
            )

        candidates = [
            item(1, "Generic industrial AI story from a search result", "Google News Engineering AI Discovery", "google_news_rss"),
            item(2, "Siemens Simcenter AI simulation workflow update", "Siemens Simcenter", "rss"),
            item(3, "Rescale agentic simulation report generation", "Rescale", "rss"),
            item(4, "Trusted vendor digital twin AI update", "Trusted Engineering AI Vendor Discovery", "google_news_rss", ["trusted_discovery"]),
            item(5, "Another generic engineering AI search result", "Google News Engineering AI Discovery", "google_news_rss"),
        ]

        selected = select_unique_events(candidates, "engineering_ai", 5)

        self.assertTrue(any(candidate.source == "Siemens Simcenter" for candidate in selected))
        self.assertTrue(any(candidate.source == "Rescale" for candidate in selected))
        self.assertLessEqual(sum(1 for candidate in selected if candidate.source == "Google News Engineering AI Discovery"), 1)

    def test_selection_excludes_historical_repeats(self) -> None:
        def item(idx: int, title: str, score: float) -> Candidate:
            return Candidate(
                id=str(idx),
                title=title,
                url=f"https://example.com/{idx}",
                source=f"test-{idx}",
                source_kind="rss",
                category="engineering_ai",
                published_at=None,
                text=title,
                matched_terms=["AI", "simulation"],
                engagement={},
                score=score,
                score_reasons=[],
            )

        previous = item(0, "Siemens Simcenter AI simulation workflow update", 100)
        candidates = [
            item(1, "Siemens Simcenter AI simulation workflow update announced", 99),
            item(2, "Rescale AI model for CFD applications", 98),
        ]
        selected = select_unique_events(candidates, "engineering_ai", 2, [previous])

        self.assertEqual([candidate.source for candidate in selected], ["test-2"])

    def test_biomedical_prefers_trusted_sources_before_broad_google(self) -> None:
        def item(idx: int, title: str, source: str, source_kind: str, tags: Optional[list[str]] = None) -> Candidate:
            return Candidate(
                id=str(idx),
                title=title,
                url=f"https://example.com/bio/{idx}",
                source=source,
                source_kind=source_kind,
                category="general_ai",
                published_at=None,
                text=title,
                matched_terms=["AI", "clinical"],
                engagement={},
                score=100 - idx,
                score_reasons=[],
                source_tags=tags or [],
            )

        candidates = [
            item(1, "Clinical AI benchmark from generic medical search", "Google News Medical AI Discovery", "google_news_rss", ["medical_ai"]),
            item(2, "Nature Medicine clinical AI model study", "Trusted Biomedical AI Source Discovery", "google_news_rss", ["medical_ai", "trusted_discovery"]),
            item(3, "STAT reports healthcare AI deployment", "STAT Health Tech", "rss", ["medical_ai"]),
            item(4, "Another generic medical AI search result", "Google News Medical AI Discovery", "google_news_rss", ["medical_ai"]),
        ]

        selected = select_medical_bio_ai(candidates, 5)

        self.assertTrue(any(candidate.source == "Trusted Biomedical AI Source Discovery" for candidate in selected))
        self.assertTrue(any(candidate.source == "STAT Health Tech" for candidate in selected))
        self.assertLessEqual(sum(1 for candidate in selected if candidate.source == "Google News Medical AI Discovery"), 1)


if __name__ == "__main__":
    unittest.main()
