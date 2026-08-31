"""Shared pytest fixtures for the newsletter test suite."""

from __future__ import annotations

import pytest

from newsletter.models import (
    Engagement,
    RawRecord,
    Source,
)


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
