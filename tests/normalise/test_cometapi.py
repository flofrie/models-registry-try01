"""Tests for cometapi normaliser.

Uses golden fixtures saved from live scrapes — the parser is exercised
against real pages, not synthetic data, so any drift in real-world
content will surface as a test failure.
"""
from pathlib import Path

from llm_registry.discovery.api.openai import OpenAIModelsClient
from llm_registry.discovery.api.requesty import RequestyModelsClient
from llm_registry.normalise.cometapi import (
    build_slug_to_url_map,
    find_url_for_model,
    parse_cometapi_detail_page,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / f"cometapi_{name}.md").read_text()


# --- parse_cometapi_detail_page: real fixtures -------------------------------

def test_claude_sonnet_4_6_inline_pricing():
    """Standard pattern: 'Input:$X/M' / 'Output:$Y/M' in the first 30 lines."""
    md = _load("claude-sonnet-4-6")
    e = parse_cometapi_detail_page(md, "claude-sonnet-4-6", "cometapi")

    assert e.provider == "cometapi"
    assert e.model_id == "claude-sonnet-4-6"
    assert e.display_name == "Claude Sonnet 4.6"
    assert e.pricing is not None
    assert e.pricing.input_per_1m == 2.4
    assert e.pricing.output_per_1m == 12.0
    # Context comes from tech-spec table ("| **Context window** | 200,000 tokens |")
    assert e.context_window == 200_000


def test_gpt_4o_pricing_and_context_from_table():
    """Context from bold table row: '| **Context length** | 128,000 tokens |'."""
    md = _load("gpt-4o")
    e = parse_cometapi_detail_page(md, "gpt-4o", "cometapi")

    assert e.pricing is not None
    assert e.pricing.input_per_1m == 2.0
    assert e.pricing.output_per_1m == 8.0
    assert e.context_window == 128_000


def test_gemini_3_flash_thousands_separated_context():
    """Regression: page shows 'Context:1,048,576' inline. The original
    regex only matched digits+dots, returning 1 instead of 1,048,576."""
    md = _load("gemini-3-flash")
    e = parse_cometapi_detail_page(md, "gemini-3-flash", "cometapi")

    assert e.context_window == 1_048_576  # exactly 1M
    assert e.pricing is not None
    assert e.pricing.input_per_1m == 0.4
    assert e.pricing.output_per_1m == 2.4
    # "Max Output:65.5k" → 65.5 * 1000 = 65_500
    assert e.max_output_tokens == 65_500


def test_sora_2_per_second_pricing():
    """Video/image gen models quote price per second, not per 1M tokens."""
    md = _load("sora-2")
    e = parse_cometapi_detail_page(md, "sora-2", "cometapi")

    # No input/output pricing for video models
    assert e.pricing is not None
    assert e.pricing.input_per_1m is None
    assert e.pricing.output_per_1m is None
    # per_request is the per-second value
    assert e.pricing.per_request == 0.08
    # Video modality detected
    assert e.capabilities is not None
    assert e.capabilities.vision is True


def test_claude_opus_4_8_capabilities_detected():
    md = _load("claude-opus-4-8")
    e = parse_cometapi_detail_page(md, "claude-opus-4-8", "cometapi")

    assert e.capabilities is not None
    assert e.capabilities.text is True
    assert e.capabilities.streaming is True
    # Pricing inline + context from table (1M)
    assert e.pricing.input_per_1m == 4.0
    assert e.pricing.output_per_1m == 20.0
    assert e.context_window == 1_000_000


# --- find_url_for_model ------------------------------------------------------

def test_find_url_exact_match():
    slug_map = {
        "claude-sonnet-4-6": ("anthropic", "claude-sonnet-4-6"),
        "gpt-4o": ("openai", "gpt-4o"),
    }
    assert find_url_for_model("claude-sonnet-4-6", slug_map) == ("anthropic", "claude-sonnet-4-6")


def test_find_url_slash_split():
    """API sometimes returns 'provider/model' IDs; the matcher splits on '/'."""
    slug_map = {
        "flux-2-dev": ("black-forest-labs", "flux-2-dev"),
    }
    assert find_url_for_model("black-forest-labs/flux-2-dev", slug_map) == (
        "black-forest-labs",
        "flux-2-dev",
    )


