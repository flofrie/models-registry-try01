# SPDX-License-Identifier: MIT
"""Persistent failed-enrichment ledger."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

CACHE_PATH = Path.cwd() / ".cache" / "failed_enrichments.json"

CATEGORY_NO_SITEMAP_PAGE = "no_sitemap_page"
CATEGORY_SITEMAP_URL_404 = "sitemap_url_404"
CATEGORY_SCRAPE_TRANSIENT = "scrape_transient"
CATEGORY_SCRAPE_PERMANENT = "scrape_permanent"
CATEGORY_PARSE_EMPTY = "parse_empty"
CATEGORY_PARSE_ERROR = "parse_error"
CATEGORY_UNKNOWN = "unknown"

TRANSIENT_CATEGORIES = {CATEGORY_SCRAPE_TRANSIENT}
PARSE_CATEGORIES = {CATEGORY_PARSE_EMPTY, CATEGORY_PARSE_ERROR, CATEGORY_UNKNOWN}
PERMANENT_CATEGORIES = {
    CATEGORY_NO_SITEMAP_PAGE,
    CATEGORY_SITEMAP_URL_404,
    CATEGORY_SCRAPE_PERMANENT,
}
TRY_HARDER_CATEGORIES = {
    CATEGORY_SCRAPE_TRANSIENT,
    CATEGORY_PARSE_EMPTY,
    CATEGORY_PARSE_ERROR,
    CATEGORY_UNKNOWN,
}

TRANSIENT_COOLDOWN = timedelta(minutes=5)
PARSE_COOLDOWN = timedelta(hours=1)
FAR_FUTURE = datetime(9999, 12, 31, tzinfo=timezone.utc)
MAX_ATTEMPTS = 5
RETRYABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
PERMANENT_HTTP_STATUS_CODES = {401, 403, 404}


def record_failure(
    *,
    provider_id: str,
    model_id: str,
    detail_url: Optional[str],
    category: str,
    detail: str,
    try_harder: bool = False,
    now: Optional[datetime] = None,
) -> dict:
    """Record or update an unresolved enrichment failure."""
    now = now or _now()
    ledger = load_failures()
    key = failure_key(provider_id, model_id, detail_url)
    existing = ledger.get(key, {})
    attempts = int(existing.get("attempts", 0)) + 1
    try_harder_attempts = int(existing.get("try_harder_attempts", 0))
    if try_harder:
        try_harder_attempts += 1

    entry = {
        "provider_id": provider_id,
        "model_id": model_id,
        "detail_url": detail_url,
        "last_attempt_at": _iso(now),
        "last_failure_category": category,
        "last_failure_detail": detail[:500],
        "attempts": attempts,
        "try_harder_attempts": try_harder_attempts,
        "next_eligible_at": _iso(_next_eligible_at(category, now)),
        "exhausted": attempts >= MAX_ATTEMPTS,
    }
    ledger[key] = entry
    save_failures(ledger)
    return entry


def clear_failure(provider_id: str, model_id: str, detail_url: Optional[str] = None) -> None:
    """Clear unresolved failures for a successfully enriched model."""
    ledger = load_failures()
    if detail_url is not None:
        ledger.pop(failure_key(provider_id, model_id, detail_url), None)
    else:
        prefix = f"{provider_id}::{model_id}::"
        for key in list(ledger):
            if key.startswith(prefix):
                ledger.pop(key, None)
    save_failures(ledger)


def eligible_failures(
    *,
    provider_id: Optional[str] = None,
    force: bool = False,
    now: Optional[datetime] = None,
) -> list[dict]:
    """Return unresolved failures eligible for retry."""
    now = now or _now()
    failures = []
    for entry in load_failures().values():
        if provider_id and entry.get("provider_id") != provider_id:
            continue
        if not force:
            if entry.get("exhausted"):
                continue
            if entry.get("last_failure_category") in PERMANENT_CATEGORIES:
                continue
            if _parse_iso(entry["next_eligible_at"]) > now:
                continue
        failures.append(entry)
    return failures


def load_failures() -> dict[str, dict]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_failures(ledger: dict[str, dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ledger, indent=2, sort_keys=True))
    tmp.replace(CACHE_PATH)


def failure_key(provider_id: str, model_id: str, detail_url: Optional[str]) -> str:
    return f"{provider_id}::{model_id}::{detail_url or ''}"


def classify_exception(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in RETRYABLE_HTTP_STATUS_CODES:
            return CATEGORY_SCRAPE_TRANSIENT
        if status in PERMANENT_HTTP_STATUS_CODES:
            return CATEGORY_SCRAPE_PERMANENT
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return CATEGORY_SCRAPE_TRANSIENT
    return CATEGORY_UNKNOWN


def _next_eligible_at(category: str, now: datetime) -> datetime:
    if category in TRANSIENT_CATEGORIES:
        return now + TRANSIENT_COOLDOWN
    if category in PARSE_CATEGORIES:
        return now + PARSE_COOLDOWN
    return FAR_FUTURE


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)
