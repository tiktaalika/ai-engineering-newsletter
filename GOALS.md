# GOALS.md — AI Engineering Newsletter V2 Rewrite

> Structured roadmap for migrating the monolithic v1 codebase into a modern, modular, async-first v2 architecture.
> v1 codebase in main branch, v2 in dev branch
> Reference: [PROJECT.md](./PROJECT.md) for full v1 functional specification.

---

## Legend

- **[ ]** Not started
- **[~]** In progress
- **[x]** Complete

---

## Goal 1 — Modern Python Standards

Migrate from flat scripts + requirements.txt to a properly structured, typed, linted Python package with modern tooling.

### 1.1 Project Structure & Packaging
- [x] Switch to `pyproject.toml` with Hatch build backend
- [x] Adopt `uv` for dependency management and lockfile
- [x] Use `src/` layout (`src/newsletter/`)
- [x] Define stable package exports via `__init__.py`
- [x] Add `[project.optional-dependencies]` for LLM features (`openai`, `python-dotenv`) — **`llm` extra defined**
- [x] Add `py.typed` marker for PEP 561 compliance

### 1.2 Tooling & Quality Gates
- [x] Ruff for linting and formatting
- [x] `ty` for static type checking
- [x] pytest + pytest-asyncio for testing
- [x] CI pipeline (GitHub Actions: lint → type-check → test)
- [x] Add coverage reporting (pytest-cov) — **branch coverage enabled via `--cov-branch` in `addopts`; no fail-under threshold enforced**
- [x] Add `ruff check --select I` for import sorting — **configured via `[tool.ruff.lint] select`**
- [ ] Add pre-commit hooks or `uv run` task aliases for local dev

### 1.3 Type System & Data Models
- [x] `attrs`/`cattrs` for structured configuration models
- [x] Define all domain models as `attrs` frozen classes with full type annotations (all in `src/newsletter/models.py`)
  - [x] `Source` (config registry entry)
  - [x] `RawRecord` (fetched item before scoring)
  - [x] `Candidate` (scored, filtered item)
  - [x] `Engagement` (points, comments, upvotes)
  - [x] `ScoreBreakdown` (individual sub-scores + composite)
  - [x] `DigestIssue` (final selection output)
  - [x] `RepoRecord` (GitHub trend data)
  - [x] `Period` (weekly/monthly anchor)
  - [x] `PaperPush` (Friday arXiv results)
  - [x] `Paper` (single arXiv paper entry)
  - [x] `RunLog` (pipeline execution metadata)
  - [x] `FetchSuccess` / `FetchFailure` / `FetchResult` (fetch outcome union)
- [~] Replace all `dict[str, Any]` patterns in old code with typed models — **v2 modules are typed end-to-end; the only remaining `dict[str, Any]` is `http.fetch_json()`'s return, which is inherent to untyped JSON**
- [~] Use `typing.Protocol` for interfaces (fetchers, scorers, renderers) — **`Fetcher` protocol done (`fetchers/base.py`); scorer/renderer protocols land with Goals 6–7**

### 1.4 Configuration System
- [x] TOML-based config replacing YAML/JSON
- [x] `Configuration.load()` with cattrs structuring and validation
- [ ] Port keywords config from `config/keywords.json` → TOML
- [ ] Port trend report config from `config/trend_report.yaml` → TOML
- [ ] Add config schema validation (required fields, enum constraints)
- [ ] Support environment variable overrides (e.g. `NEWSLETTER_OPENAI_API_KEY`)
- [x] Add `--config` CLI flag for custom config path — **`collect --config/-c`; `_resolve_config_path()` falls back to `<project_root>/config/config.toml`**

### 1.5 Logging & Observability
- [x] Structured logging via `logging.toml` config
- [x] Separate audit log (file) and error log (rotating file)
- [x] Replace all `print()` calls in `main.py` with proper logger usage
- [x] Add structured run-log model (replaces `run_log` dict in candidates JSON) — `RunLog` attrs class defined
- [x] Add per-source fetch timing and error tracking — **`elapsed_ms` on `FetchSuccess`/`FetchFailure`; `orchestrate._fetch_single()` times with `time.monotonic()` and captures the exception type + message**

