# SPDX-License-Identifier: MIT
"""CLI entry point for LLM Models Registry."""
import asyncio

import click
from dotenv import load_dotenv
from rich.console import Console

from llm_registry.config.loader import load_config
from llm_registry.discovery.api import discover_from_api, discover_from_requesty
from llm_registry.discovery.scraping import scrape_with_firecrawl
from llm_registry.discovery.scraping.failures import (
    CATEGORY_NO_SITEMAP_PAGE,
    CATEGORY_PARSE_EMPTY,
    CATEGORY_PARSE_ERROR,
    CATEGORY_SITEMAP_URL_404,
    TRY_HARDER_CATEGORIES,
    classify_exception,
    clear_failure,
    eligible_failures,
    record_failure,
)
from llm_registry.merge import mark_missing_provider_models_unavailable, merge_model_entries
from llm_registry.normalise.dispatch import ENRICHMENT_PARSERS
from llm_registry.normalise.cometapi import (
    build_slug_to_url_map,
    fetch_sitemap_urls,
    find_url_for_model,
    parse_cometapi_detail_page,
)
from llm_registry.output import generate_markdown, get_timestamp, read_models_json, write_models_json
from llm_registry.schema.model_entry import ModelEntry

console = Console()

# Load .env file
load_dotenv()


@click.group()
@click.version_option(version="0.1.0")
def main():
    """LLM Models Registry - maintain model databases across providers."""
    pass


@main.command()
def providers():
    """List configured providers."""
    config = load_config()
    console.print(f"[bold]Configured providers:[/bold] {len(config.providers)}")
    for p in config.providers:
        console.print(f"  - {p.id}: {p.name}")


@main.command()
@click.option("--provider", "providers", multiple=True, help="Specific provider(s) to update")
@click.option("--dry-run", is_flag=True, help="Discover without writing output")
@click.option("--force", is_flag=True, help="Force full re-scrape, ignore scrape cache")
@click.option("--enrich", is_flag=True, help="Scrape individual model pages for pricing details")
def update(providers, dry_run, force, enrich):
    """Update models from providers."""
    asyncio.run(_update(providers, dry_run, force, enrich))


