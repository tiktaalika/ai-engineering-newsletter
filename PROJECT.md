# PROJECT.md — AI Engineering Newsletter & GitHub Trend Monitor

> Complete functional specification for 1-to-1 replication.  
> All schemas, formulas, regex strings, token values, and constants are given verbatim.

---

## 1. Project Overview

A two-subsystem, auditable, bilingual (English + Chinese) daily newsletter and static website pipeline that:

1. **AI Engineering Newsletter** — Collects, scores, deduplicates, and selects English-language AI news from a curated source registry into a daily issue with four sections (General AI Top 10, Engineering AI Top 5, Biomedical AI Top 5, Research Radar) and renders a static HTML site.
2. **GitHub Trend Monitor** — Collects GitHub repository metadata across six domains (AI Agent, MCP, RAG, LLM Infrastructure, Simulation, Engineering AI), scores them with a transparent formula, and produces weekly/monthly Markdown reports rendered into the same site.

**License:** MIT  
**Language:** Python 3.11+  
**Primary runtime:** GitHub Actions (no-API public mode); optional OpenAI API for Chinese summaries.

---

## 2. Directory Layout

```
/
├── config/
│   ├── keywords.json              # Topic filter terms for news scoring
│   ├── sources.yaml               # Curated news source registry (primary)
│   ├── sources.json               # Legacy fallback (deprecated)
│   └── trend_report.yaml          # GitHub trend monitor config
├── data/
│   ├── digests/                   # Daily output artifacts
│   │   ├── YYYY-MM-DD-candidates.json
│   │   ├── YYYY-MM-DD-briefing-input.md
│   │   ├── YYYY-MM-DD-final.md
│   │   ├── YYYY-MM-DD-paper-push.json   (Fridays only)
│   │   └── site_summaries.json            (LLM-cached Chinese summaries)
│   ├── snapshots/YYYY-MM-DD/      # Raw trend data cache per collection day
│   ├── repos.jsonl                # Append-only normalized repo records
│   └── logs/trend_report.log
├── reports/
│   ├── weekly/YYYY-MM-DD-weekly-github-trends.md
│   └── monthly/YYYY-MM-DD-monthly-github-trends.md
├── scripts/
│   ├── build_digest_candidates.py # News collection, scoring, selection
│   ├── generate_daily_report.py   # Deterministic Markdown from candidates JSON
│   ├── render_digest_site.py      # Static HTML site generator
│   ├── generate_weekly_paper_push.py  # Friday arXiv paper discovery
│   ├── generate_site_summaries.py # OpenAI Chinese summary generator
│   └── check_recent_duplicates.py # Pre-publish quality gate
├── site/
│   ├── index.html                 # Language selector landing page
│   ├── en/index.html              # English edition (paginated)
│   ├── en/page/N/index.html
│   ├── zh/index.html              # Chinese edition (paginated)
│   ├── zh/page/N/index.html
│   └── trends/{weekly,monthly}/YYYY-MM-DD-label/index.html
├── tests/
│   ├── test_trend_report.py
│   ├── test_generate_daily_report.py
│   ├── test_source_registry.py
│   └── test_weekly_paper_push.py
├── trend_report/                  # Python package for GitHub trend monitor
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── collectors.py
│   ├── classifier.py
│   ├── scoring.py
│   ├── reports.py
│   ├── storage.py
│   ├── logging_utils.py
│   └── dummy_data.py
├── .github/workflows/
│   ├── daily-no-api-site.yml      # Daily newsletter + site deploy
│   ├── github-trend-report.yml    # Weekly/monthly trend reports
│   └── pages.yml                  # Manual Pages deploy
├── .gitlab-ci.yml                 # GitLab mirror CI
├── requirements.txt               # Full deps (openai, python-dotenv, PyYAML)
├── requirements-no-api.txt        # No-API deps (PyYAML only)
├── requirements-llm.txt           # LLM-only deps (openai, python-dotenv)
└── .env.example
```

---

## 3. Subsystem A — AI Engineering Newsletter

### 3.1 Source Registry (`config/sources.yaml`)

Each source entry must contain:

```yaml
name: string            # Human-readable source name
url: string             # Feed URL, site URL, or API endpoint
source_type: string     # One of: rss, website, github, arxiv, linkedin_manual, x_api, newsletter, manual
category: string        # One of: general_ai, engineering_ai, research, startup, vendor, community
priority: string        # One of: high, medium, low
tags: [string]          # Classification and filtering tags
notes: string           # Human-readable description
enabled: boolean        # Whether the source is active
fetch_type: string      # Optional override: rss, google_news_rss, hn_algolia, reddit_json, sitemap_or_search, web_search_query
max_entries: int        # Optional cap per source (default 25)
query: string           # Optional search query for google_news_rss or web_search sources
```

**Priority score mapping:**

```python
priority_scores = {
    "high": 1.0,
    "medium": 0.65,
    "low": 0.35,
}
```

**Category window hours:**

```python
category_window_hours = {
    "general_ai": 24,
    "engineering_ai": 720,
    "research": 168,
    "startup": 72,
    "vendor": 72,
    "community": 48,
}
```

**Fetch type resolution logic** (function `fetch_kind`):

1. If `fetch_type` is explicitly set, use it.
2. Else if `source_type == "rss"`, use `"rss"`.
3. Else if `source_type == "website"`, use `"sitemap_or_search"`.
4. Else if `source_type` in `{manual, newsletter, linkedin_manual, x_api, github, arxiv}`, use `"web_search_query"`.
5. Otherwise use the `source_type` value or `"web_search_query"`.

**Auto-query generation:** For `web_search_query` or `sitemap_or_search` sources without an explicit `query`:

```python
query = f'site:{urllib.parse.urlsplit(source["url"]).netloc} AI'
```

**Canonical category mapping:**

```python
def canonical_category(category: str) -> str:
    if category in {"engineering_ai", "cae_ai_engineering"}:
        return "engineering_ai"
    if category in {"research", "startup", "vendor", "community"}:
        return category
    return "general_ai"
```

