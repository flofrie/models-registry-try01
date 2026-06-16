"""CLI entry point for LLM Models Registry."""
import asyncio

import click
from dotenv import load_dotenv
from rich.console import Console

from llm_registry.config.loader import load_config
from llm_registry.discovery.api import discover_from_api, discover_from_requesty
from llm_registry.discovery.scraping import scrape_with_firecrawl
from llm_registry.merge import merge_model_entries
from llm_registry.normalise import normalize_wisgate_markdown
from llm_registry.normalise.cometapi import (
    build_slug_to_url_map,
    fetch_sitemap_urls,
    find_url_for_model,
    parse_cometapi_detail_page,
)
from llm_registry.output import generate_markdown, read_models_json, write_models_json
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
@click.option("--force", is_flag=True, help="Force full re-scrape, ignore cache")
@click.option("--enrich", is_flag=True, help="Scrape individual model pages for pricing details")
def update(providers, dry_run, force, enrich):
    """Update models from providers."""
    asyncio.run(_update(providers, dry_run, force, enrich))


async def _update(provider_ids: tuple, dry_run: bool, force: bool, enrich: bool):
    """Async implementation of update command."""
    config = load_config()

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
            except Exception as e:
                console.print(f"  → API failed: {e}")

        # Step 2: If enrich flag, scrape individual model pages for pricing
        if enrich and prov.website.scraping_strategy != "none" and api_entries:
            console.print("  → Scraping model detail pages for pricing...")

            if prov.id == "cometapi":
                await _enrich_cometapi(prov, api_entries, console)
            else:
                # Wisgate and others: scrape individual pages
                models_needing_pricing = [e for e in api_entries if not e.pricing]
                for entry in models_needing_pricing:
                    try:
                        model_url = f"{prov.website.models_page}/{entry.model_id}"
                        console.print(f"    → {entry.model_id}")
                        markdown = await scrape_with_firecrawl(model_url)

                        details = normalize_wisgate_markdown(markdown, prov.id, target_model_id=entry.model_id)
                        if details:
                            scraped = details[0]
                            if scraped.pricing:
                                entry.pricing = scraped.pricing
                            if scraped.context_window:
                                entry.context_window = scraped.context_window
                            if scraped.max_output_tokens:
                                entry.max_output_tokens = scraped.max_output_tokens
                            if scraped.display_name:
                                entry.display_name = scraped.display_name
                            if scraped.capabilities:
                                entry.capabilities = scraped.capabilities
                    except Exception as e:
                        console.print(f"    → Failed: {e}")

        # Merge into all_models - use api_type from endpoint_types for cometapi
        for entry in api_entries:
            key = f"{prov.id}_{entry.model_id}"
            existing = all_models.get(key)
            all_models[key] = merge_model_entries(existing, entry) if existing else entry

    console.print(f"\n[bold]Total models: {len(all_models)}[/bold]")

    if dry_run:
        console.print("[yellow]Dry run - not writing output[/yellow]")
    else:
        console.print("→ Writing MODELS.json...")
        write_models_json(all_models)

        console.print("→ Generating MODELS.md...")
        generate_markdown(all_models)

        console.print("[green]Done![/green]")


async def _enrich_cometapi(prov, api_entries: list[ModelEntry], console) -> None:
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
            continue

        provider_slug, model_slug = url_info
        url = f"https://www.cometapi.com/models/{provider_slug}/{model_slug}/"
        try:
            from llm_registry.discovery.scraping.cache import get_cached_markdown
            was_cached = get_cached_markdown(url) is not None
            markdown = await scrape_with_firecrawl_cached(url, scrape_with_firecrawl)
            if was_cached:
                cached_hits += 1
            else:
                fresh_scrapes += 1
            scraped = parse_cometapi_detail_page(markdown, entry.model_id, prov.id)
            if scraped is None:
                # 404 page — sitemap has the URL but the page is gone
                page_missing += 1
                continue
            if scraped:
                if scraped.pricing:
                    entry.pricing = scraped.pricing
                if scraped.context_window:
                    entry.context_window = scraped.context_window
                if scraped.max_output_tokens:
                    entry.max_output_tokens = scraped.max_output_tokens
                if scraped.display_name:
                    entry.display_name = scraped.display_name
                if scraped.capabilities:
                    entry.capabilities = scraped.capabilities
                enriched += 1
        except Exception as e:
            failed += 1
            console.print(f"    → Failed {entry.model_id}: {e}")

    console.print(
        f"  → Enriched {enriched} models "
        f"({cached_hits} from cache, {fresh_scrapes} fresh, {page_missing} sitemap URLs were 404, "
        f"{failed} failed, {not_found} had no sitemap page)"
    )


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