async def _update(provider_ids: tuple, dry_run: bool, force: bool, enrich: bool):
    """Async implementation of update command."""
    config = load_config()
    firecrawl_timeout_seconds = config.settings.firecrawl_timeout_seconds

    # Filter to specific providers if requested
    target_providers = [
        p for p in config.providers
        if not provider_ids or p.id in provider_ids
    ]

    if not target_providers:
        console.print("[red]No matching providers found[/red]")
        return

    console.print(f"[bold]Updating {len(target_providers)} provider(s)[/bold]")

    all_models: dict[str, ModelEntry] = {}

    # Load existing models for merge
    if not force:
        existing = read_models_json()
        all_models = existing

    for prov in target_providers:
        console.print(f"\n[cyan]Discovering from {prov.name}...[/cyan]")

        # Step 1: Try API first - this gives us the complete model list.
        # We pick the endpoint with `models_endpoint` set as the discovery
        # endpoint (typically the openai one). The other endpoints are
        # recorded for downstream SDK wiring but don't drive discovery.
        discovery_endpoint = next((e for e in prov.endpoints if e.models_endpoint), None)
        available_types = {e.type for e in prov.endpoints}

        api_entries: list[ModelEntry] = []
        discovery_succeeded = False
        if discovery_endpoint:
            try:
                console.print(
                    f"  → Calling API: {discovery_endpoint.base_url}{discovery_endpoint.models_endpoint}"
                )
                auth_kwargs = {"auth_required": discovery_endpoint.auth.required}
                if prov.id == "requesty":
                    api_entries = await discover_from_requesty(
                        base_url=discovery_endpoint.base_url,
                        endpoint=discovery_endpoint.models_endpoint,
                        env_var=discovery_endpoint.auth.env_var,
                        provider_id=prov.id,
                        available_endpoint_types=available_types,
                        **auth_kwargs,
                    )
                else:
                    api_entries = await discover_from_api(
                        base_url=discovery_endpoint.base_url,
                        endpoint=discovery_endpoint.models_endpoint,
                        env_var=discovery_endpoint.auth.env_var,
                        provider_id=prov.id,
                        available_endpoint_types=available_types,
                        **auth_kwargs,
                    )
                console.print(f"  → API returned {len(api_entries)} models")
                discovery_succeeded = True
            except Exception as e:
                console.print(f"  → API failed: {e}")

        # Step 2: If enrich flag, scrape individual model pages for pricing
        if enrich and prov.website.scraping_strategy != "none" and api_entries:
            console.print("  → Scraping model detail pages for pricing...")

            if prov.id == "cometapi":
                await _enrich_cometapi(
                    prov,
                    api_entries,
                    console,
                    firecrawl_timeout_seconds=firecrawl_timeout_seconds,
                    record_failures=not dry_run,
                )
            elif not prov.website.has_model_detail_url_strategy():
                console.print("  → Skipping detail-page enrichment: no model URL template")
            else:
                parser_fn = ENRICHMENT_PARSERS.get(prov.website.enrichment_strategy)
                if parser_fn is None:
                    label = prov.website.enrichment_strategy or "none"
                    console.print(f"  → Skipping detail-page enrichment: no parser for strategy '{label}'")
                else:
                    # Template-backed providers: scrape individual pages.
                    models_needing_pricing = [e for e in api_entries if not e.pricing]
                    for entry in models_needing_pricing:
                        model_url = prov.website.model_detail_url(entry.model_id)
                        console.print(f"    → {entry.model_id}: discovered, scraping")
                        phase = "scrape"
                        try:
                            markdown = await scrape_with_firecrawl(
                                model_url,
                                firecrawl_timeout_seconds=firecrawl_timeout_seconds,
                            )

                            phase = "parse"
                            details = parser_fn(
                                markdown,
                                prov.id,
                                target_model_id=entry.model_id,
                                source_url=model_url,
                            )
                            scraped = details[0] if details else None
                            if _apply_scraped_enrichment(entry, scraped):
                                if not dry_run:
                                    clear_failure(prov.id, entry.model_id)
                                console.print(f"    → {entry.model_id}: scraped, enriched")
                            else:
                                if not dry_run:
                                    record_failure(
                                        provider_id=prov.id,
                                        model_id=entry.model_id,
                                        detail_url=model_url,
                                        category=CATEGORY_PARSE_EMPTY,
                                        detail="Scraped page had no extractable enrichment fields",
                                    )
                                console.print(f"    → {entry.model_id}: scraped, no extractable data")
                        except Exception as e:
                            if not dry_run:
                                record_failure(
                                        provider_id=prov.id,
                                        model_id=entry.model_id,
                                        detail_url=model_url,
                                        category=CATEGORY_PARSE_ERROR if phase == "parse" else classify_exception(e),
                                        detail=f"{type(e).__name__}: {e}",
                                    )
                            console.print(f"    → {entry.model_id}: failed: {e}")

        # Merge fresh API entries into all_models, preserving existing enrichment.
        for entry in api_entries:
            key = f"{prov.id}_{entry.model_id}"
            existing = all_models.get(key)
            all_models[key] = merge_model_entries(existing, entry) if existing else entry

        if discovery_succeeded:
            unavailable = mark_missing_provider_models_unavailable(
                all_models,
                prov.id,
                api_entries,
                get_timestamp(),
            )
            if unavailable:
                console.print(f"  → Marked {unavailable} missing models unavailable")

    console.print(f"\n[bold]Total models: {len(all_models)}[/bold]")

    if dry_run:
        console.print("[yellow]Dry run - not writing output[/yellow]")
    else:
        console.print("→ Writing MODELS.json...")
        write_models_json(all_models)

        console.print("→ Generating MODELS.md...")
        generate_markdown(all_models)

        console.print("[green]Done![/green]")