**Guo Yichen reference tag:** Sources tagged `guo_yichen_reference` form the preferred pool for General AI Top 10 selection. These include official AI company feeds, research labs, developer-tool blogs, expert newsletters, and startup/VC feeds.

### 3.2 Keyword Filters (`config/keywords.json`)

Two top-level buckets:

```json
{
  "general_ai": {
    "required_language": "en",
    "include": ["AI", "artificial intelligence", "generative AI", "genAI", "LLM", ...],
    "exclude": ["Adobe Illustrator", "A.I. generated image only", "AI washing", ...]
  },
  "cae_ai_engineering": {
    "required_language": "en",
    "core_include": ["CAE", "computer-aided engineering", "engineering simulation", "simulation", "physics-informed neural network", "PINN", "surrogate model", ...],
    "ai_include": ["AI", "artificial intelligence", "machine learning", "ML", "deep learning", "neural", "agent", "surrogate", "physics-informed", "PINN", "operator learning", "neural operator", "generative", "copilot", "automation"],
    "include": ["CAE", "computer-aided engineering", "simulation", "engineering simulation", "digital twin", ...],
    "exclude": ["computer-aided education", "CAE exam", "surrogate model virus", "TSX:CAE", "CFD trading", "traders", ...]
  }
}
```

Keyword matching uses case-insensitive substring containment: `term.lower() in haystack`.

### 3.3 Collection Pipeline (`scripts/build_digest_candidates.py`)

**Execution order:**

1. Load source registry (`sources.yaml` or legacy `sources.json`).
2. Load keyword filters (`keywords.json`).
3. For each enabled source, fetch records via the appropriate parser.
4. For each fetched record, apply filters, score, and collect candidates.
5. Deduplicate by normalized URL.
6. Sort candidates by score descending.
7. Cap at 100 candidates.
8. Run selection algorithms for each section.
9. Write three output files.

**Supported fetch types and their parsers:**

| `kind` | Parser | Description |
|---|---|---|
| `rss` | `parse_rss` | Parse RSS/Atom XML; extract title, link, description, pubDate |
| `google_news_rss` | `parse_rss` (with constructed URL) | `https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en` |
| `hn_algolia` | `parse_hn` | Algolia HN API: `https://hn.algolia.com/api/v1/search_by_date` with `tags=story`, `numericFilters=created_at_i>{cutoff}` |
| `reddit_json` | `parse_reddit` | Reddit JSON API (`.json` suffix) |
| `web_search_query` | `web_search_placeholder` | Generates a manual-search placeholder record (not ranked) |
| `sitemap_or_search` | `parse_website_discovery` → `parse_sitemap_source` → `link_records_from_html` | Try sitemap XML first, fall back to same-site HTML link extraction, then to search placeholder |

**RSS XML parsing:** Handles both RSS 2.0 `<item>` and Atom `<entry>` elements. XML entity cleanup:

```python
raw = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)", "&amp;", raw)
```

**Sitemap parsing:**

- Tries `{scheme}://{netloc}/sitemap.xml` and `{base_path}/sitemap.xml`.
- Parses `<sitemap>` index files for child sitemaps (max 20 child sitemaps).
- Parses `<url>` entries for `{loc}` and `{lastmod}`.
- Caps at 500 URLs per source.

**Same-site link extraction** (regex):

```python
re.finditer(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", raw, flags=re.IGNORECASE | re.DOTALL)
```

Same-site filter: scheme must be `http`/`https`, netloc must match source netloc. Caps at 200 links per source.

**Datetime parsing** (function `parse_datetime`):

1. `email.utils.parsedate_to_datetime(value)` — handles RFC 2822.
2. Fallback formats: `"%Y-%m-%dT%H:%M:%SZ"`, `"%Y-%m-%dT%H:%M:%S%z"`, `"%Y-%m-%d"`.
3. All datetimes normalized to UTC.

**URL normalization** (function `norm_url`):

```python
def norm_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    kept = [(k, v) for k, v in query if not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), urllib.parse.urlencode(kept), "")
    )
```

**English language detection** (function `language_looks_english`):

```python
def language_looks_english(text: str) -> bool:
    letters = re.findall(r"[A-Za-z]", text)
    if len(letters) < 20:
        return False
    ascii_ratio = sum(1 for ch in text if ord(ch) < 128) / max(len(text), 1)
    return ascii_ratio > 0.82
```

**Core terms gate:** A candidate must match at least one term from both `core_include` and `ai_include` (for engineering) or the general equivalent.

**Text cleaning:**

```python
def clean_text(value: str | None) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()
```

### 3.4 Scoring Formula (News Candidates)

**Function:** `score_candidate(source, engagement, matches, published_at, now, window_hours, priority_scores, text)`

**Composite score:**

```
score = 32 * source_priority
      + 22 * novelty
      + 20 * general_relevance
      + 14 * engineering_relevance
      +  8 * research_relevance
      + 10 * engineering_workflow_ai_boost  (conditional)
      + 14 * log_scale(points, 1200)
      + 10 * log_scale(comments, 800)
      + 10 * log_scale(upvotes, 5000)
```

**Sub-scores:**

| Sub-score | Formula |
|---|---|
| `source_priority` | `priority_scores[source.priority]` (high=1.0, medium=0.65, low=0.35) |
| `novelty` | `recency_boost(published_at, now, window_hours)` — see below |
| `general_relevance` | `min(len(matched_terms) / 6, 1.0)` |
| `engineering_relevance` | `1.0` if `source.category == "engineering_ai"`, else `min(count_of_engineering_terms_in_text / 4, 1.0)` |
| `research_relevance` | `1.0` if `source.category == "research"`, else `min(count_of_research_terms_in_text / 3, 1.0)` |
| `log_scale(value, cap)` | `min(log1p(value) / log1p(cap), 1.0)` if value > 0, else `0.0` |

**Recency boost:**

```python
def recency_boost(published_at, now, window_hours):
    if not published_at:
        return 0.35
    age_hours = max((now - published_at).total_seconds() / 3600, 0)
    if age_hours > window_hours:
        return 0.0
    return max(0.15, 1.0 - (age_hours / window_hours) * 0.75)
```

**Engineering workflow AI boost:** +10 points when ALL of these are true:

