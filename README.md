# AI Engineering Newsletter

This workspace contains an auditable AI Engineering Newsletter pipeline. It refreshes a static website with daily news, paper highlights, and GitHub trend monitoring. The public English site can run without an OpenAI API key; the Chinese reading edition is optional and only needs an LLM key when Chinese summaries/translations are regenerated.

## What It Produces

- Top 10 English-language General AI News items covering model releases, AI products, company dynamics, open-source models, policy, funding, and major research progress.
- Top 5 English-language Engineering AI News items from a rolling window, covering engineering, simulation, CAD, CAE, SPDM, PLM, digital twins, physical AI, scientific ML, and industrial AI.
- Top 5 English-language Medical, Medicine, and Bio/Genetics AI News items covering healthcare AI, clinical AI, biotech, genomics, genetics, and drug-discovery-related AI.
- A static website with a root language selector, an English public edition, an optional Chinese reading edition, Paper Push sections, and GitHub Trend Monitor pages.
- Optional Research Radar and Watchlist Updates sections.
- A candidate audit file with up to 100 scored news candidates from the enabled curated source registry.
- A run log with source failures and ranking reasons.

## Why It Is Not a Black Box

The daily newsletter is based on explicit configuration:

- Source registry: `config/sources.yaml`
- Legacy source config fallback: `config/sources.json`
- Topic filters: `config/keywords.json`
- Candidate builder: `scripts/build_digest_candidates.py`
- Daily artifacts: `data/digests/`

Each candidate records source, link, matched terms, visible engagement signals, total score, score reasons, and sub-scores:

- `general_ai_score`
- `engineering_relevance_score`
- `research_relevance_score`
- `novelty_score`
- `source_priority_score`

Direct read counts are often not public, so the ranking estimates reach using visible evidence such as source priority, engagement, recency, topic relevance, and cross-source evidence. The source registry is intentionally extensible; the daily candidate pool, not the source count, is capped at 100.

Selection is not a raw popularity leaderboard. After duplicate-event removal, the Top 10 General AI list and Top 5 Engineering AI list apply topic diversification so one hot area, such as AI payments, regulation, data centers, or model-release drama, does not crowd out the whole newsletter. The default cap is two items per broad topic before the selector relaxes the cap to fill empty slots.

For General AI, the selector now treats Google News RSS as a recall/fallback layer rather than the main source of truth. Official labs, major technology publications, mainstream technology desks, and computer-science / engineering-oriented sources are selected first; Google News can fill at most a small number of Top 10 slots. This avoids a daily list dominated by unfamiliar repost sites while still catching important stories that the curated feeds miss.

The same source-first rule applies to the right column:

- Engineering AI is anchored on curated engineering and industrial sources first: Siemens Digital Industries Software, Siemens Simcenter, Siemens Art of the Possible, Ansys, COMSOL, Rescale, NAFEMS, and the configured watchlist of Dassault Systemes, Autodesk, Altair, Hexagon/MSC, PTC, Cadence, Synopsys, SimScale, Synera, PhysicsX, Luminary Cloud, Neural Concept, Monolith AI, nTop, and related CAE / simulation vendors. Broad Google News Engineering AI discovery is low-priority fallback; source-specific trusted vendor discovery is separate and capped.
- Engineering media and industrial-AI discovery also includes user-requested sources such as Engineering.com, Engineering24, Rescale, AI for Industry / Industrial AI Network, and source-specific Google News recall limited to trusted engineering domains. Engineering24 is kept as a manual watchlist entry until a stable public URL or RSS feed is confirmed.
- Biomedical AI is anchored on trusted biomedical and clinical sources first, including source-specific discovery for NEJM, Nature, The Lancet, Science, Cell, STAT, and Fierce Biotech, plus direct RSS where available. Broad Google News Medical/Bio discovery is low-priority fallback and capped.

## Upstream References

The source strategy is intentionally closer to curated open-source digest projects than to open-ended news search.