### 1.6 CLI & Entry Points
- [x] Typer for CLI (`[project.scripts]`) — `newsletter` entry point wired to `main()`
- [x] Implement `main()` entry point — **Typer `app()`; loads config, configures logging, installs signal handlers, runs the pipeline under `asyncio.run()`, maps exit codes (0 ok / 1 error / 130 cancelled)**
- [~] Implement subcommands:
  - [~] `newsletter collect` — **concurrent async fetch + `RawRecord`→`Candidate` conversion works (deterministic IDs, normalized URLs); scoring, dedup, selection and the `*-candidates.json` artifact are still TODO**
  - [ ] `newsletter report` — generate daily Markdown (replaces `generate_daily_report.py`)
  - [ ] `newsletter site` — render static HTML (replaces `render_digest_site.py`)
  - [ ] `newsletter papers` — Friday arXiv push (replaces `generate_weekly_paper_push.py`)
  - [ ] `newsletter summaries` — Chinese LLM summaries (replaces `generate_site_summaries.py`)
  - [ ] `newsletter check` — pre-publish quality gate (replaces `check_recent_duplicates.py`)
  - [ ] `newsletter trends collect` — GitHub trend collection
  - [ ] `newsletter trends weekly` — weekly trend report
  - [ ] `newsletter trends monthly` — monthly trend report
  - [ ] `newsletter run-all` — full pipeline orchestration
- [~] Add `--date`, `--window-hours`, `--dry-run` global options — **all three implemented on `collect` (`--date/-d`, `--window-hours/-w`, `--dry-run`); not yet an app-level callback shared by every subcommand**

---

## Goal 2 — Expanded Testing

Build a comprehensive test suite that covers every pipeline stage with unit, integration, and snapshot tests.

### 2.1 Test Infrastructure
- [x] pytest + pytest-asyncio configured
- [x] pytest-mock available
- [x] pytest-cov in dev dependencies — **wired through `addopts`, so CI reports coverage on every `uv run pytest`**
- [~] Create shared fixtures module (`tests/conftest.py`)
  - [ ] Fixture: sample `Configuration` — **tests still write TOML inline (`_MINIMAL_CONFIG` in `test_main.py`)**
  - [x] Fixture: sample `Source` objects (each fetch type) — **`rss_source`, `atom_source`, `website_source`**
  - [~] Fixture: sample `RawRecord` / `Candidate` objects — **`sample_raw_record` exists; no `Candidate` fixture until scoring lands**
  - [~] Fixture: mock `httpx.AsyncClient` (via `respx` or manual) — **`respx` is activated per test rather than through a shared fixture**
  - [x] Fixture: temp directory for output artifacts — **`tmp_path`, plus the autouse `isolated_logging` fixture that redirects the project root so tests never write into the committed `logs/`**
- [x] Add `respx` for httpx mock/stubbing in tests — **in `[dependency-groups].dev`; used by `test_http.py`, `test_rss_fetcher.py`, `test_orchestrate.py`**
- [ ] Add snapshot/golden-file testing for report output (e.g. `syrupy` or manual JSON comparison) — **golden *inputs* already live in `conftest.py` (RSS/Atom/RDF/CDATA/windows-1252/hostile XML); output snapshots wait on the Goal 7 renderers**

### 2.2 Unit Tests — Configuration
- [x] Basic config loading test — **plus a `fetch_type`-optional / `fetch_kind()` auto-resolution test (2 tests total)**
- [ ] Test missing config file → `ConfigurationError` — **⚠️ decision needed: `Configuration.load()` raises `FileNotFoundError` today (caught in `collect`), not `ConfigurationError`**
- [ ] Test invalid TOML → `ConfigurationError`
- [ ] Test missing required fields → `ClassValidationError`
- [ ] Test source enum validation (fetch_type, category, priority)
- [ ] Test keyword config loading and term matching

### 2.3 Unit Tests — Source Fetchers (one per fetcher type)
- [x] `test_rss_fetcher.py` — RSS 2.0 parsing, Atom parsing, malformed XML handling, XML entity cleanup, date parsing, registry dispatch — **53 tests, including billion-laughs / XXE hardening via `defusedxml`**
- [ ] `test_google_news_fetcher.py` — query URL construction, result parsing
- [ ] `test_hn_fetcher.py` — Algolia API response parsing, cutoff filtering
- [ ] `test_reddit_fetcher.py` — JSON API response parsing, rate limit handling
- [ ] `test_arxiv_fetcher.py` — Atom API parsing, engineering/AI pattern matching
- [ ] `test_website_fetcher.py` — sitemap XML parsing, HTML link extraction, fallback chain
- [ ] `test_youtube_fetcher.py` — YouTube RSS feed parsing
- [ ] Each fetcher test covers: happy path, empty response, HTTP error, parse error, timeout