1. `canonical_category(source.category) == "engineering_ai"`
2. Any of these terms in text: `"agentic ai", "ai agent", "agents", "llm", "natural language", "post-processing", "result browser", "report template", "code generation", "sandboxed environment", "simulation workflow", "simulation automation", "plot agent", "variable metadata"`
3. Any of these terms in text: `"simulation", "cae", "simcenter", "amesim", "cfd", "fea", "digital twin"`

**Engineering relevance terms** (matched against lowercased text):

```python
engineering_terms = (
    "cae", "computer-aided engineering", "engineering simulation", "simulation", "cad",
    "spdm", "plm", "digital twin", "physical ai", "scientific ml", "industrial ai",
    "cfd", "fea", "surrogate", "neural operator", "physics-informed",
)
```

**Research relevance terms:**

```python
research_terms = (
    "arxiv", "paper", "research", "benchmark", "dataset", "model release", "nature",
    "science robotics", "papers with code", "hugging face papers",
)
```

### 3.5 Category Inference

After scoring, the candidate's category is inferred:

```python
def infer_candidate_category(source_category, text, score_parts):
    category = canonical_category(source_category)
    if category == "engineering_ai":
        return "engineering_ai"
    lower = text.lower()
    industrial_terms = ("industrial ai", "ai for engineering", "engineering ai", "engineering simulation",
                        "computer-aided engineering", "simulation", "cae", "cad", "cfd", "fea", "spdm",
                        "plm", "digital twin", "manufacturing", "robotics", "surrogate model",
                        "physics-informed", "scientific ml")
    ai_terms = ("ai", "artificial intelligence", "machine learning", "ml", "agent", "copilot", "generative", "neural")
    if score_parts.get("engineering_relevance_score", 0) >= 0.5:
        return "engineering_ai"
    if any(term in lower for term in industrial_terms) and any(term in lower for term in ai_terms):
        return "engineering_ai"
    if category == "research":
        return "research"
    return "general_ai"
```

### 3.6 Event Deduplication

**Canonical event key** — hardcoded mappings for known recurring news stories:

```python
def canonical_event_key(title: str) -> str | None:
    text = title.lower()
    # Examples:
    if "openai" in text and any(term in text for term in ("ipo", "initial public", "go public", "public offering", "stock market", "s-1", "sec")):
        return "openai-ipo"
    if "openai" in text and any(term in text for term in ("price cut", "price cuts", "slashing prices", "drastic price")) and "anthropic" in text:
        return "openai-anthropic-price-war"
    if "visa" in text and any(term in text for term in ("openai", "chatgpt")) and any(term in text for term in ("payment", "payments", "agentic commerce", "ai agent")):
        return "visa-openai-agent-payments"
    # ... (14 total canonical keys)
    return None
```

**Token-based similarity:**

```python
def event_tokens(title: str) -> set[str]:
    title = re.sub(r"\s+-\s+[^-]+$", "", title.lower())  # strip source suffix after last " - "
    tokens = re.findall(r"[a-z0-9]+", title)
    return {
        token for token in tokens
        if len(token) > 2 and token not in COMMON_EVENT_WORDS and token not in SOURCE_SUFFIXES
    }
```

**Stopword sets:**

```python
COMMON_EVENT_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "is", "it", "its",
    "new", "of", "on", "or", "s", "says", "the", "to", "with", "report", "reports",
    "reported", "exclusive", "breaking", "news", "via",
}
SOURCE_SUFFIXES = {
    "reuters", "bbc", "cnbc", "forbes", "techcrunch", "bloomberg", "wsj", "financial",
    "times", "guardian", "yahoo", "finance", "ap", "axios", "nytimes", "meta", "openai",
}
```

**Same-event detection** (`is_same_event`):

1. If `event_url_key(left.url) == event_url_key(right.url)` (normalized scheme+netloc+path, no trailing slash), return `True`.
2. If `canonical_event_key(left.title) == canonical_event_key(right.title)`, return `True`.
3. Token overlap rules (all must pass):
   - Same source, `|intersection| >= 2`, and `|intersection| / min(|left_tokens|, |right_tokens|) >= 0.67` → same event.
   - `|intersection| >= 5` and `|intersection| / min(|left_tokens|, |right_tokens|) >= 0.5` → same event.
   - `|intersection| >= 4` and `|intersection| / |union| >= 0.42` → same event.
4. Otherwise → different events.

### 3.7 Topic Diversification

**Topic keys** — assigned by scanning lowercased `title + text`:

```python
def topic_key(candidate) -> str:
    text = f"{candidate.title} {candidate.text}".lower()
    if any(term in text for term in ("payment", "payments", "agentic commerce", "wallet", "checkout", "stablecoin", "micropayment")):
        return "payments_agent_commerce"
    if any(term in text for term in ("regulation", "policy", "law", "senate", "washington", "government", "safety", "data retention", "data terms")):
        return "policy_safety_governance"
    if any(term in text for term in ("data center", "datacenter", "compute", "gpu", "chip", "nvidia", "oracle", "power grid", "energy")):
        return "infrastructure_compute"
    if any(term in text for term in ("coding", "developer", "software engineering", "ai-native development", "programming")):
        return "software_development"
    if any(term in text for term in ("health", "medical", "medicine", "clinical", "hospital", "drug discovery")):
        return "health_bio"
    if any(term in text for term in ("robot", "robotics", "autonomous vehicle", "drone")):
        return "robotics_autonomy"
    if any(term in text for term in ("model", "claude", "chatgpt", "openai", "anthropic", "deepmind", "llm", "benchmark")):
        return "frontier_models"
    if candidate.category in {"engineering_ai", "cae_ai_engineering"}:
        if any(term in text for term in ("cfd", "fea", "cae", "simulation", "surrogate", "digital twin", "neural operator")):
            return "cae_simulation"
    return "other"
```

**Selection constraints:**

| Constraint | General AI | Engineering AI | Biomedical AI |
|---|---|---|---|
| Max items | 10 | 5 | 5 |
| Max per topic | 2 | 2 | 2 |
| Max per source (first pass) | 2 | 1 | 2 |
| Google News cap | 2 | 1 | 1 |
| Historical dedup lookback | 7 days | 30 days | 30 days |
| Requires `guo_yichen_reference` | Yes (first pass) | No | No |
| Requires `trusted_or_curated` | Yes (General + Engineering) | Yes | Yes |

