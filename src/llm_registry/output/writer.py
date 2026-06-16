"""Output writer for JSON and Markdown."""
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import orjson

from llm_registry.schema.model_entry import ModelEntry


def get_timestamp() -> str:
    """Get current ISO timestamp."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def write_models_json(
    models: dict[str, ModelEntry],
    output_path: Optional[Path] = None,
    backup_count: int = 5,
) -> None:
    """Write models to JSON file with atomic write and backup rotation."""
    if output_path is None:
        output_path = Path.cwd() / "MODELS.json"

    # Add timestamps
    timestamp = get_timestamp()
    for key, entry in models.items():
        if entry.last_updated is None:
            entry.last_updated = timestamp
        if entry.source and entry.source.scraped_at is None:
            entry.source.scraped_at = timestamp

    # Serialize to dict
    data = {key: entry.model_dump() for key, entry in models.items()}

    # Write to temp file first
    temp_path = output_path.with_suffix(".json.tmp")
    with open(temp_path, "wb") as f:
        f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))

    # Rotate backups
    if output_path.exists():
        backup_dir = output_path.parent / ".backups"
        backup_dir.mkdir(exist_ok=True)

        # Copy current output to a unique backup so rotation can retain
        # multiple historical versions instead of overwriting one file.
        backup_timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_dir / f"{output_path.stem}.backup.{backup_timestamp}.json"
        shutil.copy2(output_path, backup_path)

        # Keep only N backups
        backups = sorted(backup_dir.glob(f"{output_path.stem}.backup*.json"), reverse=True)
        for old in backups[backup_count:]:
            old.unlink()

    # Atomic replace
    os.replace(temp_path, output_path)


def read_models_json(input_path: Optional[Path] = None) -> dict[str, ModelEntry]:
    """Read models from JSON file."""
    if input_path is None:
        input_path = Path.cwd() / "MODELS.json"

    if not input_path.exists():
        return {}

    with open(input_path, "rb") as f:
        data = orjson.loads(f.read())

    return {key: ModelEntry(**val) for key, val in data.items()}


def generate_markdown(models: dict[str, ModelEntry], output_path: Optional[Path] = None) -> None:
    """Generate human-readable Markdown from models."""
    if output_path is None:
        output_path = Path.cwd() / "MODELS.md"

    # Group by provider
    by_provider: dict[str, list[ModelEntry]] = {}
    for entry in models.values():
        if entry.provider not in by_provider:
            by_provider[entry.provider] = []
        by_provider[entry.provider].append(entry)

    lines = [
        "# MODELS.md — LLM Models Registry",
        "",
        f"*Last updated: {get_timestamp()}*",
        "",
    ]

    for provider, entries in sorted(by_provider.items()):
        lines.append(f"## {provider.capitalize()} ({len(entries)} models)")
        lines.append("")
        lines.append(
            "| Model ID | API Type | Context | Max Output | Input $/1M | Output $/1M | "
            "Cache Read | Cache Write |"
        )
        lines.append(
            "|----------|----------|---------|------------|------------|-------------|"
            "------------|-------------|"
        )

        for entry in sorted(entries, key=lambda e: e.model_id):
            ctx = _format_context(entry.context_window)
            max_out = _format_context(entry.max_output_tokens)
            inp = _format_price(entry.pricing.input_per_1m if entry.pricing else None)
            out = _format_price(entry.pricing.output_per_1m if entry.pricing else None)
            cache_read = _format_price(
                entry.pricing.cache_read_per_1m if entry.pricing else None
            )
            cache_write = _format_price(
                entry.pricing.cache_write_per_1m if entry.pricing else None
            )

            lines.append(
                f"| {entry.model_id} | {entry.api_type or '-'} | {ctx} | {max_out} | "
                f"{inp} | {out} | {cache_read} | {cache_write} |"
            )

        lines.append("")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))


def _format_context(ctx: Optional[int]) -> str:
    """Format context window."""
    if ctx is None:
        return "-"
    if ctx >= 1_000_000:
        return f"{ctx // 1_000_000}M"
    return f"{ctx // 1000}K"


def _format_price(price: Optional[float]) -> str:
    """Format price."""
    if price is None:
        return "-"
    return f"${price:.2f}"