### 2.4 Unit Tests — Scoring & Filtering
- [ ] `test_scoring.py` — composite score formula, each sub-score, edge cases (null engagement, missing dates)
- [ ] `test_keywords.py` — include/exclude term matching, case insensitivity, core terms gate
- [ ] `test_dedup.py` — URL normalization, canonical event keys, token similarity thresholds
- [ ] `test_selection.py` — multi-pass selection, topic diversification, per-source caps, guo preference
- [ ] `test_category.py` — canonical category mapping, category inference, biomedical detection
- [ ] `test_text.py` — `clean_text`, `language_looks_english`, `english_summary`

### 2.5 Unit Tests — Report Generation
- [ ] `test_daily_report.py` — Markdown structure, section headings, topic labels
- [ ] `test_paper_push.py` — arXiv query, pattern filters, recency filter, dedup against history
- [ ] `test_site_summaries.py` — cache hit/miss, batch API call structure, prompt construction

### 2.6 Unit Tests — Trend Monitor
- [ ] `test_trend_classifier.py` — keyword scoring, multi-category matching
- [ ] `test_trend_scoring.py` — normalization, star growth, activity score
- [ ] `test_trend_reports.py` — weekly/monthly period anchoring, report structure
- [ ] `test_trend_storage.py` — JSONL read/write, snapshot caching

### 2.7 Integration Tests
- [ ] `test_pipeline_collect.py` — end-to-end collect with mocked HTTP (multiple sources → candidates JSON)
- [ ] `test_pipeline_report.py` — candidates JSON → final Markdown
- [ ] `test_pipeline_site.py` — candidates + reports → HTML output
- [ ] `test_quality_gate.py` — duplicate detection across issues, publishable item counts

### 2.8 Coverage & CI
- [x] Configure pytest-cov with `--cov=src/newsletter --cov-report=term-missing` — **in `[tool.pytest.ini_options].addopts` together with `--cov-branch`; currently 96%**
- [ ] Set minimum coverage threshold in CI (target: 80% line coverage) — **no `--cov-fail-under` yet**
- [ ] Add coverage badge or report in PR comments

### 2.9 Unit Tests — Async HTTP, Orchestration & CLI

> Landed with Goals 3.1–3.4; no section existed for them in the original plan.

- [x] `test_http.py` (20 tests) — backoff + jitter bounds, retryable vs non-retryable statuses, `MaxRetriesExceeded`, `fetch_text/json/bytes`, `DomainRateLimiter` pacing
- [x] `test_orchestrate.py` (16 tests) — concurrency cap, per-source timeout, fault isolation, disabled-source skipping, result ordering
- [x] `test_main.py` (26 tests) — deterministic candidate IDs + URL normalization, CLI options and exit codes, cancellation → 130, repo-`logs/` isolation regression
- [x] `test_text.py` (8 tests) / `test_dedup.py` (9 tests) — `entry_id` and `norm_url` (Goals 6.1, 6.4)

---

## Goal 3 — Async Source Fetching

Replace all synchronous HTTP with async I/O for concurrent, rate-limited, fault-isolated source collection.

### 3.1 HTTP Client Migration
- [x] Replace `httpx.Client` with `httpx.AsyncClient` in all fetch paths — **one shared `AsyncClient` is created in `_run_pipeline()` and passed down through `fetch_all_sources()` → fetchers**
- [~] Create `newsletter/http.py` — shared async HTTP utilities:
  - [x] `async def fetch_text(client, url, *, timeout, max_attempts, max_backoff, rate_limiter) -> str`
  - [x] `async def fetch_json(client, url, ...) -> dict[str, Any]`
  - [x] `async def fetch_bytes(client, url, ...) -> bytes`
  - [ ] Response caching layer (file-based, keyed by URL + date)
  - [x] Retry with exponential backoff for transient errors (429, 503, timeouts) — **`backoff_delay()` with jitter; `HTTPStatusFetchError` for non-retryable 4xx/5xx, `MaxRetriesExceeded` when attempts run out**
- [x] Remove all `urllib.request` usage from ported code — **v2 uses `httpx` for I/O and `urllib.parse` only for URL normalization**

### 3.2 Concurrent Fetching Orchestration
- [x] Implement `async def fetch_all_sources(sources, client, ...) -> list[FetchResult]` — **`orchestrate.py`; skips disabled sources, preserves input order, logs the success/failure tally**
  - [x] Fault isolation via `asyncio.gather()` — **each task is wrapped in `_fetch_single()`, which catches every exception itself, so `return_exceptions=True` is unnecessary and one failure can never cancel siblings**
  - [x] Per-source timeout (configurable, default 15s) — **`asyncio.wait_for(..., source_timeout)`**
  - [x] Per-source error capture → `FetchSuccess | FetchFailure`