**Multi-pass selection** (`select_unique_events`): The selector runs 4 progressive passes with gradually relaxed constraints:

1. **Pass 1:** Full constraints (guo preference, trusted-only, topic cap, source cap, history dedup).
2. **Pass 2:** Relax topic cap (keep source cap and history dedup).
3. **Pass 3:** Relax source cap (keep history dedup).
4. **Pass 4:** Relax topic cap again.
5. **Fallback:** If `require_guo_general=True` and fewer than `limit` selected, re-run with `require_guo_general=False`.

### 3.8 Biomedical AI Detection

**Function:** `is_medical_bio_ai(candidate)`

Matches if ANY of these regex patterns match in lowercased `title + text + source_tags`:

```python
medical_patterns = (
    r"\bhealthcare\b", r"\bmedical\b", r"\bmedicine\b", r"\bclinical\b",
    r"\bhospital\b", r"\bpatient\b", r"\bphysician\b", r"\bdrug discovery\b",
    r"\bdrug development\b", r"\bpharma\b", r"\bpharmaceutical\b", r"\bbiotech\b",
    r"\bbiomedical\b", r"\bbioinformatics\b", r"\bgenomics\b", r"\bgenomic\b",
    r"\bgenetics\b", r"\bgenetic\b", r"\bgene therapy\b", r"\bgene editing\b",
    r"\bcrispr\b", r"\bbiology\b", r"\bbiological\b", r"\blife sciences\b",
    r"\bbiomarker\b", r"\btherapeutic\b", r"\bdiagnostic\b",
)
```

Selection uses the same multi-pass logic with `select_medical_bio_ai`, filtering for `canonical_category in {general_ai, research}`, biomedical pattern match, and trusted/curated status.

### 3.9 Candidate Data Schema

Each candidate in `YYYY-MM-DD-candidates.json`:

```json
{
  "id": "16-char hex SHA1 prefix of normalized URL",
  "title": "string",
  "url": "string (normalized, UTM-stripped)",
  "source": "source name from registry",
  "source_kind": "rss | google_news_rss | sitemap_or_search | hn_algolia | reddit_json | web_search_query",
  "category": "general_ai | engineering_ai | research",
  "published_at": "ISO 8601 datetime string or null",
  "text": "string (max 1200 chars)",
  "matched_terms": ["term1", "term2"],
  "engagement": {
    "points": "int or null",
    "comments": "int or null",
    "upvotes": "int or null"
  },
  "score": "float (composite score)",
  "score_reasons": ["source_priority=1.00", "novelty=0.94", ...],
  "general_ai_score": "float 0-1",
  "engineering_relevance_score": "float 0-1",
  "research_relevance_score": "float 0-1",
  "novelty_score": "float 0-1",
  "source_priority_score": "float 0-1",
  "source_tags": ["tag1", "tag2"],
  "registry_category": "general_ai | engineering_ai | research | startup | vendor | community",
  "source_priority": "high | medium | low"
}
```

**Entry ID generation:**

```python
def entry_id(url: str, title: str) -> str:
    raw = (url or title).lower().encode("utf-8", "replace")
    return hashlib.sha1(raw).hexdigest()[:16]
```

### 3.10 Output JSON Schema (`YYYY-MM-DD-candidates.json`)

```json
{
  "run_log": {
    "generated_at": "ISO 8601 datetime",
    "window_hours": 24,
    "source_count": "int (enabled sources)",
    "fetched_count": "int (raw records fetched)",
    "filtered_count": "int (passed keyword/score filter)",
    "duplicate_count": "int (removed by URL dedup)",
    "failures": [{"source": "name", "error": "message"}]
  },
  "selection_policy": {
    "general_ai": "string",
    "engineering_ai": "string",
    "medical_bio_ai": "string",
    "research_radar": "string",
    "ranking_note": "string",
    "history_deduplication": "string"
  },
  "top_10_general_ai": ["Candidate objects"],
  "top_5_engineering_ai": ["Candidate objects"],
  "top_5_medical_bio_ai": ["Candidate objects"],
  "top_5_cae_ai_engineering": ["same as top_5_engineering_ai (legacy alias)"],
  "research_radar": ["Candidate objects"],
  "supplemental_search_tasks": [
    {
      "source": "name",
      "category": "category",
      "query": "search query",
      "url": "Google search URL",
      "source_type": "type",
      "priority": "priority",
      "tags": "comma-separated",
      "note": "string"
    }
  ],
  "watchlist_updates": ["same as supplemental_search_tasks"],
  "top_100_news_candidates": ["Candidate objects (top 100 by score)"]
}
```

### 3.11 Daily Report Generator (`scripts/generate_daily_report.py`)

Reads `YYYY-MM-DD-candidates.json` and produces `YYYY-MM-DD-final.md`.

**Topic label inference:**

```python
def topic_label(item):
    text = f"{item['title']} {item['text']}".lower()
    if any(t in text for t in ("cfd", "cae", "fea", "simulation", "surrogate", "digital twin", "physics ai")):
        return "CAE / simulation"
    if any(t in text for t in ("agent", "agentic", "workflow", "copilot")):
        return "agent workflow"
    if any(t in text for t in ("model", "llm", "benchmark", "evaluation", "reasoning")):
        return "model / evaluation"
    if any(t in text for t in ("chip", "gpu", "compute", "data center", "infrastructure")):
        return "AI infrastructure"
    if any(t in text for t in ("medical", "clinical", "pharma", "drug", "genomics", "health")):
        return "medical / bio AI"
    if any(t in text for t in ("robot", "robotics", "humanoid", "manufacturing", "industrial")):
        return "industrial / robotics"
    return "AI update"
```

**Report sections:**

```markdown
# AI Engineering Daily Report - YYYY-MM-DD
## Run Log
## Top 10 General AI News
## Top 5 Engineering AI News
## Top 5 Medical, Medicine, and Bio/Genetics AI News
## Research Radar
## Watchlist Updates
## Why It Matters
## Source Failures (if any)
```

