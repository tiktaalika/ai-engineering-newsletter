"""Shared pytest fixtures for the newsletter test suite."""

from __future__ import annotations

import contextlib
import logging
import shutil
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import pytest

from newsletter import main as main_module
from newsletter.configuration import Configuration
from newsletter.dedup import norm_url
from newsletter.keywords import KeywordConfig
from newsletter.models import (
    Candidate,
    Category,
    Engagement,
    FetchType,
    Priority,
    RawRecord,
    ScoreBreakdown,
    Source,
)
from newsletter.text import entry_id

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Configuration fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def app_config() -> Configuration:
    """The real application config shipped in ``config/config.toml``."""
    return Configuration.load(REPO_ROOT / "config" / "config.toml")


@pytest.fixture()
def keyword_config() -> KeywordConfig:
    """The real keyword config shipped in ``config/keywords.toml``."""
    return KeywordConfig.load(REPO_ROOT / "config" / "keywords.toml")


# --------------------------------------------------------------------------- #
# Log isolation
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def isolated_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Stop tests from writing into the repo's committed ``logs/`` directory.

    ``newsletter collect`` resolves its project root at runtime and configures
    the *root* logger with file handlers (``logs/audit.log`` + rotating
    ``logs/error.log``).  Once any test triggers that, every later log record
    in the session — including httpx's ``_client`` chatter from ``respx``
    tests — is appended to the real files, dirtying the working tree.

    This autouse fixture redirects the project root to a throwaway directory
    holding copies of the real ``logging.toml`` and ``keywords.toml`` (so the
    ``dictConfig`` path, its file handlers, and the CLI's default keyword
    resolution are all still exercised — just into ``tmp_path``), and restores
    the root logger afterwards so handlers never leak between tests.

    Yields:
        The temporary project root used for the test.
    """
    project_root = tmp_path / "project"
    (project_root / "config").mkdir(parents=True)
    (project_root / "logs").mkdir()
    for name in ("logging.toml", "keywords.toml"):
        shutil.copy(REPO_ROOT / "config" / name, project_root / "config")

    monkeypatch.setattr(main_module, "_resolve_project_root", lambda: project_root)

    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level

    try:
        yield project_root
    finally:
        for handler in list(root.handlers):
            if handler in saved_handlers:
                continue
            # ``ext://sys.stderr`` handlers wrap pytest's captured stream,
            # which may already be closed by the time teardown runs.
            with contextlib.suppress(ValueError, OSError):
                handler.flush()
            with contextlib.suppress(ValueError, OSError):
                handler.close()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


@pytest.fixture()
def rss_source() -> Source:
    """A minimal RSS-type source for testing."""
    return Source(
        name="Test Blog",
        scrape_url="https://blog.example.com/feed.xml",
        priority="high",
        fetch_type="rss",
        category="general_ai",
        tags=["test", "ai"],
    )


@pytest.fixture()
def atom_source() -> Source:
    """A minimal Atom-type source for testing."""
    return Source(
        name="Test Atom Feed",
        scrape_url="https://blog.example.com/atom.xml",
        priority="medium",
        fetch_type="atom",
        category="engineering_ai",
    )


@pytest.fixture()
def website_source() -> Source:
    """A website-type source (no registered fetcher yet)."""
    return Source(
        name="Test Website",
        scrape_url="https://news.example.com/",
        priority="low",
        fetch_type="website",
        category="general_ai",
    )


@pytest.fixture()
def sample_raw_record(rss_source: Source) -> RawRecord:
    """A sample raw record for downstream tests."""
    return RawRecord(
        source=rss_source,
        title="New AI Model Released",
        url="https://blog.example.com/new-ai-model",
        description="A groundbreaking new AI model has been released.",
        pub_date=None,
        engagement=Engagement(points=42, comments=5),
    )


@pytest.fixture()
def make_configuration() -> Callable[..., Configuration]:
    """Factory for an in-memory :class:`Configuration`.

    Mirrors the shipped ``config/config.toml`` presets so scoring and window
    resolution behave like production without touching disk.
    """

    def _make(
        sources: list[Source] | None = None,
        priority_presets: dict[str, float] | None = None,
        category_window_hours: dict[str, int] | None = None,
        user_agent: str = "test-agent/1.0",
    ) -> Configuration:
        return Configuration(
            user_agent=user_agent,
            priority_presets=priority_presets
            or {"high": 1.0, "medium": 0.65, "low": 0.35},
            category_window_hours=category_window_hours
            or {
                "general_ai": 24,
                "engineering_ai": 720,
                "research": 168,
                "startup": 72,
                "vendor": 72,
                "community": 48,
            },
            sources=sources or [],
        )

    return _make


@pytest.fixture()
def make_candidate() -> Callable[..., Candidate]:
    """Factory for :class:`Candidate` objects with sensible defaults.

    Dedup and selection tests need many lightly-varying candidates; every
    argument is keyword-overridable and the URL is normalized and the ID
    derived from it, exactly as the collect stage does.
    """

    def _make(
        title: str = "Some AI headline",
        url: str = "https://example.com/story",
        source_name: str = "Test Blog",
        category: Category = "general_ai",
        priority: Priority = "high",
        tags: list[str] | None = None,
        fetch_type: FetchType | None = "rss",
        text: str = "",
        score: float = 0.0,
        breakdown: ScoreBreakdown | None = None,
        pub_date: datetime | None = None,
        engagement: Engagement | None = None,
        matched_terms: list[str] | None = None,
    ) -> Candidate:
        normalized_url = norm_url(url)
        source = Source(
            name=source_name,
            scrape_url=f"https://example.com/{source_name.lower()}/feed",
            priority=priority,
            category=category,
            fetch_type=fetch_type,
            tags=tags or [],
        )
        return Candidate(
            id=entry_id(normalized_url, title),
            title=title,
            url=normalized_url,
            source=source,
            category=category,
            pub_date=pub_date,
            text=text,
            description=text,
            matched_terms=matched_terms or [],
            engagement=engagement or Engagement(),
            score_breakdown=breakdown or ScoreBreakdown(score=score),
            registry_category=category,
            source_priority=priority,
        )

    return _make


# --------------------------------------------------------------------------- #
# Sample XML feeds
# --------------------------------------------------------------------------- #

SAMPLE_RSS_20 = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Blog</title>
    <link>https://blog.example.com</link>
    <description>A test blog</description>
    <item>
      <title>First Post</title>
      <link>https://blog.example.com/first-post</link>
      <description>&lt;p&gt;Hello world&lt;/p&gt;</description>
      <pubDate>Mon, 01 Sep 2025 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second Post</title>
      <link>https://blog.example.com/second-post</link>
      <description>No HTML here</description>
      <pubDate>Tue, 02 Sep 2025 08:30:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

SAMPLE_ATOM = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <id>urn:uuid:feed-123</id>
  <entry>
    <title>Atom Entry</title>
    <id>urn:uuid:entry-456</id>
    <link href="https://blog.example.com/atom-entry"/>
    <summary>An atom summary</summary>
    <published>2025-09-01T10:00:00Z</published>
  </entry>
</feed>
"""