- [x] Add configurable concurrency limit (e.g. `asyncio.Semaphore(10)`) — **`concurrency` kwarg, `DEFAULT_CONCURRENCY = 10`**
- [~] Add rate limiting per domain (e.g. token bucket or simple delay) — **`DomainRateLimiter` implemented + tested and accepted as an optional `rate_limiter=` kwarg on `fetch_text/json/bytes`, but the pipeline never instantiates one yet**
  - [ ] Respect `request_delay_seconds` from config — **not a field on `Source`/`Configuration` yet**
  - [ ] Special handling for GitHub API (rate limit headers)
  - [ ] Special handling for Reddit (User-Agent requirement, `.json` suffix)

### 3.3 Async Pipeline Stages
- [~] `collect` stage: async fetch → sync score/filter (CPU-bound scoring stays sync) — **async fetch + candidate conversion done; scoring/filtering still stubbed to `ScoreBreakdown(score=0.0)` (Goal 6)**
- [ ] `trends collect` stage: async GitHub API calls with snapshot caching
- [ ] `papers` stage: async arXiv API query
- [ ] `summaries` stage: async OpenAI API calls with batch grouping
- [ ] Wrap sync scoring/dedup/selection in `asyncio.to_thread()` if needed for large datasets

### 3.4 Entry Point Integration
- [x] `main()` uses `asyncio.run()` as the event loop entry — **inside the Typer `collect` command**
- [x] Typer async command support (via `asyncio.run()` wrapper) — **sync command wrapping `asyncio.run(_run_pipeline(...))`**
- [x] Graceful shutdown on SIGINT/SIGTERM (cancel pending tasks, flush logs) — **`_install_signal_handlers()` cancels the running task, which propagates through `gather`; `CancelledError` → exit 130; no-ops where `add_signal_handler` is unsupported (Windows)**

---

## Goal 4 — Modular Source Fetchers

Extract the monolithic fetch logic into a pluggable fetcher system where each source type has its own isolated implementation.

### 4.1 Fetcher Protocol & Registry
- [x] Define `Fetcher` protocol in `newsletter/fetchers/base.py`:
  ```python
  class Fetcher(Protocol):
      @property
      def fetch_type(self) -> str: ...
      async def fetch(self, source: Source, client: httpx.AsyncClient, *, cutoff: datetime) -> list[RawRecord]: ...
  ```
- [x] Create `FetchResult` model (defined in `src/newsletter/models.py`):
  - [x] `FetchSuccess` — source, records, elapsed_ms
  - [x] `FetchFailure` — source, error, elapsed_ms
  - [x] `type FetchResult = FetchSuccess | FetchFailure`
- [x] Implement fetcher registry in `newsletter/fetchers/__init__.py`:
  - [x] `FETCHER_REGISTRY: dict[str, Fetcher]` — maps `fetch_type` string → implementation
  - [x] `get_fetcher(source: Source) -> Fetcher` — resolves fetcher using v1's `fetch_kind` logic
  - [x] Auto-discovery via module imports or explicit registration

### 4.2 Individual Fetcher Implementations

Each fetcher lives in its own module under `newsletter/fetchers/`:

#### `newsletter/fetchers/rss.py` — RSS / Atom Feeds
- [x] Port `parse_rss` logic from v1 `build_digest_candidates.py` — **extracted into `RSSFetcher.fetch()` in `fetchers/rss.py`**
- [x] Handle RSS 2.0 `<item>` and Atom `<entry>` elements — **both paths handled via `_extract_items()` dispatching to correct model path**
- [x] XML entity cleanup regex — **`_clean_xml_entities()` with bare `&` fix**
- [x] `pubDate` parsing with multi-format fallback — `parse_pub_date()` with RFC 2822 + ISO 8601 + Atom `published`/`updated`
- [x] Support `fetch_type`: `rss`, `atom`, `rdf` — **all dispatched via registry to `RSSFetcher`**
- [x] Extract to standalone `newsletter/fetchers/rss.py` module
- [x] Async migration — **`RSSFetcher.fetch()` is `async` and goes through `http.fetch_bytes()` (retry + backoff)**

#### `newsletter/fetchers/google_news.py` — Google News RSS
- [ ] Construct search URL: `https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en`
- [ ] Auto-generate query from source URL if not explicit (`site:{netloc} AI`)
- [ ] Parse response via RSS fetcher (reuse `rss.py` internally)
- [ ] Support `max_entries` cap