### 3.12 Friday Paper Push (`scripts/generate_weekly_paper_push.py`)

Runs only on Fridays (weekday == 4). Queries arXiv Atom API.

**arXiv query:**

```
search_query = all:"physics informed" OR all:"neural operator" OR all:"surrogate model"
               OR all:"computational fluid dynamics" OR all:"finite element"
               OR all:"topology optimization" OR all:"digital twin" OR all:"engineering design"
sortBy=submittedDate, sortOrder=descending, max_results=50
```

**API endpoint:** `https://export.arxiv.org/api/query`

**Engineering pattern filter** (any must match in `title + abstract`):

```python
ENGINEERING_PATTERNS = (
    r"\bcad\b", r"\bcae\b", r"\bcfd\b", r"\bfea\b", r"finite elements?",
    r"digital twins?", r"physics[- ]informed", r"neural operators?",
    r"surrogate models?", r"\bpde[- ]constrained\b", r"topology optimization",
    r"engineering design", r"fluid dynamics", r"computational mechanics",
    r"multiphysics", r"turbulence", r"computational engineering",
)
```

**AI pattern filter** (any must match):

```python
AI_PATTERNS = (
    r"artificial intelligence", r"machine learning", r"deep learning",
    r"physics[- ]informed", r"neural", r"surrogate", r"foundation model",
    r"large language model", r"reinforcement learning", r"digital twins?",
)
```

**Exclusion filter** (none must match):

```python
EXCLUDED_PATTERNS = (
    r"\bofdm\b", r"wireless", r"telecommunication", r"ultra-dense network",
    r"quantum", r"rehabilitation", r"clinical", r"biomedical",
)
```

**Recency filter:** Published within `[issue_date - 8 days, issue_date]`.

**Deduplication:** Checks previous `*-paper-push.json` files within 60 days by canonical arXiv URL.

**Canonical URL extraction:**

```python
def canonical_url(url: str) -> str:
    match = re.search(r"arxiv\.org/(?:abs|pdf)/(\d+\.\d+)", url)
    return f"https://arxiv.org/abs/{match.group(1)}" if match else url.split("?", 1)[0]
```

**Minimum threshold:** Requires at least 3 papers before writing; raises `RuntimeError` otherwise (does not overwrite previous files).

**Paper push JSON schema:**

```json
{
  "title_zh": "每周 AI-for-Engineering 论文推送",
  "title_en": "Weekly AI-for-Engineering Paper Push",
  "intro_zh": "string",
  "intro_en": "string",
  "cae_sources_checked": ["arXiv public Atom API"],
  "cae_papers": [
    {
      "title": "string",
      "url": "https://arxiv.org/abs/XXXX.XXXXX",
      "source": "arXiv",
      "published": "YYYY-MM-DD",
      "authors": ["Author 1", "Author 2"],
      "summary_en": "first 500 chars of abstract",
      "summary_zh": "英文摘要：" + first 500 chars of abstract,
      "why": "Selected for direct relevance to AI-enabled engineering analysis, design, or simulation."
    }
  ],
  "biomedical_papers": []
}
```

### 3.13 Chinese Summary Generator (`scripts/generate_site_summaries.py`)

Uses OpenAI API (optional). Caches results in `data/digests/site_summaries.json`.

**Cache schema:**

```json
{
  "candidate_id_16char_hex": "2-4 sentence Chinese summary string",
  ...
}
```

**OpenAI call:**

```python
model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
temperature = 0.2
max_completion_tokens = 4000
system_prompt = "你是严谨的中文科技新闻编辑，只输出有效 JSON。"
```

**User prompt template:**

```
为下面每条英文 AI 新闻写 2-4 句中文摘要。摘要必须直接说明发生了什么、关键事实或数据、
以及它对行业或工程实践的重要性。每条约 80-160 个中文字符，准确、克制，不要编造，
不要使用'值得跟进'、'主题偏向'、'建议关注'、'出现一条更新'等空泛模板。
如果输入只是市场观点而非技术进展，要明确说明；如果材料不足，不要补充输入中没有的事实。
只返回 JSON 数组，每个对象包含 id 和 zh_summary。

{JSON batch of up to 10 items}
```

**Batch size:** 10 items per API call.

**Environment variables:**

```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini
OPENAI_CLASSIFIER_MODEL=gpt-5-nano
OPENAI_DAILY_MAX_TOKENS=120000
OPENAI_MONTHLY_BUDGET_USD=5
```

### 3.14 Pre-publish Quality Gate (`scripts/check_recent_duplicates.py`)

Runs before site deploy. Returns exit code 1 on failure.

**Quality checks:**

1. `source_count > 0` (registry was loaded).
2. `fetched_count > 0` OR `top_100_news_candidates` is non-empty.
3. Candidate file is not marked as placeholder.
4. General AI section has at least 5 publishable items.
5. Total publishable items across all sections ≥ 10.
6. No same-issue cross-section duplicates.
7. No recent-history duplicates within `--lookback-days` (default 7).

---

## 4. Subsystem B — GitHub Trend Monitor

### 4.1 Configuration (`config/trend_report.yaml`)

```yaml
categories:
  AI Agent:
    keywords: [agent, agents, autonomous agent, multi-agent, crewai, langgraph, autogen, openmanus, browser-use]
  MCP:
    keywords: [mcp, model context protocol, mcp-server, mcp-client, claude desktop, tool server]
  RAG:
    keywords: [rag, retrieval augmented generation, retrieval, vector database, embeddings, document qa, knowledge base, llamaindex, haystack, ragflow]
  LLM Infrastructure:
    keywords: [llm inference, serving, vllm, llama.cpp, ollama, sglang, tensorrt-llm, litellm, gateway, fine-tuning, eval, observability]
  Simulation:
    keywords: [simulation, cae, cfd, fem, finite element, multiphysics, digital twin, ansys, comsol, openfoam, paraview, surrogate model]
  Engineering AI:
    keywords: [engineering ai, ai engineering, simulation ai, design automation, cad, cae, plm, mbse, digital thread, engineering knowledge, scientific ai]

scoring:
  normalized_star_growth: 0.55
  normalized_total_stars: 0.25
  normalized_recent_activity: 0.10
  normalized_fork_growth: 0.10

collection:
  per_category_limit: 25
  request_delay_seconds: 1.0
  user_agent: "github-trend-monitor/0.1 (+https://github.com/)"
  cache_ttl_hours: 12
  include_dummy_on_failure: true
  sources:
    github_search: true
    github_trending: true
    oss_insight_trending: true
    gitstar_ranking: true
    star_history: true

reporting:
  weekly_top_n: 20
  monthly_top_n: 30
  emerging_max_total_stars: 2500
  emerging_min_growth: 5
```

