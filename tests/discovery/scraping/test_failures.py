# SPDX-License-Identifier: MIT
from datetime import datetime, timedelta, timezone

from llm_registry.discovery.scraping import failures


def test_failure_ledger_records_eligibility_and_clears_success(tmp_path, monkeypatch):
    monkeypatch.setattr(failures, "CACHE_PATH", tmp_path / "failed_enrichments.json")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    failures.record_failure(
        provider_id="provider",
        model_id="model",
        detail_url="https://example.test/model",
        category=failures.CATEGORY_SCRAPE_TRANSIENT,
        detail="timeout",
        now=now,
    )

    assert failures.eligible_failures(now=now) == []
    eligible = failures.eligible_failures(now=now + timedelta(minutes=6))
    assert len(eligible) == 1
    assert eligible[0]["provider_id"] == "provider"
    assert eligible[0]["attempts"] == 1

    failures.clear_failure("provider", "model", "https://example.test/model")
    assert failures.load_failures() == {}


def test_permanent_failures_are_skipped_unless_forced(tmp_path, monkeypatch):
    monkeypatch.setattr(failures, "CACHE_PATH", tmp_path / "failed_enrichments.json")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    failures.record_failure(
        provider_id="provider",
        model_id="missing",
        detail_url=None,
        category=failures.CATEGORY_NO_SITEMAP_PAGE,
        detail="no page",
        now=now,
    )

    assert failures.eligible_failures(now=now + timedelta(days=1)) == []
    assert len(failures.eligible_failures(force=True, now=now)) == 1


def test_clear_failure_without_url_clears_all_model_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(failures, "CACHE_PATH", tmp_path / "failed_enrichments.json")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    for detail_url in (None, "https://example.test/model"):
        failures.record_failure(
            provider_id="provider",
            model_id="model",
            detail_url=detail_url,
            category=failures.CATEGORY_PARSE_EMPTY,
            detail="empty",
            now=now,
        )

    assert len(failures.load_failures()) == 2
    failures.clear_failure("provider", "model")
    assert failures.load_failures() == {}