#### `newsletter/fetchers/hn.py` — Hacker News (Algolia API)
- [ ] Query `https://hn.algolia.com/api/v1/search_by_date` with `tags=story`, `numericFilters`
- [ ] Parse JSON response → `RawRecord` list
- [ ] Extract points from API response
- [ ] Respect cutoff timestamp

#### `newsletter/fetchers/reddit.py` — Reddit JSON API
- [ ] Fetch `.json` suffixed URLs
- [ ] Parse listing structure → `RawRecord` list
- [ ] Extract upvotes, comment count as engagement
- [ ] Handle Reddit rate limiting and User-Agent requirements

#### `newsletter/fetchers/website.py` — Website Discovery (Sitemap → HTML → Search)
- [ ] **Phase 1: Sitemap parsing**
  - [ ] Try `{scheme}://{netloc}/sitemap.xml` and `{base_path}/sitemap.xml`
  - [ ] Parse `<sitemap>` index files for child sitemaps (max 20)
  - [ ] Parse `<url>` entries for `{loc}` and `{lastmod}`
  - [ ] Cap at 500 URLs per source
- [ ] **Phase 2: HTML link extraction** (fallback)
  - [ ] Regex-based `<a href>` extraction with same-site filter
  - [ ] Cap at 200 links per source
- [ ] **Phase 3: Search placeholder** (final fallback)
  - [ ] Generate manual-search placeholder record (not ranked)

#### `newsletter/fetchers/arxiv.py` — arXiv API
- [ ] Query `https://export.arxiv.org/api/query` with structured `search_query`
- [ ] Parse Atom response → paper records with title, abstract, authors, published date
- [ ] Canonical URL extraction (`arxiv.org/abs/XXXX.XXXXX`)
- [ ] Engineering pattern filter + AI pattern filter + exclusion filter
- [ ] Recency filter and historical dedup against previous paper push files

#### `newsletter/fetchers/youtube.py` — YouTube Channel Feeds
- [ ] Parse YouTube RSS feed (`/feeds/videos.xml?channel_id=...`)
- [ ] Extract video title, link, published date, description
- [ ] Map to `RawRecord`

#### `newsletter/fetchers/github.py` — GitHub Search & Trending
- [ ] **GitHub Search API**: keyword queries, per-category, paginated results
- [ ] **GitHub Trending page**: HTML scraping for `owner/repo` links
- [ ] **OSS Insight / GitStar**: supplemental trending source scraping
- [ ] Snapshot caching to `data/snapshots/YYYY-MM-DD/`
- [ ] Auth header injection when `GITHUB_TOKEN` is available

### 4.3 Fetcher Testing Strategy
- [ ] Each fetcher has its own test module (see Goal 2.3)
- [ ] All HTTP calls mocked via `respx` — no network access in unit tests
- [ ] Each fetcher tested with:
  - [ ] Golden-file sample responses (committed to `tests/fixtures/`)
  - [ ] Edge cases: empty feed, malformed XML/JSON, HTTP 404/429/500
  - [ ] Timeout behavior
  - [ ] Engagement extraction accuracy

### 4.4 Fetcher Configuration
- [ ] Each `Source` in config specifies `fetch_type` explicitly
- [ ] Auto-resolution fallback (v1 `fetch_kind` logic) preserved for backward compat
- [ ] Per-fetcher config options (e.g. `max_entries`, `query`, `request_delay`)
- [ ] Fetcher-specific `enabled` flag per source for gradual rollout

---

## Goal 5 — Multi-Language Support

Architect the pipeline so language is a first-class axis, enabling bilingual (English + Chinese) output today and additional languages in the future.

### 5.1 Language Abstraction Layer
- [ ] Define `Language` enum / literal type (`"en"`, `"zh"`, extensible)
- [ ] Create `newsletter/i18n.py` module:
  - [ ] `LanguageConfig` model: language code, keyword sets, stopword sets, LLM prompt templates
  - [ ] Load per-language configs from `config/languages/{lang}.toml`
- [ ] Make keyword matching language-aware:
  - [ ] Per-language `include`/`exclude` term lists
  - [ ] Per-language `core_include`/`ai_include` for engineering filter
  - [ ] Replace hardcoded English terms with configurable per-language sets

### 5.2 Language-Aware Pipeline Stages
- [ ] **Filtering**: Apply language-specific keyword filters (v1 `required_language` field becomes per-language config)
- [ ] **Language detection**: Port `language_looks_english()` → `detect_language(text, lang_config)` for configurable detection
- [ ] **Summarization**: Per-language summary generation (English extractive, Chinese LLM-based)
- [ ] **Report generation**: Template strings externalized for i18n (section headings, metadata labels)