### 4.2 Data Model (`trend_report/models.py`)

```python
@dataclass
class RepoRecord:
    snapshot_date: str       # "YYYY-MM-DD"
    full_name: str           # "owner/repo"
    url: str                 # "https://github.com/owner/repo"
    description: str
    language: str            # "Python", "TypeScript", etc.
    stars: int
    forks: int
    open_issues: int
    last_update: str         # "YYYY-MM-DD"
    created_at: str          # ISO 8601
    pushed_at: str           # ISO 8601
    author: str              # owner login
    category: str            # "AI Agent", "MCP", etc.
    matched_categories: list[str]
    topics: list[str]        # GitHub topics
    source: str              # "github_search", "github_trending", "dummy", etc.
    stars_gained_hint: int   # for dummy/fallback records
    forks_gained_hint: int   # for dummy/fallback records
    source_notes: list[str]
```

### 4.3 Collection Sources (`trend_report/collectors.py`)

#### 4.3.1 GitHub Search API

**Query construction per category:**

```python
since = (datetime.now(timezone.utc) - timedelta(days=45)).date().isoformat()
for keyword in category_keywords[:6]:
    query_term = f'"{keyword}"' if " " in keyword else keyword
    query = f"{query_term} in:name,description pushed:>={since} stars:>10"
    params = urlencode({"q": query, "sort": "stars", "order": "desc", "per_page": per_keyword})
    url = f"https://api.github.com/search/repositories?{params}"
```

**per_keyword** = `max(3, min(10, per_category_limit // max(1, len(keywords)) + 1))`

**Request headers:**

```python
{"User-Agent": "github-trend-monitor/0.1 (+https://github.com/)", "Accept": "application/vnd.github+json"}
```

Optional `Authorization: Bearer {GITHUB_TOKEN}` when token is available.

**Response cache:** Raw JSON saved to `data/snapshots/YYYY-MM-DD/github_search_metadata_{slug(category)}_{slug(keyword)}.json`.

**Slug function:**

```python
def slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")
```

#### 4.3.2 GitHub Trending Page

Fetches `https://github.com/trending?since=weekly`, parses HTML for `<a>` links matching `owner/repo` pattern (exactly 2 path segments, excluding `/topics/`, `/trending/`, `/collections/`). Caps at 50 links.

#### 4.3.3 OSS Insight Trending

Fetches `https://ossinsight.io/collections/trending-repos`, extracts `owner/repo` links. Caps at 80 links.

#### 4.3.4 GitStar Ranking

Fetches `https://gitstar-ranking.com/repositories`, extracts `owner/repo` links. Caps at 80 links.

#### 4.3.5 Star History

Writes a placeholder note JSON only:

```json
{
  "status": "not_scraped",
  "reason": "Star History is primarily useful as a visual validation source; GitHub snapshots are used for numeric growth."
}
```

### 4.4 Classifier (`trend_report/classifier.py`)

**Keyword-based text matching:**

```python
def classify_repo(repo, categories):
    text_parts = [
        repo.get("full_name", ""),
        repo.get("name", ""),
        repo.get("description", ""),
        repo.get("language", ""),
        " ".join(repo.get("topics") or []),
    ]
    text = " ".join(str(part).lower() for part in text_parts if part)
    scores = Counter()
    for category, config in categories.items():
        for keyword in config.get("keywords", []):
            keyword_l = keyword.lower()
            if keyword_l in text:
                scores[category] += 2 if " " in keyword_l else 1
    if not scores:
        return "Unclassified", []
    ranked = [category for category, _ in scores.most_common()]
    return ranked[0], ranked
```

Multi-word keywords score 2 points; single-word keywords score 1 point.

### 4.5 Scoring Formula (`trend_report/scoring.py`)

```
trend_score = 0.55 * normalized_star_growth
            + 0.25 * normalized_total_stars
            + 0.10 * normalized_recent_activity
            + 0.10 * normalized_fork_growth
```

**Normalization:**

```python
def safe_norm(value, max_value):
    if max_value <= 0:
        return 0.0
    return min(1.0, max(0.0, float(value) / float(max_value)))
```

**Star growth calculation:** For each repo, find the latest snapshot on or before `end` date and the baseline snapshot on or before `start` date. `stars_gained = max(0, latest.stars - baseline.stars)`. If no baseline exists, use `stars_gained_hint`.

**Recent activity score:**

```python
def activity_score(record, end):
    raw = record.pushed_at or record.last_update or record.snapshot_date
    pushed_day = datetime.fromisoformat(raw[:10]).date()
    age_days = max(0, (end - pushed_day).days)
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.7
    if age_days <= 90:
        return 0.4
    return 0.1
```

**Sort order:** Primary by `trend_score` descending, then `stars_gained` descending, then `stars` descending.

### 4.6 Period Anchoring

**Weekly period:**

```python
def weekly_period(settings, today=None):
    current = today or date.today()
    days_since_sunday = (current.weekday() + 1) % 7
    end = current - timedelta(days=days_since_sunday)
    start = end - timedelta(days=7)
    return Period("weekly", start, end, ...)
```

The weekly period is always anchored to the most recent Sunday, even if the GitHub Actions run starts late.

**Monthly period:**

```python
def monthly_period(settings, today=None):
    end = today or date.today()
    first_this_month = end.replace(day=1)
    previous_end = first_this_month - timedelta(days=1)
    previous_start = previous_end.replace(day=1)
    return Period("monthly", previous_start, previous_end, ...)
```

