from pathlib import Path

from newsletter.configuration import Configuration
from newsletter.fetchers import fetch_kind


def test_configuration_load():
    config_path = Path(__file__).parent.parent / "config" / "config.toml"
    config = Configuration.load(config_path)
    assert config.user_agent
    assert "high" in config.priority_presets
    assert len(config.sources) > 0


def test_source_without_fetch_type_resolves_via_source_type(tmp_path: Path):
    """fetch_type is optional; v1 fetch_kind auto-resolution applies."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        'user_agent = "test-agent/1.0"\n'
        "[priority_presets]\n"
        "high = 1.0\n"
        "[category_window_hours]\n"
        "general_ai = 24\n"
        "\n"
        "[[sources]]\n"
        'name = "Implicit RSS"\n'
        'scrape_url = "https://example.com/feed"\n'
        'priority = "high"\n'
        'category = "general_ai"\n'
        'source_type = "rss"\n'
        "\n"
        "[[sources]]\n"
        'name = "Bare"\n'
        'scrape_url = "https://example.com/"\n'
        'priority = "low"\n'
        'category = "general_ai"\n'
    )

    config = Configuration.load(config_file)
    assert len(config.sources) == 2

    implicit_rss, bare = config.sources
    assert implicit_rss.fetch_type is None
    assert fetch_kind(implicit_rss) == "rss"

    assert bare.fetch_type is None
    assert bare.source_type is None
    assert fetch_kind(bare) == "web_search_query"