### 5.3 LLM Integration (Optional)
- [ ] Isolate OpenAI dependency in `newsletter/llm.py`
- [ ] `async def generate_summaries(candidates, target_lang, ...) -> dict[str, str]`
- [ ] Batch API calls (10 items per request)
- [ ] Cache keyed by `(candidate_id, language)` → summary text
- [ ] Budget enforcement (daily token cap, monthly USD cap)
- [ ] Graceful degradation: skip LLM summaries when API key unavailable

### 5.4 Site Rendering (Bilingual)
- [ ] Language selector landing page (`site/index.html`)
- [ ] Per-language edition pages (`site/{lang}/index.html`, paginated)
- [ ] Port v1 archive entry generation with language-aware content
- [ ] Chinese headline merging from `site_summaries.json` cache

### 5.5 Backburner / Future
- [ ] Add Japanese (`ja`), Korean (`ko`) language configs as examples
- [ ] Machine translation fallback for sources not in target language
- [ ] Per-language source registry sections

---

## Goal 6 — Pipeline Core (Scoring, Dedup, Selection)

Port the v1 scoring, deduplication, and selection algorithms into clean, tested modules.

### 6.1 Text Processing — `newsletter/text.py`
- [ ] `clean_text(value: str | None) -> str` — HTML unescape, tag strip, whitespace normalize
- [ ] `language_looks_english(text: str) -> bool` — ASCII ratio heuristic
- [ ] `english_summary(item: dict) -> str` — extractive 2-sentence summary
- [ ] `effective_source(item: dict) -> str` — resolve Google News source suffix
- [x] `entry_id(url: str, title: str) -> str` — SHA1 16-char hex ID

### 6.2 Keyword Matching — `newsletter/keywords.py`
- [ ] Port keyword filter logic from v1
- [ ] `match_terms(text: str, terms: list[str]) -> list[str]` — case-insensitive substring
- [ ] Core terms gate (must match both `core_include` AND `ai_include` for engineering)
- [ ] General vs. engineering keyword buckets

### 6.3 Scoring — `newsletter/scoring.py`
- [ ] `score_candidate(source, engagement, matches, published_at, now, window_hours, text) -> ScoreBreakdown`
- [ ] All sub-scores: source_priority, novelty, general_relevance, engineering_relevance, research_relevance
- [ ] Engineering workflow AI boost (conditional +10)
- [ ] `recency_boost(published_at, now, window_hours) -> float`
- [ ] `log_scale(value, cap) -> float`

### 6.4 Deduplication — `newsletter/dedup.py`
- [x] `norm_url(url: str) -> str` — UTM stripping, path normalization
- [ ] `canonical_event_key(title: str) -> str | None` — hardcoded known events
- [ ] `event_tokens(title: str) -> set[str]` — tokenization with stopwords
- [ ] `is_same_event(left, right) -> bool` — URL key + canonical key + token overlap rules
- [ ] Cross-section deduplication (items in General AI excluded from Engineering AI history)
- [ ] Historical dedup against previous N days of published issues

### 6.5 Selection — `newsletter/selection.py`
- [ ] `select_unique_events(candidates, limit, ...) -> list[Candidate]` — multi-pass algorithm
  - [ ] Pass 1: full constraints (topic cap, source cap, history dedup, trusted/guo preference)
  - [ ] Pass 2: relax topic cap
  - [ ] Pass 3: relax source cap
  - [ ] Pass 4: relax all caps
  - [ ] Fallback: relax guo preference
- [ ] Topic key assignment (`topic_key(candidate) -> str`)
- [ ] Biomedical AI detection (`is_medical_bio_ai(candidate) -> bool`)
- [ ] Engineering AI exclusion list
- [ ] Category inference (`infer_candidate_category(...)`)

---

## Goal 7 — Report & Site Generation

Port output generation into modular renderers.

### 7.1 Daily Report — `newsletter/reports/daily.py`
- [ ] Read candidates JSON → produce final Markdown
- [ ] Section structure: General AI Top 10, Engineering AI Top 5, Biomedical AI Top 5, Research Radar
- [ ] Topic label inference
- [ ] Run log, watchlist updates, source failure sections

### 7.2 Paper Push — `newsletter/reports/papers.py`
- [ ] arXiv query + filtering + dedup
- [ ] JSON output with bilingual fields
- [ ] Minimum threshold (3 papers)

### 7.3 Trend Reports — `newsletter/reports/trends.py`
- [ ] Weekly and monthly Markdown report generation
- [ ] Overall ranking, core metrics, category rankings, author ranking
- [ ] Emerging repo filter

