# AI Engineering Newsletter v2

## Requirements

- Python **≥ 3.14**
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync                      # install dependencies
```

Then edit the configuration in `config/` (shipped with the repo, no template step):

- **`config.toml`** — newsletter sources (RSS feeds etc.), scoring weights, lookback window
- **`keywords.toml`** — include/exclude keyword gates for `general_ai` and `engineering_ai` topics
- **`logging.toml`** — logging setup

## Usage

```bash
# 1. Fetch, filter, score, deduplicate and select candidates
uv run newsletter collect [OPTIONS]

# 2. Render the daily Markdown report from the collected candidates
uv run newsletter report [OPTIONS]
```

### `newsletter collect`

| Option | Description |
|---|---|
| `-c, --config PATH` | Path to `config.toml` (default: repo `config/`) |
| `--keywords PATH` | Path to `keywords.toml` (default: next to `--config`) |
| `-o, --output-dir PATH` | Output directory (default: `data/digests/`) |
| `-d, --date YYYY-MM-DD` | Digest date (default: today) |
| `-w, --window-hours N` | Lookback window in hours (default: 24) |
| `--dry-run` | Run the pipeline without writing artifacts |

Writes `data/digests/YYYY-MM-DD-candidates.json`.

### `newsletter report`

| Option | Description |
|---|---|
| `-d, --date YYYY-MM-DD` | Digest date to render (default: today) |
| `-o, --output-dir PATH` | Directory containing the candidates JSON (default: `data/digests/`) |

Reads `YYYY-MM-DD-candidates.json` and writes `YYYY-MM-DD-final.md`.
Exits with code 1 if the candidates artifact is missing or the date is invalid.

## Output

- `data/digests/YYYY-MM-DD-candidates.json` — all sections (Top 10 General AI,
  Top 5 Engineering AI, Top 5 Biomedical AI, Research Radar, top-100 pool) plus a
  run log and per-source failures
- `data/digests/YYYY-MM-DD-final.md` — the human-readable daily report
- `logs/` — audit and error logs

## Development

```bash
uv run pytest              # test suite (with coverage)
uv run ruff format .       # format
uv run ruff check .        # lint
uv run ty check            # type check
```

## Project docs

- [PROJECT.md](PROJECT.md) — the v1 specification
- [GOALS.md](GOALS.md) — v2 roadmap, goals and current status
- [STACK.md](STACK.md) — technology choices
- [STYLE.md](STYLE.md) — code style rules