SAMPLE_RSS_BARE_AMPERSAND = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test</title>
    <link>https://example.com</link>
    <description>Test feed</description>
    <item>
      <title>AT&amp;T &amp; Verizon deal</title>
      <link>https://example.com/at-t</link>
      <description>AT&amp;T announced a new deal &amp; more</description>
    </item>
  </channel>
</rss>
"""

SAMPLE_RDF = """\
<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel rdf:about="https://example.com">
    <title>RDF Feed</title>
    <link>https://example.com</link>
    <description>An RDF/RSS 1.0 feed</description>
  </channel>
  <item rdf:about="https://example.com/rdf-item">
    <title>RDF Item</title>
    <link>https://example.com/rdf-item</link>
    <description>rdf description</description>
    <dc:date>2025-09-01T00:00:00Z</dc:date>
  </item>
</rdf:RDF>
"""

# RSS channel WITHOUT <description> — this shape crashed the strict
# rss-parser library used previously.
SAMPLE_RSS_NO_CHANNEL_DESCRIPTION = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Minimal</title>
    <link>https://example.com</link>
    <item>
      <title>Only item</title>
      <link>https://example.com/only</link>
    </item>
  </channel>
</rss>
"""

SAMPLE_RSS_CDATA = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>CDATA feed</title>
    <link>https://example.com</link>
    <description>CDATA test</description>
    <item>
      <title><![CDATA[<b>Breaking</b> AI news]]></title>
      <link>https://example.com/cdata</link>
      <description><![CDATA[<p>HTML body</p>]]></description>
    </item>
  </channel>
</rss>
"""

# Item has no <description>; content:encoded carries the body.
SAMPLE_RSS_CONTENT_ENCODED = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Encoded</title>
    <link>https://example.com</link>
    <description>content:encoded test</description>
    <item>
      <title>Encoded Item</title>
      <link>https://example.com/enc</link>
      <content:encoded><![CDATA[<p>encoded body</p>]]></content:encoded>
    </item>
  </channel>
</rss>
"""

# Atom with multiple <link> elements per entry.
SAMPLE_ATOM_MULTI_LINK = """\
<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Multi-link feed</title>
  <id>urn:uuid:feed-1</id>
  <updated>2025-09-01T00:00:00Z</updated>
  <entry>
    <title>Entry A</title>
    <id>urn:uuid:a</id>
    <updated>2025-09-01T00:00:00Z</updated>
    <link rel="self" href="https://example.com/feed/a"/>
    <link rel="alternate" href="https://example.com/article-a"/>
    <summary>summary a</summary>
  </entry>
  <entry>
    <title>Entry B</title>
    <id>urn:uuid:b</id>
    <updated>2025-09-01T00:00:00Z</updated>
    <link rel="self" href="https://example.com/feed/b"/>
    <summary>summary b</summary>
  </entry>
</feed>
"""

# XML with a non-UTF-8 encoding declared in the prolog (é = 0xE9).
SAMPLE_RSS_WINDOWS_1252 = (
    b'<?xml version="1.0" encoding="windows-1252"?>\n'
    b'<rss version="2.0"><channel><title>Caf\xe9</title>'
    b"<link>https://example.com</link><description>d</description>"
    b"<item><title>Caf\xe9 AI</title><link>https://example.com/cafe</link>"
    b"<description>espresso</description></item></channel></rss>"
)

# --- Hostile XML samples (security tests) ---

BILLION_LAUGHS_XML = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
 <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
 <!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">
 <!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">
 <!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">
 <!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">
]>
<rss version="2.0"><channel><title>&lol9;</title><link>x</link>
<description>d</description></channel></rss>
"""

XXE_XML = b"""<?xml version="1.0"?>
<!DOCTYPE rss [
 <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<rss version="2.0"><channel><title>&xxe;</title><link>x</link>
<description>d</description></channel></rss>
"""