def test_find_url_dots_to_dashes():
    """API uses dots in version numbers; sitemap uses dashes."""
    slug_map = {"gpt-4-1": ("openai", "gpt-4-1")}
    assert find_url_for_model("gpt-4.1", slug_map) == ("openai", "gpt-4-1")


def test_find_url_no_match_returns_none():
    slug_map = {"claude-sonnet-4-6": ("anthropic", "claude-sonnet-4-6")}
    assert find_url_for_model("abab5.5-chat", slug_map) is None


# --- build_slug_to_url_map ---------------------------------------------------

def test_build_slug_map_uses_slug_as_key():
    entries = [
        ("anthropic", "claude-sonnet-4-6"),
        ("openai", "gpt-4o"),
    ]
    m = build_slug_to_url_map(entries)
    assert m == {
        "claude-sonnet-4-6": ("anthropic", "claude-sonnet-4-6"),
        "gpt-4o": ("openai", "gpt-4o"),
    }


def test_build_slug_map_last_wins_on_duplicates():
    """If two providers share a slug, the last one overwrites the first.
    Documented behaviour; useful for callers who care to dedupe upstream."""
    entries = [
        ("provider-a", "shared-slug"),
        ("provider-b", "shared-slug"),
    ]
    assert build_slug_to_url_map(entries) == {"shared-slug": ("provider-b", "shared-slug")}


# --- empty markdown edge case -----------------------------------------------

def test_empty_markdown_returns_entry_with_none_fields():
    e = parse_cometapi_detail_page("", "unknown-model", "cometapi")
    assert e.model_id == "unknown-model"
    assert e.provider == "cometapi"
    assert e.pricing is None
    assert e.context_window is None
    assert e.display_name is None


# --- api_type inference (regression: cometapi-claude-* misclassification) ---

def test_infer_api_type_claude_canonical_name():
    """The standard 'claude-*' id should map to Anthropic."""
    c = OpenAIModelsClient("http://x", "/m", "k")
    assert c._infer_api_type("claude-sonnet-4-6", "", ["OpenAI", "Anthropic"]) == "Anthropic"


def test_infer_api_type_anthropic_family_without_claude_word():
    """Regression: CometAPI exposes some models with the 'claude' word
    stripped (e.g. 'cometapi-sonnet-4-5-20250929'). The bare family
    names 'sonnet', 'opus', 'haiku', 'fable', 'mythos' are exclusively
    Anthropic — they should still map to Anthropic."""
    c = OpenAIModelsClient("http://x", "/m", "k")
    for mid in [
        "cometapi-sonnet-4-5-20250929",
        "cometapi-opus-4-6",
        "cometapi-haiku-4-5-20251001",
        "anthropic-fable-5",
        "claude-mythos-5",
    ]:
        assert c._infer_api_type(mid, "", ["OpenAI"]) == "Anthropic", mid


def test_infer_api_type_gpt_image_sora_dall_e_are_openai():
    c = OpenAIModelsClient("http://x", "/m", "k")
    for mid in ["gpt-5", "o1-preview", "o3-mini", "openai/gpt-4o", "dall-e-3", "gpt-image-1", "sora-2"]:
        assert c._infer_api_type(mid, "", ["Anthropic"]) == "OpenAI", mid


def test_infer_api_type_veo_imagen_are_google():
    c = OpenAIModelsClient("http://x", "/m", "k")
    for mid in ["gemini-2.5-pro", "veo-3.1", "imagen-3.0", "google/gemini-3"]:
        assert c._infer_api_type(mid, "", ["OpenAI"]) == "Google", mid


def test_infer_api_type_falls_back_to_api_types():
    c = OpenAIModelsClient("http://x", "/m", "k")
    # unknown id, no match → fall back to first configured api_type
    assert c._infer_api_type("llama-3-70b", "", ["OpenAI"]) == "OpenAI"


def test_requesty_infer_api_type_uses_same_heuristic():
    """Requesty client must use the same logic — same bug existed there."""
    c = RequestyModelsClient("http://x", "/m", "k")
    assert c._infer_api_type("cometapi-sonnet-4-6", "", ["OpenAI"]) == "Anthropic"
    assert c._infer_api_type("gpt-4o", "", ["OpenAI"]) == "OpenAI"
    assert c._infer_api_type("gemini-2.5-pro", "", ["OpenAI"]) == "Google"
