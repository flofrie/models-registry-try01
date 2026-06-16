"""Normalizer for mapping raw data to ModelEntry."""
import re
from typing import Optional

from llm_registry.schema.model_entry import (
    Capabilities,
    ModelEntry,
    Pricing,
)


def parse_price(price_str: str) -> Optional[float]:
    """Parse price string like '$5.00 per 1M tokens' to float."""
    if not price_str:
        return None

    # Extract numeric value
    match = re.search(r"[\d.]+", price_str.replace(",", ""))
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass
    return None


def parse_context(context_str: str) -> Optional[int]:
    """Parse context string like '1M' or '32k' to integer."""
    if not context_str:
        return None

    context_str = context_str.strip().upper()

    # Handle 1M, 200K, etc.
    if "M" in context_str:
        match = re.search(r"([\d.]+)\s*M", context_str)
        if match:
            return int(float(match.group(1)) * 1_000_000)
    elif "K" in context_str:
        match = re.search(r"([\d.]+)\s*K", context_str)
        if match:
            return int(float(match.group(1)) * 1_000)

    return None


def normalize_wisgate_markdown(
    markdown: str,
    provider_id: str,
    target_model_id: str = None,
    source_url: str = "https://wisgate.ai/models",
) -> list[ModelEntry]:
    """Parse Firecrawl markdown from Wisgate into ModelEntry list.

    If target_model_id is provided, returns only that model's entry.
    """
    entries = []

    # If we have a target model_id, try to extract just that model's info
    if target_model_id:
        entry = _parse_model_details(
            markdown,
            provider_id,
            target_model_id,
            target_model_id.replace("-", " ").title(),
            source_url,
        )
        if entry:
            return [entry]
        return []

    # Otherwise parse all models from listing page (legacy behavior)
    # Split by model sections (### Model Name)
    sections = re.split(r"^###\s+", markdown, flags=re.MULTILINE)

    for section in sections:
        if not section.strip():
            continue

        lines = section.strip().split("\n")
        if not lines:
            continue

        # First line is model name - strip leading # and whitespace
        display_name = lines[0].strip().lstrip("#").strip()

        # Skip if display_name is empty or looks like a header fragment
        if not display_name or display_name.startswith("-") or display_name.startswith("*"):
            continue

        # Extract model_id from the slug line (second line often has the ID)
        model_id = display_name.lower().replace(" ", "-")
        for line in lines[1:]:
            slug_match = re.match(r"^([a-z0-9\-]+)$", line.strip())
            if slug_match:
                model_id = slug_match.group(1)
                break

        # Skip if model_id looks like a date or other non-model
        if re.match(r"^\d{4}-\d{2}-\d{2}$", model_id):
            continue

        entry = _parse_model_details(markdown, provider_id, model_id, display_name, source_url)
        entries.append(entry)

    return entries


def _parse_model_details(
    markdown: str,
    provider_id: str,
    model_id: str,
    display_name: str,
    source_url: str,
) -> ModelEntry:
    """Parse individual model detail page."""
    pricing = Pricing()
    capabilities = Capabilities()
    context_window = None
    max_output_tokens = None

    # Clean display_name - remove suffix like " - AI Model Details"
    display_name = re.sub(r"\s*-\s*AI\s+Model\s+Details\s*$", "", display_name, flags=re.IGNORECASE).strip()

    # Context window - look for "Context Window" followed by value
    ctx_match = re.search(r"Context Window\s*\n\s*([\d.]+)([KM]?)", markdown, re.IGNORECASE)
    if ctx_match:
        value = float(ctx_match.group(1))
        unit = ctx_match.group(2).upper()
        if unit == "M":
            context_window = int(value * 1_000_000)
        elif unit == "K":
            context_window = int(value * 1_000)
        else:
            context_window = int(value)

    # Max output tokens
    max_out_match = re.search(r"Max Output Tokens\s*\n\s*([\d.]+)([KM]?)", markdown, re.IGNORECASE)
    if max_out_match:
        value = float(max_out_match.group(1))
        unit = max_out_match.group(2).upper()
        if unit == "M":
            max_output_tokens = int(value * 1_000_000)
        elif unit == "K":
            max_output_tokens = int(value * 1_000)
        else:
            max_output_tokens = int(value)

    # Pricing - look for "Price" section
    # Standard pattern: "$5.00 • $25.00" (input • output per 1M tokens)
    price_match = re.search(r"\$\s*([\d.]+)\s*[•·]\s*\$\s*([\d.]+)", markdown)
    if price_match:
        pricing.input_per_1m = float(price_match.group(1))
        pricing.output_per_1m = float(price_match.group(2))
    else:
        # Alternative: "Price" followed by "$X.XX" (may have empty lines between)
        # Could be "per request" (image/video generation)
        alt_price_match = re.search(r"(?i)Price\s*\n\s*\n?\s*\$\s*([\d.]+)", markdown)
        if alt_price_match:
            pricing.per_request = float(alt_price_match.group(1))

    # Cache pricing - "Cache Price $0.50 • $6.25"
    cache_match = re.search(r"Cache Price\s*\$\s*([\d.]+)\s*[•·]\s*\$\s*([\d.]+)", markdown, re.IGNORECASE)
    if cache_match:
        pricing.cache_read_per_1m = float(cache_match.group(1))
        pricing.cache_write_per_1m = float(cache_match.group(2))

    # Capabilities - look for Modalities section (Text, Image, Audio, Video)
    # Pattern: "## Modalities" followed by "### Text" etc.
    # First find the Modalities section
    modalities_section = re.search(r"(?i)##\s+Modalities\s*\n(.*?)(?=\n##\s+|\Z)", markdown, re.DOTALL)
    if modalities_section:
        modalities_text = modalities_section.group(1)

        # Check each modality - Text, Image, Audio, Video
        # Pattern: "### Modality" followed by content on next line
        for modality in ["Text", "Image", "Audio", "Video"]:
            mod_match = re.search(rf"(?i)###\s+{modality}\s*\n(.*?)(?:\n###|\Z)", modalities_text, re.DOTALL)
            if mod_match:
                mod_text = mod_match.group(1).strip().lower()
                supported = "not supported" not in mod_text

                if modality == "Text":
                    if supported:
                        capabilities.streaming = True  # Text implies streaming
                        capabilities.text = True
                elif modality == "Image":
                    capabilities.vision = supported
                elif modality == "Audio":
                    capabilities.audio = supported
                elif modality == "Video":
                    pass  # No video field in current schema

    # Determine API type from model name patterns
    name_lower = display_name.lower()
    if "claude" in name_lower:
        api_type = "Anthropic"
    elif "gpt" in name_lower or "openai" in name_lower:
        api_type = "OpenAI"
    elif "gemini" in name_lower:
        api_type = "Google"
    elif "deepseek" in name_lower or "minimax" in name_lower:
        api_type = "OpenAI"
    else:
        api_type = "OpenAI"  # default

    return ModelEntry(
        model_id=model_id,
        provider=provider_id,
        display_name=display_name,
        api_type=api_type,
        context_window=context_window,
        max_output_tokens=max_output_tokens,
        pricing=pricing,
        capabilities=capabilities,
        source={
            "url": source_url,
            "method": "scrape",
        },
    )