### 4.7 Report Output Format

**Filename:** `reports/{weekly,monthly}/YYYY-MM-DD-{label}-github-trends.md`

**Report structure:**

```markdown
# GitHub {Weekly,Monthly} Trend Report

Period: YYYY-MM-DD to YYYY-MM-DD

Scoring formula:
`trend_score = 0.55 * normalized_star_growth + 0.25 * normalized_total_stars + 0.1 * normalized_recent_activity + 0.1 * normalized_fork_growth`

## Overall Ranking (top N table)
## Core Metrics
### Fastest-Growing Repositories (sorted by stars_gained desc)
### Highest Total Stars (sorted by stars desc)
## Category Rankings (one per category)
### {Category}
#### Top by Star Growth
#### Top by Total Stars
#### Newly Emerging (stars ≤ 2500 AND stars_gained ≥ 5)
## Author / Organization Ranking (top 20)
## Collection Notes
```

**Emerging repo filter:**

```python
emerging_max_total_stars = 2500
emerging_min_growth = 5
```

### 4.8 Storage (`trend_report/storage.py`)

**JSONL format** (`data/repos.jsonl`): One JSON object per line, fields match `RepoRecord.to_dict()` with `ensure_ascii=False, sort_keys=True`.

### 4.9 Dummy Fallback Data (`trend_report/dummy_data.py`)

12 seed repositories used when live collection returns zero records:

```python
SEED_REPOS = [
    ("openai/openai-agents-python", "AI Agent", "Python", 18400, 2100, "SDK for building AI agents and tool workflows.", ["agent", "tools"]),
    ("modelcontextprotocol/servers", "MCP", "TypeScript", 24500, 3200, "Reference MCP servers for the Model Context Protocol.", ["mcp", "tools"]),
    ("run-llama/llama_index", "RAG", "Python", 46200, 6100, "Data framework for LLM applications and retrieval augmented generation.", ["rag", "llamaindex"]),
    ("vllm-project/vllm", "LLM Infrastructure", "Python", 55700, 9200, "High-throughput and memory-efficient inference engine for LLMs.", ["inference", "serving"]),
    ("openfoam/openfoam-dev", "Simulation", "C++", 8900, 2300, "Open source computational fluid dynamics simulation toolbox.", ["cfd", "simulation"]),
    ("ansys/pyansys", "Engineering AI", "Python", 1800, 420, "Pythonic engineering simulation automation across Ansys products.", ["cae", "engineering"]),
    ("browser-use/browser-use", "AI Agent", "Python", 38800, 4100, "Make websites accessible for AI agents.", ["browser-use", "agent"]),
    ("microsoft/autogen", "AI Agent", "Python", 49200, 7600, "Multi-agent conversation framework for AI applications.", ["multi-agent", "autogen"]),
    ("qdrant/qdrant", "RAG", "Rust", 28600, 1900, "Vector database for embeddings and semantic search.", ["vector-database", "embeddings"]),
    ("sgl-project/sglang", "LLM Infrastructure", "Python", 18900, 2400, "Fast serving framework for large language models.", ["llm", "serving"]),
    ("Kitware/ParaView", "Simulation", "C++", 2600, 1100, "Scientific visualization for simulation and engineering data.", ["simulation", "paraview"]),
    ("langchain-ai/langgraph", "AI Agent", "Python", 35200, 5600, "Build resilient language agents as graphs.", ["agent", "langgraph"]),
]
```

Dummy growth hint: `max(6, int(stars * (0.01 + (idx % 5) * 0.004)))`.

---

## 5. Static Site Renderer (`scripts/render_digest_site.py`)

### 5.1 Page Structure

| Path | Content |
|---|---|
| `site/index.html` | Language selector landing page |
| `site/en/index.html` | English edition page 1 |
| `site/en/page/N/index.html` | English edition page N |
| `site/zh/index.html` | Chinese edition page 1 |
| `site/zh/page/N/index.html` | Chinese edition page N |
| `site/trends/weekly/YYYY-MM-DD-weekly/index.html` | Weekly trend report page |
| `site/trends/monthly/YYYY-MM-DD-monthly/index.html` | Monthly trend report page |

**Pagination:** `ARCHIVE_PAGE_SIZE = 7` (7 days per page).

**History dedup start date:** `HISTORY_DEDUP_START = date(2026, 7, 5)`.

### 5.2 Archive Entries

Generates entries for every calendar day from the oldest candidate date to the newest, marking days without candidates as "missing" (displayed with dashed borders).

### 5.3 Day Item Hydration

When a `*-final.md` exists for a date:

1. Parse Markdown sections by heading patterns.
2. Match items by URL against `top_100_news_candidates` in the candidates JSON.
3. Merge final.md's Chinese headlines with candidate metadata (scores, engagement, source tags).
4. Re-run deduplication against previously published days.

When no `*-final.md` exists:

1. Re-run the full selection algorithm from the candidates JSON.
2. Apply cross-section deduplication (General AI items excluded from Engineering AI history, etc.).

### 5.4 English Summary Generation

```python
def english_summary(item):
    text = re.sub(r"\s+", " ", item.get("text", "")).strip()
    title = item.get("title", "").strip()
    if title and text.lower().startswith(title.lower()):
        text = text[len(title):].strip(" -:.,")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    summary = " ".join(sentence for sentence in sentences[:2] if sentence)
    if not summary:
        summary = "Selected for its relevance, source priority, recency, and cross-source/topic evidence."
    if len(summary) > 340:
        summary = summary[:337].rstrip() + "..."
    return summary
```

### 5.5 Effective Source Extraction

For Google News items, the actual source is extracted from the title suffix:

```python
def effective_source(item):
    source = str(item.get("source", "")).strip()
    title = str(item.get("title", "")).strip()
    if source.lower().startswith("google news") and " - " in title:
        inferred = title.rsplit(" - ", 1)[-1].strip()
        if inferred:
            return inferred
    return source or "unknown"
```

### 5.6 Engineering AI Exclusion List

Items excluded from the Engineering AI section by text match:

```python
excluded_terms = {
    "analysts offer insights", "industrial goods companies", "tsx:cae", "forex.com",
    "ai index cfd", "capital.com", "tradingview", "finance magnates", "traders",
    "trading", "brokers", "cfd access", "surrogate model virus", "chatbots in a simulation",
}
```

### 5.7 Trend Report HTML Rendering

Markdown-to-HTML converter handles:

- Headings (`#` through `####`) with auto-generated `id` anchors.
- Unordered lists (`- ` prefix).
- Tables (pipe-delimited with `---` separator row).
- Inline links `[text](url)` → `<a href="url">text</a>`.
- Inline code `` `code` `` → `<code>code</code>`.

---

## 6. CI/CD Workflows

### 6.1 Daily No-API Newsletter (`daily-no-api-site.yml`)

**Schedule:** 4 attempts at `06:18`, `06:48`, `07:18`, `07:48` UTC (best-effort).

**Steps:**

1. Checkout.
2. Set up Python 3.11.
3. Install `requirements-no-api.txt`.
4. Build candidates: `python3 scripts/build_digest_candidates.py --window-hours 24 --date "$DATE"`.
5. Generate daily report: `python3 scripts/generate_daily_report.py --date "$DATE"`.
6. Generate Chinese summaries (conditional on `OPENAI_API_KEY`): `python3 scripts/generate_site_summaries.py --date "$DATE"`.
7. Generate Friday paper push (continue-on-error): `python3 scripts/generate_weekly_paper_push.py --date "$DATE"`.
8. Render site: `python3 scripts/render_digest_site.py`.
9. Check duplicates: `python3 scripts/check_recent_duplicates.py --date "$DATE" --lookback-days 7`.
10. Commit artifacts: `data/digests/*-candidates.json`, `*-briefing-input.md`, `*-final.md`, `*-paper-push.json`, `site_summaries.json`, `site/**`.
11. Deploy to GitHub Pages.

### 6.2 GitHub Trend Report (`github-trend-report.yml`)

**Schedule:**

- Weekly: `0 20 * * 0` (Sunday 20:00 UTC).
- Monthly: `15 7 1 * *` (1st of month 07:15 UTC).

**Steps:**

1. Checkout, Python 3.11, install deps.
2. Collect: `python -m trend_report collect` (with `GITHUB_TOKEN`).
3. Weekly report: `python -m trend_report weekly` (on Sunday schedule or manual).
4. Monthly report: `python -m trend_report monthly` (on 1st-of-month schedule or manual).
5. Render site: `python3 scripts/render_digest_site.py`.
6. Commit: `data/snapshots/**`, `data/repos.jsonl`, `data/logs/trend_report.log`, `reports/weekly/**`, `reports/monthly/**`, `site/**`.
7. Deploy to GitHub Pages.

### 6.3 Manual Pages Deploy (`pages.yml`)

Manual trigger only. Runs duplicate check then deploys existing `site/` directory.

### 6.4 Concurrency

All three workflows share `concurrency: { group: pages, cancel-in-progress: false }`.

---

## 7. Manual Run Commands

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# Newsletter
python3 scripts/build_digest_candidates.py --window-hours 24
python3 scripts/generate_daily_report.py
python3 scripts/generate_weekly_paper_push.py --force  # any day
python3 scripts/generate_site_summaries.py            # needs OPENAI_API_KEY
python3 scripts/render_digest_site.py
python3 scripts/check_recent_duplicates.py --date $(date +%F) --lookback-days 7

# Trend Monitor
python -m trend_report collect
python -m trend_report weekly
python -m trend_report monthly
python -m trend_report all
```

---

## 8. Dependencies

**`requirements.txt`** (full):

```
openai>=1.0.0
python-dotenv>=1.0.0
PyYAML>=6.0.0
```

**`requirements-no-api.txt`**:

```
PyYAML>=6.0.0
```

**`requirements-llm.txt`**:

```
openai>=1.0.0
python-dotenv>=1.0.0
```

**Standard library only** (no additional deps): `urllib.request`, `urllib.parse`, `urllib.error`, `xml.etree.ElementTree`, `html.parser`, `json`, `hashlib`, `re`, `math`, `time`, `email.utils`, `argparse`, `dataclasses`, `pathlib`, `logging`, `collections`, `datetime`, `os`, `sys`, `typing`.

---

## 9. User Agent Strings

| Subsystem | User Agent |
|---|---|
| News digest | `news-push-ai-digest/0.1 (+auditable personal digest)` |
| Trend monitor | `github-trend-monitor/0.1 (+https://github.com/)` |
| Paper push | `ai-engineering-newsletter/1.0 (public weekly paper discovery)` |

---

## 10. Deployment URLs

```
https://tiktaalika.github.io/ai-engineering-newsletter/     # Language selector
https://tiktaalika.github.io/ai-engineering-newsletter/en/  # English edition
https://tiktaalika.github.io/ai-engineering-newsletter/zh/  # Chinese edition
```

---

## 11. HTTP Caching Strategy

- **News digest:** No HTTP caching; each source fetched fresh per run.
- **Trend monitor:** File-based cache at `data/snapshots/YYYY-MM-DD/*.json`. If the cache file exists, it is read instead of making a new HTTP request (`get_json` and `get_text` functions in `collectors.py`). Redirects followed up to 2 hops for `get_text`.
- **LLM summaries:** Persistent JSON cache at `data/digests/site_summaries.json`. Previously summarized items (keyed by 16-char hex ID) are not re-queried.

---

## 12. Error Handling Strategy

| Failure mode | Behavior |
|---|---|
| Source fetch error (HTTP, timeout, parse) | Logged to `run_log.failures`; pipeline continues with other sources |
| Zero live records collected (trend monitor) | Dummy fallback records written with `source: "dummy"` |
| Zero candidates after filtering (newsletter) | Empty sections written explicitly; daily report shows "no items" message |
| Paper push < 3 papers | `RuntimeError` raised; existing files left unchanged |
| GitHub API rate limit | Collection returns early with records gathered so far |
| Pre-publish duplicate detected | Exit code 1; deploy blocked |
| No OpenAI API key | Chinese summaries skipped; English edition still publishes |