@main.command(name="retry-failed")
@click.option("--provider", "providers", multiple=True, help="Specific provider(s) to retry")
@click.option("--try-harder", is_flag=True, help='Use 2x Firecrawl timeout and proxy="auto" for retryable failures')
@click.option("--dry-run", is_flag=True, help="Show eligible failures without writing MODELS.json or the failure ledger")
@click.option("--force", is_flag=True, help="Ignore retry cooldowns/exhaustion for retry-failed (unlike update --force)")
def retry_failed(providers, try_harder, dry_run, force):
    """Retry unresolved failed enrichment records."""
    asyncio.run(_retry_failed(providers, try_harder=try_harder, dry_run=dry_run, force=force))


async def _retry_failed(
    provider_ids: tuple,
    *,
    try_harder: bool,
    dry_run: bool,
    force: bool,
) -> None:
    config = load_config()
    provider_by_id = {provider.id: provider for provider in config.providers}
    selected = set(provider_ids)
    failures = [
        failure
        for failure in eligible_failures(force=force)
        if not selected or failure["provider_id"] in selected
    ]

    if not failures:
        console.print("[green]No eligible failed enrichments to retry[/green]")
        return

    base_timeout = config.settings.firecrawl_timeout_seconds or 30
    firecrawl_timeout_seconds = base_timeout * 2 if try_harder else config.settings.firecrawl_timeout_seconds
    proxy = "auto" if try_harder else None
    models = read_models_json()
    retried = 0
    succeeded = 0
    still_failed = 0
    skipped = 0

    console.print(f"[bold]Retrying {len(failures)} failed enrichment(s)[/bold]")
    for failure in failures:
        provider_id = failure["provider_id"]
        model_id = failure["model_id"]
        detail_url = failure.get("detail_url")
        category = failure["last_failure_category"]
        if not detail_url:
            skipped += 1
            console.print(f"  → {provider_id}/{model_id}: skipped, no detail URL")
            continue
        if try_harder and category not in TRY_HARDER_CATEGORIES and not force:
            skipped += 1
            console.print(f"  → {provider_id}/{model_id}: skipped, try-harder not useful for {category}")
            continue

        provider = provider_by_id.get(provider_id)
        parser_fn = _enrichment_parser_for_retry(provider)
        if provider is None or parser_fn is None:
            skipped += 1
            console.print(f"  → {provider_id}/{model_id}: skipped, no enrichment parser")
            continue

        retried += 1
        console.print(f"  → {provider_id}/{model_id}: retrying")
        phase = "scrape"
        try:
            markdown = await scrape_with_firecrawl(
                detail_url,
                firecrawl_timeout_seconds=firecrawl_timeout_seconds,
                proxy=proxy,
            )
            phase = "parse"
            scraped = parser_fn(markdown, model_id, provider_id, detail_url)
            if scraped is None:
                still_failed += 1
                if not dry_run:
                    record_failure(
                        provider_id=provider_id,
                        model_id=model_id,
                        detail_url=detail_url,
                        category=CATEGORY_SITEMAP_URL_404,
                        detail="Retry returned a not-found page",
                        try_harder=try_harder,
                    )
                console.print(f"  → {provider_id}/{model_id}: sitemap URL was 404")
                continue

            key = f"{provider_id}_{model_id}"
            entry = models.get(key) or ModelEntry(model_id=model_id, provider=provider_id)
            if _apply_scraped_enrichment(entry, scraped):
                succeeded += 1
                models[key] = entry
                if not dry_run:
                    clear_failure(provider_id, model_id)
                console.print(f"  → {provider_id}/{model_id}: enriched")
            else:
                still_failed += 1
                if not dry_run:
                    record_failure(
                        provider_id=provider_id,
                        model_id=model_id,
                        detail_url=detail_url,
                        category=CATEGORY_PARSE_EMPTY,
                        detail="Retry scraped page had no extractable enrichment fields",
                        try_harder=try_harder,
                    )
                console.print(f"  → {provider_id}/{model_id}: no extractable data")
        except Exception as e:
            still_failed += 1
            if not dry_run:
                record_failure(
                    provider_id=provider_id,
                    model_id=model_id,
                    detail_url=detail_url,
                    category=CATEGORY_PARSE_ERROR if phase == "parse" else classify_exception(e),
                    detail=f"{type(e).__name__}: {e}",
                    try_harder=try_harder,
                )
            console.print(f"  → {provider_id}/{model_id}: failed: {e}")

    if dry_run:
        console.print("[yellow]Dry run - not writing output or failure ledger[/yellow]")
    elif succeeded:
        console.print("→ Writing MODELS.json...")
        write_models_json(models)
        console.print("→ Generating MODELS.md...")
        generate_markdown(models)

    console.print(
        f"[bold]Retry summary:[/bold] {retried} retried, {succeeded} succeeded, "
        f"{still_failed} still failing, {skipped} skipped"
    )


