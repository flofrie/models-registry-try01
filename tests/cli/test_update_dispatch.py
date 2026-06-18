# SPDX-License-Identifier: MIT
"""Integration test for the per-entry dispatch in cli.py::_update.

The full _update() function pulls config, reads existing MODELS.json, calls
real APIs, and writes output — too heavy for a focused test. This module
exercises the specific dispatch line that the audit flagged: when an
entry already exists in `all_models` and the fresh API entry is
stripped (e.g., missing pricing/context_window because the API doesn't
expose them), the dispatch must call merge_model_entries() and
preserve the existing enrichment rather than overwriting with None.
"""
import asyncio
from types import SimpleNamespace

import llm_registry.cli as cli
from llm_registry.merge import merge_model_entries
from llm_registry.schema.model_entry import (
    Capabilities,
    ModelEntry,
    Pricing,
    Source,
)


class FakeConsole:
    def __init__(self):
        self.lines = []

    def print(self, *args, **kwargs):
        self.lines.append(" ".join(str(arg) for arg in args))


def test_cli_dispatch_preserves_existing_enrichment_when_api_entry_is_stripped():
    """Reproduces the dispatch in cli.py:147-151.

    Existing entry (post-enrichment): pricing, context_window, max_output_tokens,
    capabilities all populated.
    New API entry (per the bare /v1/models response): pricing=None, context_window=None,
    max_output_tokens=None, capabilities=None.

    Expected: the existing data survives the merge.
    """
    enriched = ModelEntry(
        model_id="claude-sonnet",
        provider="cometapi",
        api_type="anthropic",
        context_window=200_000,
        max_output_tokens=64_000,
        pricing=Pricing(input_per_1m=2.0, output_per_1m=10.0, cache_read_per_1m=0.5),
        capabilities=Capabilities(text=True, streaming=True),
        source=Source(url="https://cometapi.com/models/anthropic/claude-sonnet/", method="scrape"),
    )
    stripped_api = ModelEntry(
        model_id="claude-sonnet",
        provider="cometapi",
        api_type="anthropic",
    )

    all_models = {"cometapi_claude-sonnet": enriched}
    new_entry = stripped_api
    key = "cometapi_claude-sonnet"

    # === exact dispatch from cli.py:147-151 ===
    existing = all_models.get(key)
    all_models[key] = merge_model_entries(existing, new_entry) if existing else new_entry

    merged = all_models[key]
    assert merged.context_window == 200_000
    assert merged.max_output_tokens == 64_000
    assert merged.pricing.input_per_1m == 2.0
    assert merged.pricing.output_per_1m == 10.0
    assert merged.pricing.cache_read_per_1m == 0.5
    assert merged.capabilities.text is True
    assert merged.capabilities.streaming is True
    assert merged.source.method == "scrape"  # existing source preserved


def test_cli_dispatch_overwrites_non_null_api_fields():
    """Fresh API data with non-null fields must still win."""
    existing = ModelEntry(
        model_id="model",
        provider="provider",
        api_type="openai",
        pricing=Pricing(input_per_1m=1.0),
    )
    new = ModelEntry(
        model_id="model",
        provider="provider",
        api_type="anthropic",
        pricing=Pricing(input_per_1m=0.5, output_per_1m=2.0),
    )

    all_models = {"provider_model": existing}
    key = "provider_model"
    existing_d = all_models.get(key)
    all_models[key] = merge_model_entries(existing_d, new) if existing_d else new

    merged = all_models[key]
    assert merged.api_type == "anthropic"  # new wins
    assert merged.pricing.input_per_1m == 0.5  # new wins
    assert merged.pricing.output_per_1m == 2.0  # new field


def test_cli_dispatch_creates_entry_when_no_existing():
    """If the model wasn't in the previous MODELS.json, the dispatch
    inserts the fresh API entry unchanged (no merge to perform)."""
    new = ModelEntry(
        model_id="new-model",
        provider="provider",
        api_type="openai",
        context_window=128_000,
    )
    all_models: dict[str, ModelEntry] = {}
    key = "provider_new-model"

    existing = all_models.get(key)
    all_models[key] = merge_model_entries(existing, new) if existing else new

    assert all_models[key].model_id == "new-model"
    assert all_models[key].context_window == 128_000


