from pathlib import Path
from tomllib import TOMLDecodeError
from tomllib import load as load_toml

from attrs import field, frozen
from cattrs import structure
from cattrs.errors import ClassValidationError

from .models import Source  # re-exported for convenience


class ConfigurationError(Exception):
    """Raised when configuration loading or validation fails."""


@frozen
class Configuration:
    """Immutable application configuration built with attrs."""

    user_agent: str
    priority_presets: dict[str, float]
    category_window_hours: dict[str, int]
    sources: list[Source] = field(factory=list)

    @classmethod
    def load(cls, config_path: Path) -> Configuration:
        """Factory method to load and structure TOML configuration."""

        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found at: {config_path}")

        try:
            with config_path.open("rb") as f:
                raw_data = load_toml(f)

            # Convert and validate raw dict into the attrs class
            return structure(raw_data, cls)

        except ClassValidationError as e:
            raise ConfigurationError(f"Configuration validation failed: {e}") from e
        except TOMLDecodeError as e:
            raise ConfigurationError(
                f"Invalid TOML format in {config_path}: {e}"
            ) from e
