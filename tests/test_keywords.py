"""Tests for newsletter.keywords — config loading and term matching (Goal 6.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from newsletter.keywords import (
    KeywordConfig,
    KeywordError,
    KeywordFilter,
    blocked_terms,
    keyword_bucket_name,
    match_terms,
    matches,
    matches_core_terms,
    passes_gates,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_VALID_TOML = """\
[general_ai]
required_language = "en"
include = ["AI", "LLM", "OpenAI"]
exclude = ["AI washing", "price predictions"]

[engineering_ai]
required_language = "en"
core_include = ["CAE", "simulation", "CFD"]
ai_include = ["AI", "machine learning", "surrogate"]
include = ["CFD", "digital twin", "engineering simulation"]
exclude = ["CFD trading", "stock"]
"""


def _write_keywords(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "keywords.toml"
    path.write_text(body, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Configuration loading
# --------------------------------------------------------------------------- #


class TestKeywordConfigLoad:
    def test_loads_shipped_config(self, keyword_config: KeywordConfig) -> None:
        """The real config/keywords.toml ports v1 keywords.json 1:1."""
        assert keyword_config.general_ai.required_language == "en"
        assert len(keyword_config.general_ai.include) == 44
        assert len(keyword_config.general_ai.exclude) == 10
        # v1's cae_ai_engineering bucket, renamed to the canonical category.
        assert len(keyword_config.engineering_ai.core_include) == 34
        assert len(keyword_config.engineering_ai.ai_include) == 15
        assert len(keyword_config.engineering_ai.include) == 38
        assert len(keyword_config.engineering_ai.exclude) == 39

    def test_shipped_config_matches_v1_terms(
        self, keyword_config: KeywordConfig
    ) -> None:
        """Spot-check terms that downstream filters depend on."""
        assert "AI" in keyword_config.general_ai.include
        assert "AI washing" in keyword_config.general_ai.exclude
        assert "Simcenter" in keyword_config.engineering_ai.core_include
        assert "CFD trading" in keyword_config.engineering_ai.exclude

    def test_structures_all_fields(self, tmp_path: Path) -> None:
        config = KeywordConfig.load(_write_keywords(tmp_path, _VALID_TOML))
        assert config.general_ai.include == ["AI", "LLM", "OpenAI"]
        assert config.engineering_ai.ai_include == [
            "AI",
            "machine learning",
            "surrogate",
        ]
        assert config.engineering_ai.required_language == "en"

    def test_optional_fields_default(self, tmp_path: Path) -> None:
        body = '[general_ai]\ninclude = ["AI"]\n\n[engineering_ai]\ninclude = ["CAE"]\n'
        config = KeywordConfig.load(_write_keywords(tmp_path, body))
        assert config.general_ai.exclude == []
        assert config.general_ai.core_include == []
        assert config.general_ai.required_language == "en"

    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Keyword configuration"):
            KeywordConfig.load(tmp_path / "nope.toml")

    def test_invalid_toml_raises_keyword_error(self, tmp_path: Path) -> None:
        path = _write_keywords(tmp_path, "[general_ai\ninclude = ")
        with pytest.raises(KeywordError, match="Invalid TOML"):
            KeywordConfig.load(path)

    def test_wrong_type_raises_keyword_error(self, tmp_path: Path) -> None:
        """cattrs would iterate a bare string into ['A', 'I'] — reject it."""
        path = _write_keywords(
            tmp_path,
            '[general_ai]\ninclude = "AI"\n\n[engineering_ai]\ninclude = ["CAE"]\n',
        )
        with pytest.raises(KeywordError, match="must be a list of strings"):
            KeywordConfig.load(path)

    def test_missing_bucket_raises_keyword_error(self, tmp_path: Path) -> None:
        """A missing bucket must not silently default to an empty filter."""
        path = _write_keywords(tmp_path, '[general_ai]\ninclude = ["AI"]\n')
        with pytest.raises(
            KeywordError, match=r"Missing keyword bucket \[engineering_ai\]"
        ):
            KeywordConfig.load(path)

    def test_unknown_key_raises_keyword_error(self, tmp_path: Path) -> None:
        """Typos like ``excludes`` are rejected instead of ignored."""
        path = _write_keywords(
            tmp_path,
            '[general_ai]\ninclude = ["AI"]\nexcludes = ["AI washing"]\n\n'
            '[engineering_ai]\ninclude = ["CAE"]\n',
        )
        with pytest.raises(KeywordError, match="Unknown key"):
            KeywordConfig.load(path)

    def test_non_table_bucket_raises_keyword_error(self, tmp_path: Path) -> None:
        path = _write_keywords(
            tmp_path, 'general_ai = "AI"\n\n[engineering_ai]\ninclude = ["CAE"]\n'
        )
        with pytest.raises(KeywordError, match="must be a table"):
            KeywordConfig.load(path)

    def test_required_language_must_be_a_string(self, tmp_path: Path) -> None:
        path = _write_keywords(
            tmp_path,
            '[general_ai]\ninclude = ["AI"]\nrequired_language = 3\n\n'
            '[engineering_ai]\ninclude = ["CAE"]\n',
        )
        with pytest.raises(KeywordError, match="required_language must be a string"):
            KeywordConfig.load(path)

    def test_empty_include_bucket_raises_keyword_error(self, tmp_path: Path) -> None:
        """A bucket without include terms would reject every item silently."""
        path = _write_keywords(
            tmp_path,
            '[general_ai]\ninclude = ["AI"]\n\n[engineering_ai]\ninclude = []\n',
        )
        with pytest.raises(KeywordError, match="no include terms"):
            KeywordConfig.load(path)


# --------------------------------------------------------------------------- #
# Bucket resolution
# --------------------------------------------------------------------------- #


class TestKeywordBucketName:
    @pytest.mark.parametrize(
        ("category", "expected"),
        [
            ("general_ai", "general_ai"),
            ("engineering_ai", "engineering_ai"),
            ("cae_ai_engineering", "engineering_ai"),  # legacy v1 name
            ("research", "general_ai"),
            ("startup", "general_ai"),
            ("vendor", "general_ai"),
            ("community", "general_ai"),
            ("something_new", "general_ai"),
        ],
    )
    def test_mapping(self, category: str, expected: str) -> None:
        assert keyword_bucket_name(category) == expected


class TestBucketLookup:
    def test_bucket_by_name(self, keyword_config: KeywordConfig) -> None:
        assert keyword_config.bucket("general_ai") is keyword_config.general_ai
        assert keyword_config.bucket("engineering_ai") is keyword_config.engineering_ai

    @pytest.mark.parametrize("category", ["engineering_ai", "cae_ai_engineering"])
    def test_filter_for_engineering(
        self, keyword_config: KeywordConfig, category: str
    ) -> None:
        assert keyword_config.filter_for(category) is keyword_config.engineering_ai

    @pytest.mark.parametrize("category", ["general_ai", "research", "startup"])
    def test_filter_for_general(
        self, keyword_config: KeywordConfig, category: str
    ) -> None:
        assert keyword_config.filter_for(category) is keyword_config.general_ai


# --------------------------------------------------------------------------- #
# match_terms / blocked_terms
# --------------------------------------------------------------------------- #


class TestMatchTerms:
    def test_case_insensitive_substring(self) -> None:
        assert match_terms("OpenAI shipped an LLM", ["openai", "llm"]) == [
            "openai",
            "llm",
        ]

    def test_no_matches(self) -> None:
        assert match_terms("a story about gardening", ["AI", "LLM"]) == []

    def test_preserves_configured_order(self) -> None:
        text = "An AI agent using an LLM for RAG"
        assert match_terms(text, ["RAG", "AI", "LLM"]) == ["RAG", "AI", "LLM"]

    def test_substring_not_word_boundary(self) -> None:
        """v1 semantics: plain substring match, so 'AI' hits 'AIData'."""
        assert match_terms("AIData platform", ["AI"]) == ["AI"]

    def test_empty_terms(self) -> None:
        assert match_terms("any text", []) == []

    def test_empty_text(self) -> None:
        assert match_terms("", ["AI"]) == []

    def test_blocked_terms_reports_every_hit(self) -> None:
        text = "AI washing and price predictions everywhere"
        assert blocked_terms(text, ["AI washing", "price predictions", "IPO"]) == [
            "AI washing",
            "price predictions",
        ]


# --------------------------------------------------------------------------- #
# matches (exclude → include)
# --------------------------------------------------------------------------- #


class TestMatches:
    def test_include_hit_passes(self, keyword_config: KeywordConfig) -> None:
        hits, ok = matches(
            "OpenAI released a new foundation model", keyword_config.general_ai
        )
        assert ok
        assert "OpenAI" in hits

    def test_no_include_hit_fails(self, keyword_config: KeywordConfig) -> None:
        hits, ok = matches(
            "Local council approves new bicycle lane", keyword_config.general_ai
        )
        assert not ok
        assert hits == []

    def test_exclude_short_circuits(self, keyword_config: KeywordConfig) -> None:
        """An excluded term rejects even when include terms are present."""
        hits, ok = matches(
            "OpenAI AI washing claims about a new LLM", keyword_config.general_ai
        )
        assert not ok
        assert hits == []

    def test_exclude_is_case_insensitive(self) -> None:
        keyword_filter = KeywordFilter(include=["AI"], exclude=["ai washing"])
        assert matches("AI WASHING hype", keyword_filter) == ([], False)

    def test_engineering_exclude_blocks_finance_noise(
        self, keyword_config: KeywordConfig
    ) -> None:
        hits, ok = matches(
            "CFD trading platforms compared by analysts", keyword_config.engineering_ai
        )
        assert not ok
        assert hits == []

    def test_engineering_include_hit(self, keyword_config: KeywordConfig) -> None:
        hits, ok = matches(
            "Engineering simulation with a digital twin", keyword_config.engineering_ai
        )
        assert ok
        assert "digital twin" in hits


# --------------------------------------------------------------------------- #
# Core-term gates
# --------------------------------------------------------------------------- #


class TestMatchesCoreTerms:
    def test_none_means_no_gate(self) -> None:
        assert matches_core_terms("anything", None)

    def test_empty_means_no_gate(self) -> None:
        assert matches_core_terms("anything", [])

    def test_hit(self) -> None:
        assert matches_core_terms("A CFD study", ["cfd"])

    def test_miss(self) -> None:
        assert not matches_core_terms("A gardening study", ["cfd"])


class TestPassesGates:
    def test_general_bucket_has_no_gates(self, keyword_config: KeywordConfig) -> None:
        assert passes_gates("literally anything", keyword_config.general_ai)

    def test_engineering_requires_both_gates(
        self, keyword_config: KeywordConfig
    ) -> None:
        assert passes_gates(
            "A surrogate model for CFD simulation", keyword_config.engineering_ai
        )

    def test_core_only_fails(self, keyword_config: KeywordConfig) -> None:
        """Pure simulation text with no AI term must not pass."""
        assert not passes_gates(
            "Mesh generation for a CFD solver", keyword_config.engineering_ai
        )

    def test_ai_only_fails(self, keyword_config: KeywordConfig) -> None:
        """Pure AI text with no engineering domain term must not pass."""
        assert not passes_gates(
            "A new machine learning copilot", keyword_config.engineering_ai
        )

    def test_custom_gates(self) -> None:
        keyword_filter = KeywordFilter(core_include=["CAE"], ai_include=["AI"])
        assert passes_gates("CAE meets AI", keyword_filter)
        assert not passes_gates("CAE only", keyword_filter)
        assert not passes_gates("AI only", keyword_filter)