def test_cli_dispatch_does_not_mutate_existing_entry():
    """The merge must not mutate the existing entry — it returns a new
    ModelEntry via model_copy(deep=True). This is the contract that
    keeps `all_models.get(key)` correct on the next provider iteration."""
    existing = ModelEntry(
        model_id="model",
        provider="provider",
        context_window=100_000,
        pricing=Pricing(input_per_1m=1.0),
    )
    original_ctx = existing.context_window
    original_pricing = existing.pricing.input_per_1m
    new = ModelEntry(model_id="model", provider="provider")  # all None except identifiers

    all_models = {"provider_model": existing}
    key = "provider_model"
    existing_d = all_models.get(key)
    all_models[key] = merge_model_entries(existing_d, new) if existing_d else new

    # Existing entry must be untouched
    assert existing.context_window == original_ctx
    assert existing.pricing.input_per_1m == original_pricing
    # Merged entry has the preserved values
    assert all_models[key].context_window == 100_000
    assert all_models[key].pricing.input_per_1m == 1.0


def test_cli_dispatch_skips_template_provider_without_enrichment_strategy(monkeypatch):
    """A provider with model_url_template but enrichment_strategy=None
    should skip enrichment rather than trying to call a parser."""
    provider = SimpleNamespace(
        id="future",
        name="Future Provider",
        website=SimpleNamespace(
            scraping_strategy="firecrawl",
            has_model_detail_url_strategy=lambda: True,
            model_detail_url=lambda mid: f"https://future.test/{mid}",
            enrichment_strategy=None,
        ),
        endpoints=[
            SimpleNamespace(
                type="openai",
                models_endpoint="/models",
                base_url="https://future.test/v1",
                auth=SimpleNamespace(required=True, env_var="FUTURE_API_KEY"),
            ),
        ],
    )

    async def discover_one_model(**kwargs):
        from llm_registry.schema.model_entry import ModelEntry
        return [ModelEntry(model_id="future-model", provider="future")]

    scrape_calls = []

    async def record_scrape(*args, **kwargs):
        scrape_calls.append((args, kwargs))
        return ""

    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: SimpleNamespace(
            providers=[provider],
            settings=SimpleNamespace(firecrawl_timeout_seconds=None),
        ),
    )
    monkeypatch.setattr(cli, "read_models_json", lambda: {})
    monkeypatch.setattr(cli, "discover_from_api", discover_one_model)
    monkeypatch.setattr(cli, "scrape_with_firecrawl", record_scrape)
    monkeypatch.setattr(cli, "write_models_json", lambda models: None)
    monkeypatch.setattr(cli, "generate_markdown", lambda models: None)

    asyncio.run(cli._update(("future",), dry_run=False, force=False, enrich=True))
    assert scrape_calls == [], f"Expected no scrape calls, got {len(scrape_calls)}"


def test_update_does_not_soft_delete_when_discovery_fails(monkeypatch):
    existing = {
        "provider_missing": ModelEntry(
            model_id="missing",
            provider="provider",
            available=True,
        )
    }
    written = {}
    provider = SimpleNamespace(
        id="provider",
        name="Provider",
        website=SimpleNamespace(scraping_strategy="none"),
        endpoints=[
            SimpleNamespace(
                type="openai",
                models_endpoint="/models",
                base_url="https://example.test/v1",
                auth=SimpleNamespace(required=False, env_var="PROVIDER_API_KEY"),
            )
        ],
    )

    async def fail_discovery(**kwargs):
        raise RuntimeError("api down")

    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: SimpleNamespace(
            providers=[provider],
            settings=SimpleNamespace(firecrawl_timeout_seconds=None),
        ),
    )
    monkeypatch.setattr(cli, "read_models_json", lambda: existing)
    monkeypatch.setattr(cli, "discover_from_api", fail_discovery)
    monkeypatch.setattr(cli, "write_models_json", lambda models: written.update(models))
    monkeypatch.setattr(cli, "generate_markdown", lambda models: None)

    asyncio.run(cli._update(("provider",), dry_run=False, force=False, enrich=False))

    assert written["provider_missing"].available is True


