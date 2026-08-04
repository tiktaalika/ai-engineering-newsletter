from pathlib import Path

from newsletter.configuration import Configuration


def test_configuration_load():
    config_path = Path(__file__).parent.parent / "config" / "config.toml"
    config = Configuration.load(config_path)
    assert config.user_agent
    assert "high" in config.priority_presets
    assert len(config.sources) > 0