async def _enrich_cometapi(
    prov,
    api_entries: list[ModelEntry],
    console,
    *,
    firecrawl_timeout_seconds: int | None = None,
    record_failures: bool = True,
) -> None:
    """Enrich CometAPI models by scraping individual detail pages via sitemap URLs.

    Uses a per-URL scrape cache (.cache/firecrawl_scrape_cache.json) so
    successive --enrich runs don't re-burn Firecrawl credits on URLs that
    succeeded recently. Transient errors (429, 5xx) are retried with
    exponential backoff within a single run.
    """
    from llm_registry.discovery.scraping.cache import scrape_with_firecrawl_cached

    console.print("  → Fetching CometAPI sitemap...")
    try:
        sitemap_entries = await fetch_sitemap_urls()
        slug_map = build_slug_to_url_map(sitemap_entries)
        console.print(f"  → Sitemap has {len(slug_map)} model pages")
    except Exception as e:
        console.print(f"  → Sitemap fetch failed: {e}")
        return

    enriched = 0
    cached_hits = 0
    fresh_scrapes = 0
    not_found = 0  # model_id not in sitemap
    page_missing = 0  # URL in sitemap but page is 404
    failed = 0  # transient error / non-retryable

    for entry in api_entries:
        url_info = find_url_for_model(entry.model_id, slug_map)
        if not url_info:
            not_found += 1
            if record_failures:
                record_failure(
                    provider_id=prov.id,
                    model_id=entry.model_id,
                    detail_url=None,
                    category=CATEGORY_NO_SITEMAP_PAGE,
                    detail="No matching CometAPI sitemap page",
                )
            console.print(f"    → {entry.model_id}: no sitemap page")
            continue

        provider_slug, model_slug = url_info
        url = f"https://www.cometapi.com/models/{provider_slug}/{model_slug}/"
        phase = "scrape"
        try:
            from llm_registry.discovery.scraping.cache import get_cached_markdown

            async def scrape(url: str) -> str:
                return await scrape_with_firecrawl(
                    url,
                    firecrawl_timeout_seconds=firecrawl_timeout_seconds,
                )

            was_cached = get_cached_markdown(url) is not None
            if not was_cached:
                console.print(f"    → {entry.model_id}: discovered, scraping")
            markdown = await scrape_with_firecrawl_cached(url, scrape)
            if was_cached:
                cached_hits += 1
                source_label = "cached"
            else:
                fresh_scrapes += 1
                source_label = "scraped"
            phase = "parse"
            scraped = parse_cometapi_detail_page(markdown, entry.model_id, prov.id)
            if scraped is None:
                # 404 page — sitemap has the URL but the page is gone
                page_missing += 1
                if record_failures:
                    record_failure(
                        provider_id=prov.id,
                        model_id=entry.model_id,
                        detail_url=url,
                        category=CATEGORY_SITEMAP_URL_404,
                        detail="Sitemap URL returned a not-found page",
                    )
                console.print(f"    → {entry.model_id}: sitemap URL was 404")
                continue
            if _apply_scraped_enrichment(entry, scraped):
                if record_failures:
                    clear_failure(prov.id, entry.model_id)
                enriched += 1
                console.print(f"    → {entry.model_id}: {source_label}, enriched")
            else:
                if record_failures:
                    record_failure(
                        provider_id=prov.id,
                        model_id=entry.model_id,
                        detail_url=url,
                        category=CATEGORY_PARSE_EMPTY,
                        detail="Scraped page had no extractable enrichment fields",
                    )
                console.print(f"    → {entry.model_id}: {source_label}, no extractable data")
        except Exception as e:
            failed += 1
            if record_failures:
                record_failure(
                    provider_id=prov.id,
                    model_id=entry.model_id,
                    detail_url=url,
                    category=CATEGORY_PARSE_ERROR if phase == "parse" else classify_exception(e),
                    detail=f"{type(e).__name__}: {e}",
                )
            console.print(f"    → {entry.model_id}: failed: {e}")

    console.print(
        f"  → Enriched {enriched} models "
        f"({cached_hits} from cache, {fresh_scrapes} fresh, {page_missing} sitemap URLs were 404, "
        f"{failed} failed, {not_found} had no sitemap page)"
    )