def test_update_passes_firecrawl_timeout_to_template_enrichment(monkeypatch):
    provider = SimpleNamespace(
        id="provider",
        name="Provider",
        website=SimpleNamespace(
            scraping_strategy="firecrawl",
            has_model_detail_url_strategy=lambda: True,
            model_detail_url=lambda mid: f"https://provider.test/models/{mid}",
            enrichment_strategy="test",
        ),
        endpoints=[
            SimpleNamespace(
                type="openai",
                models_endpoint="/models",
                base_url="https://provider.test/v1",
                auth=SimpleNamespace(required=False, env_var="PROVIDER_API_KEY"),
            )
        ],
    )

    async def discover_one_model(**kwargs):
        return [ModelEntry(model_id="model", provider="provider")]

    scrape_calls = []

    async def record_scrape(*args, **kwargs):
        scrape_calls.append((args, kwargs))
        return "# model"

    monkeypatch.setitem(cli.ENRICHMENT_PARSERS, "test", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: SimpleNamespace(
            providers=[provider],
            settings=SimpleNamespace(firecrawl_timeout_seconds=90),
        ),
    )
    monkeypatch.setattr(cli, "read_models_json", lambda: {})
    monkeypatch.setattr(cli, "discover_from_api", discover_one_model)
    monkeypatch.setattr(cli, "scrape_with_firecrawl", record_scrape)
    monkeypatch.setattr(cli, "write_models_json", lambda models: None)
    monkeypatch.setattr(cli, "generate_markdown", lambda models: None)

    asyncio.run(cli._update(("provider",), dry_run=False, force=False, enrich=True))

    assert scrape_calls == [
        (
            ("https://provider.test/models/model",),
            {"firecrawl_timeout_seconds": 90},
        )
    ]


def test_template_enrichment_prints_per_model_outcomes(monkeypatch):
    fake_console = FakeConsole()
    provider = SimpleNamespace(
        id="provider",
        name="Provider",
        website=SimpleNamespace(
            scraping_strategy="firecrawl",
            has_model_detail_url_strategy=lambda: True,
            model_detail_url=lambda mid: f"https://provider.test/models/{mid}",
            enrichment_strategy="test",
        ),
        endpoints=[
            SimpleNamespace(
                type="openai",
                models_endpoint="/models",
                base_url="https://provider.test/v1",
                auth=SimpleNamespace(required=False, env_var="PROVIDER_API_KEY"),
            )
        ],
    )

    async def discover_models(**kwargs):
        return [
            ModelEntry(model_id="enriched", provider="provider"),
            ModelEntry(model_id="no-data", provider="provider"),
            ModelEntry(model_id="failed", provider="provider"),
        ]

    async def scrape(url, **kwargs):
        if url.endswith("/failed"):
            raise RuntimeError("timeout")
        return "# model"

    def parse(markdown, provider_id, *, target_model_id, source_url):
        if target_model_id == "enriched":
            return [
                ModelEntry(
                    model_id=target_model_id,
                    provider=provider_id,
                    pricing=Pricing(input_per_1m=1.0),
                )
            ]
        return []

    monkeypatch.setattr(cli, "console", fake_console)
    monkeypatch.setitem(cli.ENRICHMENT_PARSERS, "test", parse)
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: SimpleNamespace(
            providers=[provider],
            settings=SimpleNamespace(firecrawl_timeout_seconds=None),
        ),
    )
    monkeypatch.setattr(cli, "read_models_json", lambda: {})
    monkeypatch.setattr(cli, "discover_from_api", discover_models)
    monkeypatch.setattr(cli, "scrape_with_firecrawl", scrape)
    monkeypatch.setattr(cli, "write_models_json", lambda models: None)
    monkeypatch.setattr(cli, "generate_markdown", lambda models: None)

    asyncio.run(cli._update(("provider",), dry_run=False, force=False, enrich=True))

    output = "\n".join(fake_console.lines)
    assert "    → enriched: discovered, scraping" in output
    assert "    → enriched: scraped, enriched" in output
    assert "    → no-data: discovered, scraping" in output
    assert "    → no-data: scraped, no extractable data" in output
    assert "    → failed: discovered, scraping" in output
    assert "    → failed: failed: timeout" in output


