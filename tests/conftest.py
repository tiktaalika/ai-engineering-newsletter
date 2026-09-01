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
