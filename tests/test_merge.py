from llm_registry.merge import merge_model_entries
from llm_registry.schema.model_entry import Capabilities, ModelEntry, Pricing, Source


def test_merge_model_entries_preserves_existing_when_new_fields_are_none():
    existing = ModelEntry(
        model_id="claude-sonnet",
        provider="cometapi",
        api_type="anthropic",
        context_window=200_000,
        max_output_tokens=64_000,
        pricing=Pricing(input_per_1m=2.0, output_per_1m=10.0),
        capabilities=Capabilities(text=True, streaming=True),
        source=Source(url="https://example.test/detail", method="scrape"),
    )
    new = ModelEntry(
        model_id="claude-sonnet",
        provider="cometapi",
        api_type="anthropic",
        pricing=None,
        context_window=None,
        source=Source(url="https://api.example.test/models", method="api"),
    )

    merged = merge_model_entries(existing, new)

    assert merged.context_window == 200_000
    assert merged.max_output_tokens == 64_000
    assert merged.pricing.input_per_1m == 2.0
    assert merged.pricing.output_per_1m == 10.0
    assert merged.capabilities.text is True
    assert merged.source.url == "https://api.example.test/models"
    assert merged.source.method == "api"


def test_merge_model_entries_merges_nested_models_field_by_field():
    existing = ModelEntry(
        model_id="model",
        provider="openrouter",
        pricing=Pricing(input_per_1m=0.5, output_per_1m=1.5, cache_read_per_1m=0.1),
        capabilities=Capabilities(text=True, streaming=True),
    )
    new = ModelEntry(
        model_id="model",
        provider="openrouter",
        pricing=Pricing(input_per_1m=0.6, output_per_1m=None, cache_write_per_1m=0.2),
        capabilities=Capabilities(vision=True),
    )

    merged = merge_model_entries(existing, new)

    assert merged.pricing.input_per_1m == 0.6
    assert merged.pricing.output_per_1m == 1.5
    assert merged.pricing.cache_read_per_1m == 0.1
    assert merged.pricing.cache_write_per_1m == 0.2
    assert merged.capabilities.text is True
    assert merged.capabilities.streaming is True
    assert merged.capabilities.vision is True


def test_merge_model_entries_ignores_all_null_nested_model():
    existing = ModelEntry(
        model_id="model",
        provider="requesty",
        capabilities=Capabilities(text=True, streaming=True),
    )
    new = ModelEntry(
        model_id="model",
        provider="requesty",
        capabilities=Capabilities(),
    )

    merged = merge_model_entries(existing, new)

    assert merged.capabilities.text is True
    assert merged.capabilities.streaming is True
