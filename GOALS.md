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
- [x] Port keywords config from `config/keywords.json` → TOML — **`config/keywords.toml` (term-for-term parity with v1, verified bucket by bucket) + `KeywordConfig.load()` in `keywords.py`**
- [ ] Port trend report config from `config/trend_report.yaml` → TOML
- [~] Add config schema validation (required fields, enum constraints) — **keyword buckets are schema-checked (`_validate_raw`: required buckets, table types, list-of-strings, unknown keys, `required_language` type); `Configuration` still relies on cattrs alone**
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
  - [x] `newsletter collect` — **full pipeline: concurrent async fetch → clean/gate/score → dedup → sectioned selection → `data/digests/YYYY-MM-DD-candidates.json` (v1-compatible schema); options `--config/-c`, `--keywords`, `--output-dir`, `--date/-d`, `--window-hours/-w`, `--dry-run`**
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
- [x] Create shared fixtures module (`tests/conftest.py`)
  - [x] Fixture: sample `Configuration` — **`app_config` (the real `config/config.toml`) + the `make_configuration` factory; `keyword_config` loads the real `config/keywords.toml`**
  - [x] Fixture: sample `Source` objects (each fetch type) — **`rss_source`, `atom_source`, `website_source`**
  - [x] Fixture: sample `RawRecord` / `Candidate` objects — **`sample_raw_record` plus the `make_candidate` factory (source/category/tags/engagement/breakdown overrides)**
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
- [x] Test keyword config loading and term matching — **`test_keywords.py` (48 tests): bucket loading, schema errors, `match_terms`, `matches`, `passes_gates`**

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
- [x] `test_scoring.py` — composite score formula, each sub-score, edge cases (null engagement, missing dates) — **54 tests, incl. the exact v1 weights (32/22/20/14/8/10) and log-scale caps (1200/800/5000)**
- [x] `test_keywords.py` — include/exclude term matching, case insensitivity, core terms gate — **48 tests**
- [x] `test_dedup.py` — URL normalization, canonical event keys, token similarity thresholds — **54 tests across 14 event rules**
- [x] `test_selection.py` — multi-pass selection, topic diversification, per-source caps, guo preference — **69 tests**
- [x] `test_category.py` — canonical category mapping, category inference, biomedical detection — **25 tests**
- [x] `test_text.py` — `clean_text`, `language_looks_english`, `english_summary` — **35 tests**

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
- [x] End-to-end collect (mocked HTTP → candidates JSON) — **`test_pipeline.py` (47 tests) covers the gate/score/dedup/select stages, `test_artifacts.py` (61 tests) the JSON schema + history lookback, and `TestCLI::test_collect_writes_candidates_artifact` the whole CLI path**
- [ ] `test_pipeline_report.py` — candidates JSON → final Markdown
- [ ] `test_pipeline_site.py` — candidates + reports → HTML output
- [ ] `test_quality_gate.py` — duplicate detection across issues, publishable item counts

### 2.8 Coverage & CI
- [x] Configure pytest-cov with `--cov=src/newsletter --cov-report=term-missing` — **in `[tool.pytest.ini_options].addopts` together with `--cov-branch`; currently 98%**
- [ ] Set minimum coverage threshold in CI (target: 80% line coverage) — **no `--cov-fail-under` yet**
- [ ] Add coverage badge or report in PR comments

### 2.9 Unit Tests — Async HTTP, Orchestration & CLI

> Landed with Goals 3.1–3.4; no section existed for them in the original plan.