### 7.4 Site Renderer — `newsletter/site/`
- [ ] Static HTML generation using Jinja2 templates
- [ ] Pagination (7 days per page)
- [ ] Archive entry hydration (from final.md + candidates JSON)
- [ ] Language selector + per-language editions
- [ ] Trend report HTML rendering (Markdown → HTML)
- [ ] CSS/design tokens from STYLE.md

### 7.5 Quality Gate — `newsletter/quality.py`
- [ ] Source count, fetched count, publishable item checks
- [ ] Cross-section duplicate detection
- [ ] Historical dedup within lookback window
- [ ] Exit code 1 on failure (blocks CI deploy)

---

## Goal 8 — CI/CD & Deployment

Modernize the GitHub Actions workflows for the v2 architecture.

### 8.1 CI Pipeline
- [x] Lint (ruff format + check)
- [x] Type check (ty)
- [x] Test (pytest)
- [~] Add coverage reporting step — **coverage is printed by the `pytest` step via `addopts`; no XML report, artifact upload or threshold gate yet**
- [ ] Add matrix testing (Python 3.14 + optional 3.13 backport)

### 8.2 Daily Newsletter Workflow
- [ ] Replace `scripts/*.py` invocations with `newsletter` CLI subcommands
- [ ] Maintain 4-attempt retry schedule
- [ ] Conditional LLM summary step
- [ ] Friday paper push step
- [ ] Site render + quality gate + deploy

### 8.3 Trend Report Workflow
- [ ] Replace `python -m trend_report` with `newsletter trends` subcommands
- [ ] Weekly + monthly schedules
- [ ] Snapshot caching and commit

### 8.4 Artifact Compatibility
- [ ] Ensure output JSON schemas are backward-compatible with v1 consumers
- [ ] Maintain `YYYY-MM-DD-candidates.json`, `*-final.md`, `*-paper-push.json` formats
- [ ] Maintain `data/repos.jsonl` append-only format
- [ ] Maintain `site/` directory structure for GitHub Pages

---

## Phasing

| Phase | Goals | Focus | Status |
|---|---|---|---|
| **Phase 1** | 1.1–1.3, 4.1–4.2 (RSS) | Foundation: models, config, first fetcher working end-to-end | **Complete** — models ✅, TOML config ✅, logging ✅, fetcher protocol + registry ✅, RSS/Atom/RDF fetcher ✅, `py.typed` ✅, coverage + import sorting ✅, CI green ✅ |
| **Phase 2** (Current) | 3.1–3.2, 4.2 (all fetchers) | Async migration + all fetcher implementations | **~60%** — `http.py` (retry/backoff, rate limiter, text/json/bytes) ✅, `orchestrate.py` (semaphore, per-source timeout, fault isolation) ✅, graceful shutdown ✅. Remaining: response caching, wiring a `DomainRateLimiter` into the pipeline, and every non-RSS fetcher — **57 of 125 configured sources are skipped today** (52 `website`, 2 `youtube`, 2 `json`, 1 `api`) |
| **Phase 3** | 6.1–6.5, 2.3–2.4 | Scoring/dedup/selection core + fetcher tests | **Started** — `text.entry_id` (6.1) and `dedup.norm_url` (6.4) landed and are wired into candidate IDs, 17 tests. Scoring (6.2–6.3) is blocked on porting the keyword lists into TOML (1.4) |
| **Phase 4** | 1.6, 7.1–7.5, 2.5–2.7 | CLI, report generation, site rendering, integration tests | **~25%** — `newsletter collect` with `--config/--date/--window-hours/--dry-run` plus 26 CLI/pipeline tests; no renderers and no output artifact yet |
| **Phase 5** | 5.1–5.4, 8.1–8.4 | Language support, CI/CD modernization | **~15%** — CI runs lint → type-check → test on dev/main with coverage printed; no threshold gate, no deploy workflows, no i18n layer |
| **Phase 6** (Backburner) | 5.5 | Additional languages, translation | Not started |

---

## Current State Summary

> **Last updated:** 2026-09-06