def _apply_scraped_enrichment(entry: ModelEntry, scraped: ModelEntry | None) -> bool:
    """Merge scraped detail fields into an API entry and report whether any were found."""
    if scraped is None:
        return False

    enriched = False
    if scraped.pricing:
        entry.pricing = scraped.pricing
        enriched = True
    if scraped.context_window is not None:
        entry.context_window = scraped.context_window
        enriched = True
    if scraped.max_output_tokens is not None:
        entry.max_output_tokens = scraped.max_output_tokens
        enriched = True
    if scraped.display_name:
        entry.display_name = scraped.display_name
        enriched = True
    if scraped.capabilities:
        entry.capabilities = scraped.capabilities
        enriched = True
    return enriched


def _enrichment_parser_for_retry(provider):
    if provider is None:
        return None
    if provider.id == "cometapi":
        return lambda markdown, model_id, provider_id, detail_url: parse_cometapi_detail_page(
            markdown,
            model_id,
            provider_id,
        )

    parser_fn = ENRICHMENT_PARSERS.get(provider.website.enrichment_strategy)
    if parser_fn is None:
        return None

    def parse(markdown, model_id, provider_id, detail_url):
        details = parser_fn(
            markdown,
            provider_id,
            target_model_id=model_id,
            source_url=detail_url,
        )
        return details[0] if details else ModelEntry(model_id=model_id, provider=provider_id)

    return parse


@main.command()
def validate():
    """Validate MODELS.json against schema."""
    try:
        models = read_models_json()
        console.print(f"[green]Valid: {len(models)} models[/green]")
    except Exception as e:
        console.print(f"[red]Validation failed: {e}[/red]")


@main.command()
def generate_md():
    """Generate MODELS.md from MODELS.json."""
    models = read_models_json()
    generate_markdown(models)
    console.print(f"[green]Generated MODELS.md with {len(models)} models[/green]")


@main.command()
@click.option("--provider", help="Show diff for specific provider")
def diff(provider):
    """Show changes between current and new MODELS.json."""
    console.print(f"[yellow]diff command[/yellow] - provider: {provider}")
    console.print("[dim]Not yet implemented[/dim]")


@main.command(name="cache-clear")
def cache_clear():
    """Clear LLM extraction cache."""
    console.print("[yellow]cache clear command[/yellow]")
    console.print("[dim]Not yet implemented[/dim]")


if __name__ == "__main__":
    main()