- [x] `test_http.py` (20 tests) — backoff + jitter bounds, retryable vs non-retryable statuses, `MaxRetriesExceeded`, `fetch_text/json/bytes`, `DomainRateLimiter` pacing
- [x] `test_orchestrate.py` (16 tests) — concurrency cap, per-source timeout, fault isolation, disabled-source skipping, result ordering
- [x] `test_main.py` (38 tests) — deterministic candidate IDs + URL normalization, CLI options and exit codes (bad config, missing/invalid keywords, cancellation → 130), artifact writing and `--dry-run`, repo-`logs/` isolation regression
- [x] `test_text.py` (35 tests) / `test_dedup.py` (54 tests) — Goals 6.1 and 6.4 in full: `clean_text`, `language_looks_english`, `english_summary`, `effective_source`, `entry_id`; `norm_url`, event identity, `is_same_event`, `dedup_key`
- [x] Phase-3 modules (Goals 2.4, 6.1–6.5) — `test_keywords.py` (48), `test_scoring.py` (54), `test_selection.py` (69), `test_category.py` (25), `test_pipeline.py` (47), `test_artifacts.py` (61)

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
- [x] `collect` stage: async fetch → sync score/filter (CPU-bound scoring stays sync) — **`pipeline.collect()`: one async fetch pass, then a synchronous clean → gate → score → dedup → sort pass; `asyncio.to_thread()` is unnecessary at current volumes**
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
- [~] **Filtering**: Apply language-specific keyword filters (v1 `required_language` field becomes per-language config) — **`KeywordFilter.required_language` is loaded per bucket and enforced in `pipeline.candidate_from_record`; English is still the only configured language**
- [~] **Language detection**: Port `language_looks_english()` → `detect_language(text, lang_config)` for configurable detection — **`text.language_looks_english()` is ported and used as the pipeline's English gate; the configurable `detect_language` abstraction waits on Goal 5.1**
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
- [x] `clean_text(value: str | None) -> str` — HTML unescape, tag strip, whitespace normalize — **also strips `&#\d+;`/`&\w+;` residue and CDATA wrappers, mirroring v1**
- [x] `language_looks_english(text: str) -> bool` — ASCII ratio heuristic — **≥`MIN_LETTERS_FOR_LANGUAGE_CHECK` (20) letters and ≥`ENGLISH_ASCII_RATIO` (0.82) ASCII characters**
- [x] `english_summary(item: dict) -> str` — extractive 2-sentence summary
- [x] `effective_source(item: dict) -> str` — resolve Google News source suffix — **splits `Outlet - Publisher` down to the publisher**
- [x] `entry_id(url: str, title: str) -> str` — SHA1 16-char hex ID

### 6.2 Keyword Matching — `newsletter/keywords.py`
- [x] Port keyword filter logic from v1 — **`config/keywords.toml` + `KeywordConfig`/`KeywordFilter` attrs models, `load()` with schema validation (`KeywordError`)**
- [x] `match_terms(text: str, terms: list[str]) -> list[str]` — case-insensitive substring, order-preserving
- [x] Core terms gate (must match both `core_include` AND `ai_include` for engineering) — **`matches_core_terms()`; an empty gate always passes, exactly like v1**
- [x] General vs. engineering keyword buckets — **plus `exclude` lists, `matches()`, `passes_gates()` and per-bucket `required_language`**

### 6.3 Scoring — `newsletter/scoring.py`
- [x] `score_candidate(...) -> ScoreBreakdown` — **v1 weights verbatim: 32·priority + 22·novelty + 20·general + 14·engineering + 8·research + 10·workflow + engagement log-scales**
- [x] All sub-scores: source_priority, novelty, general_relevance, engineering_relevance, research_relevance — **priority presets from config, novelty from age/window, relevance from matched-term counts**
- [x] Engineering workflow AI boost (conditional +10) — **`has_engineering_workflow_ai()`: needs a `WORKFLOW_AI_TERMS` hit plus `WORKFLOW_CONTEXT_TERMS` context on an engineering-relevant candidate**
- [x] `recency_boost(published_at, now, window_hours) -> float` — **1.0 for fresh items, `NOVELTY_DECAY` (0.75) inside the window down to `MIN_NOVELTY` (0.15), `UNKNOWN_DATE_NOVELTY` (0.35) when undated — v1's `novelty_score`**
- [x] `log_scale(value, cap) -> float` — **`log(1+v)/log(1+cap)` clamped to [0, 1]; caps 1200 points / 800 comments / 5000 upvotes**
- [x] `score_reasons()` — human-readable explanation list carried on the candidate

### 6.4 Deduplication — `newsletter/dedup.py`
- [x] `norm_url(url: str) -> str` — UTM stripping, path normalization
- [x] `canonical_event_key(title: str) -> str | None` — hardcoded known events — **all 14 v1 `EventRule`s ported (`EVENT_RULES`) with their keyword/negation sets**
- [x] `event_tokens(title: str) -> set[str]` — tokenization with stopwords
- [x] `is_same_event(left, right) -> bool` — URL key + canonical key + token-overlap rules — **`event_url_key()` → `canonical_event_key()` → Jaccard-style overlap thresholds**
- [x] Cross-section deduplication — **`dedup_key()` (normalized URL, else lowercased title) drops a story seen in any bucket during the run and bumps `run_log.duplicate_count`; history lookback is per section, with engineering reading both `top_5_engineering_ai` and the legacy `top_5_cae_ai_engineering`**
- [x] Historical dedup against previous N days of published issues — **`artifacts.load_history()` + `main.load_section_history()`: general 7d, engineering/biomedical/research 30d (v1 parity)**

### 6.5 Selection — `newsletter/selection.py`
- [x] `select_unique_events(candidates, category, limit, history, ...) -> list[Candidate]` — multi-pass algorithm
  - [x] Pass 1: full constraints (topic cap, source cap, history dedup, trusted/guo preference)
  - [x] Pass 2: relax topic cap
  - [x] Pass 3: relax source cap
  - [x] Pass 4: relax all caps
  - [x] Fallback: relax guo preference — **re-runs selection without the Guo requirement and merges only genuinely new events**