### What works today
- **Package structure**: `src/newsletter/` with `pyproject.toml` (Hatch), `uv` lockfile, `py.typed`, full `__init__.py` exports
- **Domain models**: All 14 attrs frozen classes defined in `models.py` — `Source`, `RawRecord`, `Candidate`, `Engagement`, `ScoreBreakdown`, `DigestIssue`, `RunLog`, `FetchSuccess`, `FetchFailure`, `FetchResult`, `Paper`, `PaperPush`, `Period`, `RepoRecord`
- **Configuration**: TOML-based config with `Configuration.load()` using cattrs structuring; 125 sources defined in `config/config.toml`
- **Logging**: Structured logging via `config/logging.toml` with audit log + rotating error log + stderr
- **Fetcher protocol & registry**: `Fetcher` protocol in `fetchers/base.py`, `FETCHER_REGISTRY` dict + `get_fetcher()` dispatch + `fetch_kind()` resolution in `fetchers/__init__.py`
- **RSS/Atom/RDF fetcher**: `RSSFetcher` in `fetchers/rss.py` — stdlib `ElementTree` behind `defusedxml` (blocks entity bombs / XXE), lenient field resolution mirroring v1 `parse_rss`, XML entity cleanup, multi-format date parsing, `max_entries` cap
- **Async HTTP layer**: `http.py` — `fetch_text/json/bytes` over a shared `httpx.AsyncClient`, exponential backoff with jitter on timeouts/429/503, typed `FetchError` hierarchy, `DomainRateLimiter`
- **Source orchestration**: `fetch_all_sources()` in `orchestrate.py` — `asyncio.gather` with per-source semaphore (10), `asyncio.wait_for` timeout (15s), full fault isolation, `elapsed_ms` on every result, disabled sources skipped
- **Text/ID utilities**: `text.entry_id()` (deterministic SHA1-16 candidate IDs) and `dedup.norm_url()` (UTM/fragment/trailing-slash normalization), both applied in `raw_record_to_candidate()`
- **CLI**: `newsletter collect` with `--config/-c`, `--window-hours/-w`, `--date/-d`, `--dry-run`; `asyncio.run()` entry, SIGINT/SIGTERM → cancel → exit 130
- **CI pipeline**: GitHub Actions on dev/main — ruff format check, ruff lint, ty type check, pytest (coverage printed via `addopts`)
- **Tests**: **134 passing**, 96% branch coverage — RSS fetcher (53), main/CLI (26), http (20), orchestrate (16), dedup (9), text (8), configuration (2); `respx` for all HTTP, golden feed samples + hostile-XML samples in `conftest.py`, autouse log isolation so runs never dirty the committed `logs/`

### Known gaps (in dependency order)
1. **No scoring** — every candidate gets `ScoreBreakdown(score=0.0)`; `main.py` still carries `# TODO: scoring, dedup, selection, output writing`
2. **No keywords config** — `config/config.toml` has no keyword tables, so Goals 6.2–6.3 cannot start until 1.4 ports `config/keywords.json` → TOML
3. **No output artifact** — `collect` writes nothing; `YYYY-MM-DD-candidates.json` (Goal 8.4) is unwritten
4. **57/125 sources skipped** — only RSS-family fetchers are registered (`website` 52, `youtube` 2, `json` 2, `api` 1)
5. **Rate limiter not wired** — `DomainRateLimiter` exists and is tested but no pipeline code passes one to `fetch_*`; `request_delay_seconds` is not a config field
6. **No response cache** — Goal 3.1's file-based cache is unimplemented
7. **Config error contract** — `Configuration.load()` raises `FileNotFoundError`, while Goal 2.2 expects `ConfigurationError`
8. **No `clean_text`** — `Candidate.text` is still the raw feed description (HTML entities/tags intact)

### Immediate next steps
1. ~~Configure `pytest-cov` flags~~ ✅ · ~~import sorting~~ ✅ · ~~LLM deps~~ ✅ · ~~async HTTP + orchestration (3.1–3.2, 3.4)~~ ✅ · ~~`collect` CLI (1.6)~~ ✅ · ~~test log isolation~~ ✅
2. **Start Phase 3 / Goal 6 as one vertical slice**: keywords TOML (1.4) → `clean_text` + `language_looks_english` (6.1) → `match_terms` + core-terms gate (6.2) → `score_candidate` (6.3) → `canonical_event_key`/`event_tokens`/`is_same_event` (6.4) → `topic_key`/`is_medical_bio_ai`/`select_unique_events` (6.5) → write `data/YYYY-MM-DD-candidates.json` (8.4)
3. **Then the `website` fetcher** (4.2) — biggest coverage win, unlocks 52 sources, fully specified in PROJECT.md §3.3 (sitemap → HTML links → search placeholder)
4. Decide the config error contract (gap 7) and expand config error-handling tests (2.2)
5. Add pre-commit hooks or `uv run` task aliases for local dev (1.2)
6. Add `--cov-fail-under=80` to CI now that coverage sits at 96% (2.8)
