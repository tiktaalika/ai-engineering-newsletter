"""AI Engineering Newsletter v2 — public API."""

from .configuration import Configuration, ConfigurationError
from .dedup import norm_url
from .fetchers import (
    FETCHER_REGISTRY,
    Fetcher,
    RSSFetcher,
    UnknownFetcherError,
    get_fetcher,
)
from .models import (
    Candidate,
    Category,
    DigestIssue,
    Engagement,
    FetchFailure,
    FetchResult,
    FetchSuccess,
    FetchType,
    Paper,
    PaperPush,
    Period,
    Priority,
    RawRecord,
    RepoRecord,
    RunLog,
    ScoreBreakdown,
    Source,
    SourceType,
)
from .orchestrate import fetch_all_sources
from .text import entry_id

__all__ = [
    "FETCHER_REGISTRY",
    "Candidate",
    "Category",
    "Configuration",
    "ConfigurationError",
    "DigestIssue",
    "Engagement",
    "FetchFailure",
    "FetchResult",
    "FetchSuccess",
    "FetchType",
    "Fetcher",
    "Paper",
    "PaperPush",
    "Period",
    "Priority",
    "RSSFetcher",
    "RawRecord",
    "RepoRecord",
    "RunLog",
    "ScoreBreakdown",
    "Source",
    "SourceType",
    "UnknownFetcherError",
    "entry_id",
    "fetch_all_sources",
    "get_fetcher",
    "norm_url",
]