- [x] Topic key assignment (`topic_key(candidate) -> str`) — **all 8 v1 topic buckets via `TOPIC_RULES`, plus the `FALLBACK_TOPIC` (`other`)**
- [x] Biomedical AI detection (`is_medical_bio_ai(candidate) -> bool`) — **`MEDICAL_PATTERNS` compiled regexes gated by `MEDICAL_ELIGIBLE_CATEGORIES`**
- [x] Engineering AI exclusion list — **`ENGINEERING_EXCLUDED_TERMS`, applied inside `select_unique_events`**
- [x] Category inference (`infer_candidate_category(...)`) — **in `category.py`: `canonical_category()` alias map + relevance-score-driven inference**
- [x] `select_medical_bio_ai(candidates, limit, history)` — biomedical-only selection used by `build_issue()`

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
- [x] Ensure output JSON schemas are backward-compatible with v1 consumers — **`artifacts.candidate_to_dict()` reproduces the v1 key order (`id` … `workflow_ai_boost`), the `_meta.explanation` block and the `run_log` shape; `test_artifacts.py` asserts the exact key sequence**
- [~] Maintain `YYYY-MM-DD-candidates.json`, `*-final.md`, `*-paper-push.json` formats — **candidates JSON is written under `data/digests/` (`--output-dir` overridable); `*-final.md` and `*-paper-push.json` wait on Goals 7.1–7.2**
- [ ] Maintain `data/repos.jsonl` append-only format
- [ ] Maintain `site/` directory structure for GitHub Pages

---

## Phasing