- [`guo-yichen/news-summary`](https://github.com/guo-yichen/news-summary): strong reference for a `sources.yaml`-first design, per-source entry limits, daily GitHub Actions automation, cross-day deduplication, and high-signal AI sources such as Anthropic, OpenAI, Google DeepMind, Google Research, GitHub AI, Hugging Face, Simon Willison, Latent Space, The Pragmatic Engineer, Ahead of AI, Lilian Weng, and other expert feeds.
- [`Olshansk/rss-feeds`](https://github.com/Olshansk/rss-feeds): used indirectly for community-maintained RSS feeds where official AI company pages do not expose stable RSS, such as Anthropic, OpenAI Research, Cursor, and Windsurf.
- [`banana2556/rssdigest`](https://github.com/banana2556/rssdigest): reference for the simpler RSS/Atom-first daily digest pattern where LLM summarization is optional rather than required.

Adopted from these references:

- Curated RSS/source registry is the primary input.
- Each source can set `max_entries` so one feed cannot dominate the issue.
- Google News is treated as fallback recall, not the main ranking source.
- Cross-day deduplication prevents repeated issues from showing the same event.

Not adopted for the current no-API public version:

- Twitter/X timeline scraping, logged-in feeds, YouTube transcript APIs, email ingestion, Notion, and LLM summarization. Those need credentials, paid APIs, or a wider privacy/security surface.

## Source Registry

`config/sources.yaml` is the curated source registry. It is the default source configuration, but it is not a closed list. Add, disable, edit, or reprioritize sources there without changing code.

Each source contains at least:

```yaml
name: OpenAI
url: https://openai.com/news/rss.xml
source_type: rss
category: vendor
priority: high
tags: [frontier_model, product, api]
notes: Official OpenAI news.
enabled: true
```

Supported `source_type` values include `rss`, `website`, `github`, `arxiv`, `linkedin_manual`, `x_api`, `newsletter`, and `manual`. Sources with a stable RSS/API can also set `fetch_type`; sources without stable public access are kept as watchlist/manual review entries. The project does not scrape logged-in feeds or fragile pages.

## Run Manually

Create a local virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

For the no-API public site, this is enough:

```bash
python3 scripts/build_digest_candidates.py --window-hours 24
python3 -m trend_report all
python3 scripts/render_digest_site.py
```

This mode uses public RSS/web feeds, public arXiv-style links already stored in paper push JSON files, and GitHub public APIs. `GITHUB_TOKEN` is optional locally and only raises GitHub API rate limits. In GitHub Actions, `${{ secrets.GITHUB_TOKEN }}` is provided by GitHub automatically and is not a user-created API key.

Only create your private environment file if you want to regenerate Chinese LLM summaries/translations:

```bash
cp .env.example .env
```

Then edit `.env` and replace `OPENAI_API_KEY=sk-your-key-here` with your real key. Keep `.env` private; it is ignored by git. This is not required for the no-API public English site.

Recommended first-run budget settings:

```text
OPENAI_MODEL=gpt-4.1-mini
OPENAI_CLASSIFIER_MODEL=gpt-5-nano
OPENAI_DAILY_MAX_TOKENS=120000
OPENAI_MONTHLY_BUDGET_USD=5
```

Build the candidate audit:

```bash
python3 scripts/build_digest_candidates.py --window-hours 24
```

Outputs:

```text
data/digests/YYYY-MM-DD-candidates.json
data/digests/YYYY-MM-DD-briefing-input.md
```

The briefing input uses this structure:

```text
# AI Engineering Newsletter - YYYY-MM-DD

## Top 10 General AI News

## Top 5 Engineering AI News

## Research Radar

## Watchlist Updates

## Why It Matters
```

## Combined Website

The static site has three entry points:

```text
site/index.html      # language selector
site/en/index.html   # English edition
site/zh/index.html   # Chinese edition
```

Regenerate it manually after new newsletter files are created:

```bash
python3 scripts/render_digest_site.py
```

The newest newsletter appears at the top in both language editions. Each dated issue can include:

- Daily News Push from `data/digests/YYYY-MM-DD-candidates.json`
- Friday-only Paper Push from `data/digests/YYYY-MM-DD-paper-push.json`
- GitHub Trend Monitor links rendered from `reports/weekly/` and `reports/monthly/`

The Chinese page uses the human-written Chinese final markdown when available. The English page uses selected items with English titles, source links, source snippets, scores, and audit metadata, so it can be built without OpenAI.

## Mobile Web Publishing

The `site/` directory is a static website and can be published with GitHub Pages. This repository includes a GitHub Actions workflow that deploys `site/` whenever the `main` branch is pushed.

After the first push, enable Pages in GitHub if needed:

```text
Repository Settings -> Pages -> Source: GitHub Actions
```

The no-API GitHub Actions workflow at `.github/workflows/daily-no-api-site.yml` refreshes daily public news candidates and rebuilds the site every morning. The GitHub trend workflow at `.github/workflows/github-trend-report.yml` refreshes weekly/monthly trend reports. Push the updated files to GitHub to refresh the phone-accessible pages:

```text
https://tiktaalika.github.io/ai-engineering-newsletter/     # language selector
https://tiktaalika.github.io/ai-engineering-newsletter/en/  # English edition
https://tiktaalika.github.io/ai-engineering-newsletter/zh/  # Chinese edition
```

## LinkedIn Handling

LinkedIn is useful for CAE and AI-for-engineering practice notes, but its logged-in feed is not a stable public API. This project treats LinkedIn as a public search source and records it transparently. If a source cannot be fetched, the failure appears in the run log instead of being silently ignored.

Google News RSS queries are used as automatic supplemental recall for broad AI and Engineering AI topics. LinkedIn public searches are kept as supplemental search tasks so placeholder search URLs are not mistaken for ranked news items.

For a stronger LinkedIn implementation, add one of these later:

- A compliant LinkedIn API integration if you have access.
- A manually curated list of public LinkedIn author/company URLs.
- A browser-assisted review step for logged-in reading, with explicit human approval.

## Daily Newsletter Format

For each selected item, the automation should output:

1. One-sentence Chinese headline-style summary.
2. Five-sentence Chinese summary.
3. Original English link.
4. Chinese translation of the key original content.

## GitHub Trend Monitor

This repository also includes a small automated GitHub trend monitoring system for six domains:

- AI Agent
- MCP
- RAG
- LLM Infrastructure
- Simulation
- Engineering AI

It combines GitHub Search/API results with respectful cached reads of public trend pages where available. Raw source snapshots are stored in `data/snapshots/`, normalized records are appended to `data/repos.jsonl`, and Markdown reports are written to `reports/weekly/` and `reports/monthly/`.

The scoring formula is transparent and configurable in `config/trend_report.yaml`:

```text
trend_score =
  0.55 * normalized_star_growth
+ 0.25 * normalized_total_stars
+ 0.10 * normalized_recent_activity
+ 0.10 * normalized_fork_growth
```

Set `GITHUB_TOKEN` for higher GitHub API rate limits. If live data is unavailable, the tool logs the error and generates clearly marked dummy records so the report pipeline can still be inspected.

Run it manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

python -m trend_report collect
python -m trend_report weekly
python -m trend_report monthly
python -m trend_report all
```

macOS/Linux cron examples:

```cron
# Weekly report, Monday 07:00 local time.
0 7 * * 1 cd "/Users/fyang/news push" && . .venv/bin/activate && python -m trend_report all >> data/logs/trend_report.cron.log 2>&1

# Monthly report, first day of month 07:30 local time.
30 7 1 * * cd "/Users/fyang/news push" && . .venv/bin/activate && python -m trend_report collect && python -m trend_report monthly >> data/logs/trend_report.cron.log 2>&1
```

A GitHub Actions workflow is provided at `.github/workflows/github-trend-report.yml`. It runs weekly on Monday morning UTC, runs monthly on the 1st day of the month, and can also be started manually.
