"""Enrichment parser dispatch registry.

Maps enrichment strategy names to their parser functions.
This module is the single source of truth for known strategies.
"""
from collections.abc import Callable

from llm_registry.normalise.normaliser import normalize_wisgate_markdown

# Parser type: (markdown, provider_id, *, target_model_id, source_url) -> list[ModelEntry]
EnrichmentParser = Callable[..., list]

ENRICHMENT_PARSERS: dict[str, EnrichmentParser] = {
    "wisgate": normalize_wisgate_markdown,
}

KNOWN_ENRICHMENT_STRATEGIES: frozenset[str] = frozenset(ENRICHMENT_PARSERS.keys())