| Phase | Goals | Focus | Status |
|---|---|---|---|
| **Phase 1** | 1.1–1.3, 4.1–4.2 (RSS) | Foundation: models, config, first fetcher working end-to-end | **Complete** — models ✅, TOML config ✅, logging ✅, fetcher protocol + registry ✅, RSS/Atom/RDF fetcher ✅, `py.typed` ✅, coverage + import sorting ✅, CI green ✅ |
| **Phase 2** (Current) | 3.1–3.2, 4.2 (all fetchers) | Async migration + all fetcher implementations | **~60%** — `http.py` (retry/backoff, rate limiter, text/json/bytes) ✅, `orchestrate.py` (semaphore, per-source timeout, fault isolation) ✅, graceful shutdown ✅. Remaining: response caching, wiring a `DomainRateLimiter` into the pipeline, and every non-RSS fetcher — **57 of 125 configured sources are skipped today** (52 `website`, 2 `youtube`, 2 `json`, 1 `api`) |
| **Phase 3** | 6.1–6.5, 2.3–2.4 | Scoring/dedup/selection core + fetcher tests | **Complete** — `config/keywords.toml` (1.4), `keywords.py` (6.2), `text.py` (6.1), `scoring.py` (6.3), `dedup.py` event identity (6.4), `category.py` + `selection.py` (6.5), `pipeline.py` (collect + build_issue), `artifacts.py` v1-compatible JSON (8.4). 388 new tests, 98% branch coverage. Goal 2.3's per-fetcher tests still wait on the non-RSS fetchers |
| **Phase 4** (Current) | 1.6, 7.1–7.5, 2.5–2.7 | CLI, report generation, site rendering, integration tests | **~35%** — `newsletter collect` runs the whole pipeline and writes `data/digests/YYYY-MM-DD-candidates.json` (v1 schema); `test_pipeline.py` + `test_artifacts.py` + one CLI end-to-end test cover 2.7's collect path. Nothing renders yet: no `report`, `site`, `papers`, `summaries`, `check`, `trends` or `run-all` subcommands, and no `-briefing-input.md` |
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
- **Text/ID utilities**: `text.py` — `clean_text()` (HTML/entity/tag stripping + whitespace normalization), `language_looks_english()`, `english_summary()`, `effective_source()`, `entry_id()`; `dedup.norm_url()` (UTM/fragment/trailing-slash normalization)
- **Keyword configuration**: `config/keywords.toml` (125 sources' worth of buckets, ported 1:1 from v1's `keywords.json`) loaded by `keywords.KeywordConfig.load()` with schema validation; `match_terms()`, `matches()`, `passes_gates()`, `matches_core_terms()`
- **Scoring**: `scoring.score_candidate()` reproduces the v1 composite formula (32·priority + 22·novelty + 20·general + 14·engineering + 8·research + 10·workflow boost + 14/10/10 engagement log-scales), plus `recency_boost()`, `log_scale()`, `has_engineering_workflow_ai()` and `score_reasons()`
- **Event identity & dedup**: `dedup.canonical_event_key()` (14 ported `EventRule`s), `event_tokens()`, `event_url_key()`, `is_same_event()`, `dedup_key()`
- **Section selection**: `selection.select_unique_events()` (4 relaxation passes + Guo-preference fallback, topic/source caps, Google News caps, history dedup), `select_medical_bio_ai()`, `topic_key()`, `is_medical_bio_ai()`; `category.canonical_category()` / `infer_candidate_category()`
- **Pipeline**: `pipeline.candidate_from_record()` (v1's exact gate order: non-empty title/URL → English check → bucket include/exclude with engineering fallback → core_include → ai_include) and `pipeline.collect()` (score-sort + duplicate accounting + `RunLog`), `pipeline.build_issue()` (sectioned selection with per-section history)
- **Artifacts**: `artifacts.write_candidates_json()` emits `data/digests/YYYY-MM-DD-candidates.json` with v1's key order, `_meta.explanation` block, `selection_policy` text, the legacy `top_5_cae_ai_engineering` alias and `top_100_news_candidates`; `load_history()` reads previous issues (general 7d, engineering/biomedical/research 30d)
- **CLI**: `newsletter collect` with `--config/-c`, `--keywords`, `--output-dir`, `--window-hours/-w`, `--date/-d`, `--dry-run`; `asyncio.run()` entry, SIGINT/SIGTERM → cancel → exit 130
- **CI pipeline**: GitHub Actions on dev/main — ruff format check, ruff lint, ty type check, pytest (coverage printed via `addopts`)
- **Tests**: **522 passing**, 98% branch coverage — selection (69), artifacts (61), dedup (54), scoring (54), RSS fetcher (53), keywords (48), pipeline (47), main/CLI (38), text (35), category (25), http (20), orchestrate (16), configuration (2); `respx` for all HTTP, golden feed samples + hostile-XML samples in `conftest.py`, `app_config`/`keyword_config`/`make_configuration`/`make_candidate` fixtures, autouse log isolation so runs never dirty the committed `logs/`

### Known gaps (in dependency order)
1. **No source tags** — v1 tagged 30 sources `guo_yichen_reference` and 4 `trusted_discovery`; `config/config.toml` has no `tags`, so every General AI selection falls through passes 1–4 into the no-preference rerun (the Top 10 is plain score order) and trust gating is inert. Config-only fix, but it changes real output
2. **57/125 sources skipped** — only RSS-family fetchers are registered (`website` 52, `youtube` 2, `json` 2, `api` 1), so the candidate pool is much thinner than v1's
3. **No second artifact** — v1 also wrote `data/digests/YYYY-MM-DD-briefing-input.md` next to the JSON; v2 writes only the candidates JSON
4. **No renderers or quality gate** — Goals 7.1–7.5 (daily report, paper push, trends, site, `check`) are untouched, so the pipeline stops at candidates
5. **Rate limiter not wired** — `DomainRateLimiter` exists and is tested but no pipeline code passes one to `fetch_*`; `request_delay_seconds` is not a config field
6. **No response cache** — Goal 3.1's file-based cache is unimplemented
7. **Config error contract** — `Configuration.load()` raises `FileNotFoundError`, while Goal 2.2 expects `ConfigurationError`
8. **`supplemental_search_tasks` / `watchlist_updates` are always empty** — v1 filled them from the `website` fetcher's "manual search" placeholder records, so this unblocks with the `website` fetcher (4.2 Phase 3)

### Immediate next steps
1. ~~Configure `pytest-cov` flags~~ ✅ · ~~import sorting~~ ✅ · ~~LLM deps~~ ✅ · ~~async HTTP + orchestration (3.1–3.2, 3.4)~~ ✅ · ~~`collect` CLI (1.6)~~ ✅ · ~~test log isolation~~ ✅ · ~~Phase 3 vertical slice (1.4, 6.1–6.5, 2.4, 8.4)~~ ✅
2. **Tag the reference sources** (gap 1) — port v1's `guo_yichen_reference` / `trusted_discovery` tags into `config/config.toml`, then assert the Top 10 ordering changes as v1 intended
3. **Build the `website` fetcher** (4.2) — biggest coverage win, unlocks 52 sources, fully specified in PROJECT.md §3.3 (sitemap → HTML links → search placeholder)
4. **Start Goal 7.1** (`newsletter report`) — read `*-candidates.json` → `*-final.md`, which also delivers the missing `-briefing-input.md` and the first snapshot tests (2.1)
5. Decide the config error contract (gap 7) and expand config error-handling tests (2.2)
6. Add `--cov-fail-under=80` to CI now that coverage sits at 98% (2.8); add pre-commit hooks or `uv run` task aliases (1.2)