def test_enrich_cometapi_passes_firecrawl_timeout_through_cache(monkeypatch):
    from llm_registry.discovery.scraping import cache as cache_mod

    provider = SimpleNamespace(id="cometapi")
    entries = [ModelEntry(model_id="claude", provider="cometapi")]
    scrape_calls = []

    async def fetch_sitemap():
        return ["unused"]

    async def fake_cached_scrape(url, scrape_fn):
        return await scrape_fn(url)

    async def record_scrape(*args, **kwargs):
        scrape_calls.append((args, kwargs))
        return "# model"

    monkeypatch.setattr(cli, "fetch_sitemap_urls", fetch_sitemap)
    monkeypatch.setattr(cli, "build_slug_to_url_map", lambda sitemap_entries: {"unused": "unused"})
    monkeypatch.setattr(cli, "find_url_for_model", lambda model_id, slug_map: ("anthropic", "claude"))
    monkeypatch.setattr(cache_mod, "get_cached_markdown", lambda url: None)
    monkeypatch.setattr(cache_mod, "scrape_with_firecrawl_cached", fake_cached_scrape)
    monkeypatch.setattr(cli, "scrape_with_firecrawl", record_scrape)
    monkeypatch.setattr(cli, "parse_cometapi_detail_page", lambda markdown, model_id, provider_id: [])

    asyncio.run(
        cli._enrich_cometapi(
            provider,
            entries,
            SimpleNamespace(print=lambda *args, **kwargs: None),
            firecrawl_timeout_seconds=90,
        )
    )

    assert scrape_calls == [
        (
            ("https://www.cometapi.com/models/anthropic/claude/",),
            {"firecrawl_timeout_seconds": 90},
        )
    ]


def test_enrich_cometapi_prints_per_model_outcomes_and_summary(monkeypatch):
    from llm_registry.discovery.scraping import cache as cache_mod

    fake_console = FakeConsole()
    provider = SimpleNamespace(id="cometapi")
    entries = [
        ModelEntry(model_id="cached-enriched", provider="cometapi"),
        ModelEntry(model_id="fresh-enriched", provider="cometapi"),
        ModelEntry(model_id="fresh-no-data", provider="cometapi"),
        ModelEntry(model_id="no-sitemap", provider="cometapi"),
        ModelEntry(model_id="page-404", provider="cometapi"),
        ModelEntry(model_id="failed", provider="cometapi"),
    ]

    sitemap_map = {
        model.model_id: ("provider", model.model_id)
        for model in entries
        if model.model_id != "no-sitemap"
    }

    async def fetch_sitemap():
        return list(sitemap_map.values())

    async def fake_cached_scrape(url, scrape_fn):
        if "cached-enriched" in url:
            return "# cached"
        if "failed" in url:
            raise RuntimeError("timeout")
        return await scrape_fn(url)

    async def scrape(url, **kwargs):
        return "# fresh"

    def parse(markdown, model_id, provider_id):
        if model_id in {"cached-enriched", "fresh-enriched"}:
            return ModelEntry(
                model_id=model_id,
                provider=provider_id,
                pricing=Pricing(input_per_1m=1.0),
            )
        if model_id == "page-404":
            return None
        return ModelEntry(model_id=model_id, provider=provider_id)

    monkeypatch.setattr(cli, "fetch_sitemap_urls", fetch_sitemap)
    monkeypatch.setattr(cli, "build_slug_to_url_map", lambda sitemap_entries: sitemap_map)
    monkeypatch.setattr(cli, "find_url_for_model", lambda model_id, slug_map: slug_map.get(model_id))
    monkeypatch.setattr(
        cache_mod,
        "get_cached_markdown",
        lambda url: "# cached" if "cached-enriched" in url else None,
    )
    monkeypatch.setattr(cache_mod, "scrape_with_firecrawl_cached", fake_cached_scrape)
    monkeypatch.setattr(cli, "scrape_with_firecrawl", scrape)
    monkeypatch.setattr(cli, "parse_cometapi_detail_page", parse)

    asyncio.run(
        cli._enrich_cometapi(
            provider,
            entries,
            fake_console,
            firecrawl_timeout_seconds=None,
        )
    )

    output = "\n".join(fake_console.lines)
    assert "    → cached-enriched: cached, enriched" in output
    assert "    → cached-enriched: discovered, scraping" not in output
    assert "    → fresh-enriched: discovered, scraping" in output
    assert "    → fresh-enriched: scraped, enriched" in output
    assert "    → fresh-no-data: discovered, scraping" in output
    assert "    → fresh-no-data: scraped, no extractable data" in output
    assert "    → no-sitemap: no sitemap page" in output
    assert "    → page-404: discovered, scraping" in output
    assert "    → page-404: sitemap URL was 404" in output
    assert "    → failed: discovered, scraping" in output
    assert "    → failed: failed: timeout" in output
    assert (
        "  → Enriched 2 models (1 from cache, 3 fresh, 1 sitemap URLs were 404, "
        "1 failed, 1 had no sitemap page)"
    ) in output
