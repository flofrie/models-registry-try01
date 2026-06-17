"""Tests for cometapi normaliser.

Uses golden fixtures saved from live scrapes — the parser is exercised
against real pages, not synthetic data, so any drift in real-world
content will surface as a test failure.
"""
from pathlib import Path

from llm_registry.discovery.api.openai import OpenAIModelsClient
from llm_registry.discovery.api.requesty import RequestyModelsClient
from llm_registry.normalise import normalize_wisgate_markdown
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


def test_gemini_3_1_pro_preview_table_below_30_lines():
    """Regression: the Gemini 3.1 Pro Preview page lists context/max in a
    2-column spec table (header 'Input token limit (context)' / 'Output
    token limit') that appears at line 73, beyond the 30-line inline
    scan. Before the fix, both context_window and max_output_tokens
    were None even though the data was on the page."""
    md = _load("gemini-3-1-pro-preview")
    e = parse_cometapi_detail_page(md, "gemini-3-1-pro-preview", "cometapi")

    assert e is not None
    assert e.context_window == 1_048_576
    assert e.max_output_tokens == 65_536
    # Inline pricing still works
    assert e.pricing is not None
    assert e.pricing.input_per_1m == 1.6
    assert e.pricing.output_per_1m == 9.6


def test_gemini_3_1_flash_lite_preview_table_with_up_to_prefix():
    """Regression: this page has the 'Context window' table header with
    a value 'Up to 1 million tokens (multimodal text...)' — needs the
    'million' branch of the parser, not just the 'N tokens' branch."""
    md = _load("gemini-3-1-flash-lite-preview")
    e = parse_cometapi_detail_page(md, "gemini-3-1-flash-lite-preview", "cometapi")

    assert e is not None
    assert e.context_window == 1_000_000
    # Pricing still works
    assert e.pricing is not None


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


def test_404_page_returns_none():
    """When a sitemap URL resolves to a 404 page (HTTP 200, body says
    'Page Not Found'), parse_cometapi_detail_page returns None so the
    caller doesn't write a half-populated entry."""
    body = """\
[Kimi K2.7 Code is now on CometAPI](https://www.cometapi.com/models/moonshotai/kimi-k2-7-code/)
![404](https://www.cometapi.com/_next/image/?url=%2Ficon.svg&w=256&q=75)
# Page Not Found
The page you're looking for doesn't exist or may have been moved.
[Browse All Models](https://www.cometapi.com/models/)
"""
    assert parse_cometapi_detail_page(body, "claude-fable-5", "cometapi") is None


# --- api_type inference (v1.3: lowercase, gated by available_endpoint_types) -

def test_infer_api_type_claude_canonical_name():
    """The standard 'claude-*' id maps to anthropic when offered."""
    c = OpenAIModelsClient("http://x", "/m", "k")
    assert c._infer_api_type("claude-sonnet-4-6", "", {"openai", "anthropic", "google"}) == "anthropic"


def test_infer_api_type_anthropic_family_without_claude_word():
    """Regression: CometAPI exposes some models with the 'claude' word
    stripped (e.g. 'cometapi-sonnet-4-5-20250929'). The bare family
    names 'sonnet', 'opus', 'haiku', 'fable', 'mythos' are exclusively
    Anthropic — they should still map to anthropic when the provider
    offers it."""
    c = OpenAIModelsClient("http://x", "/m", "k")
    for mid in [
        "cometapi-sonnet-4-5-20250929",
        "cometapi-opus-4-6",
        "cometapi-haiku-4-5-20251001",
        "anthropic-fable-5",
        "claude-mythos-5",
    ]:
        assert c._infer_api_type(mid, "", {"openai", "anthropic"}) == "anthropic", mid


def test_infer_api_type_gpt_image_sora_dall_e_are_openai():
    c = OpenAIModelsClient("http://x", "/m", "k")
    for mid in ["gpt-5", "o1-preview", "o3-mini", "openai/gpt-4o", "dall-e-3", "gpt-image-1", "sora-2"]:
        assert c._infer_api_type(mid, "", {"openai", "anthropic"}) == "openai", mid


def test_infer_api_type_veo_imagen_are_google():
    c = OpenAIModelsClient("http://x", "/m", "k")
    for mid in ["gemini-2.5-pro", "veo-3.1", "imagen-3.0", "google/gemini-3"]:
        assert c._infer_api_type(mid, "", {"openai", "google"}) == "google", mid


def test_infer_api_type_gemini_falls_back_when_no_google_endpoint():
    """v1.3: providers without a 'google' endpoint (OpenRouter, Requesty)
    cannot route Gemini models to the Google surface. They must fall
    back to 'openai' (which all four providers expose)."""
    c = OpenAIModelsClient("http://x", "/m", "k")
    for mid in ["gemini-2.5-pro", "veo-3.1", "google/gemini-3"]:
        # openrouter / requesty shape: only openai + anthropic
        assert c._infer_api_type(mid, "", {"openai", "anthropic"}) == "openai", mid


def test_infer_api_type_falls_back_to_first_available():
    """Unknown model id, no match → first available type."""
    c = OpenAIModelsClient("http://x", "/m", "k")
    # unknown id, but provider has all three
    assert c._infer_api_type("llama-3-70b", "", {"openai", "anthropic", "google"}) == "openai"


def test_requesty_infer_api_type_uses_same_heuristic():
    """Requesty client must use the same logic."""
    c = RequestyModelsClient("http://x", "/m", "k")
    # requesty offers openai + anthropic (no google)
    assert c._infer_api_type("cometapi-sonnet-4-6", "", {"openai", "anthropic"}) == "anthropic"
    assert c._infer_api_type("gpt-4o", "", {"openai", "anthropic"}) == "openai"
    # gemini on requesty → openai fallback
    assert c._infer_api_type("gemini-2.5-pro", "", {"openai", "anthropic"}) == "openai"


def test_infer_api_type_description_does_not_override_clear_id_signal():
    """A clear family keyword in model_id wins even if the description
    mentions a different family. This is the safety property of the
    two-pass design: a description like "compare to Claude 3.5" can't
    reclassify a clearly-named GPT model."""
    c = OpenAIModelsClient("http://x", "/m", "k")
    av = {"openai", "anthropic", "google"}
    # id says gpt, description mentions claude → openai wins
    assert (
        c._infer_api_type("openai/gpt-4o", "GPT-4o",
                          av, "Replacement for Anthropic's Claude 3.5")
        == "openai"
    )
    # id says claude, description mentions openai → anthropic wins
    assert (
        c._infer_api_type("anthropic/claude-sonnet-4-6", "Claude Sonnet 4.6",
                          av, "Better than GPT-4o on coding")
        == "anthropic"
    )


def test_infer_api_type_description_is_tiebreaker_when_id_and_name_empty():
    """When model_id and name have no family signal, the description
    is consulted as a tiebreaker. This is the description-driven case
    the heuristic was extended to cover."""
    c = OpenAIModelsClient("http://x", "/m", "k")
    av = {"openai", "anthropic", "google"}
    # non-informative id + name, description has the signal
    assert (
        c._infer_api_type("custom-id", "Acme Model", av,
                          "Anthropic's flagship Claude model")
        == "anthropic"
    )
    assert (
        c._infer_api_type("custom-id", "Acme Model", av,
                          "Google's Gemini family")
        == "google"
    )
    # Without the description, the default is "openai"
    assert c._infer_api_type("custom-id", "Acme Model", av) == "openai"


def test_infer_api_type_description_passive_mention_still_tips():
    """Known limitation: a description that mentions 'Claude' in passing
    (e.g. 'compatible with Claude 3.5') will tip the inference to
    anthropic even though the model itself isn't Claude. This is
    the trade-off the tiebreaker accepts; documented in the docstring."""
    c = OpenAIModelsClient("http://x", "/m", "k")
    av = {"openai", "anthropic", "google"}
    # Relace-style model: id+name have no signal, description
    # mentions Claude as something it works with. Gets reclassified
    # to anthropic. This is a real limitation of the heuristic; the
    # only way to avoid it is to skip the description entirely.
    assert (
        c._infer_api_type("relace/relace-apply-3", "Relace: Relace Apply 3", av,
                          "Applies edits from GPT-4o, Claude, and others into your files.")
        == "anthropic"
    )


# --- openclaw_provider_key derivation ---------------------------------------

def _make_entry_openai(raw, **kwargs):
    return OpenAIModelsClient("http://x", "/m", "k").map_to_model_entry(raw, **kwargs)


def test_openclaw_key_uniformly_derived_for_anthropic():
    """openclaw_provider_key is always '{openclaw_provider_id}-{api_type}'.
    The only alias is cometapi → comet (OpenClaw's actual convention)."""
    raw = {"id": "claude-sonnet-4-6", "name": ""}
    e = _make_entry_openai(
        raw,
        provider_id="cometapi",
        available_endpoint_types={"openai", "anthropic", "google"},
    )
    assert e.api_type == "anthropic"
    assert e.openclaw_provider_key == "comet-anthropic"


def test_openclaw_key_derived_for_anthropic_on_openrouter():
    raw = {"id": "anthropic/claude-fable-5", "name": ""}
    e = _make_entry_openai(
        raw,
        provider_id="openrouter",
        available_endpoint_types={"openai", "anthropic"},
    )
    assert e.api_type == "anthropic"
    assert e.openclaw_provider_key == "openrouter-anthropic"


def test_openclaw_key_derived_for_openai_on_wisgate():
    raw = {"id": "gpt-4o", "name": ""}
    e = _make_entry_openai(
        raw,
        provider_id="wisgate",
        available_endpoint_types={"openai", "anthropic", "google"},
    )
    assert e.api_type == "openai"
    assert e.openclaw_provider_key == "wisgate-openai"


def test_openclaw_key_google_falls_back_to_openai_without_endpoint():
    """Regression: a Gemini model on a provider with no google endpoint
    must derive openclaw_key=provider-openai (the only surface that
    actually works)."""
    raw = {"id": "google/gemini-3-flash", "name": ""}
    e = _make_entry_openai(
        raw,
        provider_id="openrouter",
        available_endpoint_types={"openai", "anthropic"},
    )
    assert e.api_type == "openai"
    assert e.openclaw_provider_key == "openrouter-openai"


def test_requesty_openclaw_key_derived_uniformly():
    """Same uniform derivation in the Requesty client."""
    raw = {"id": "anthropic/claude-fable-5", "description": ""}
    e = RequestyModelsClient("http://x", "/m", "k").map_to_model_entry(
        raw,
        provider_id="requesty",
        available_endpoint_types={"openai", "anthropic"},
    )
    assert e.api_type == "anthropic"
    assert e.openclaw_provider_key == "requesty-anthropic"


def test_requesty_sparse_text_model_gets_text_capability():
    raw = {"id": "nvidia/nemotron-3-ultra-550b-a55b", "description": ""}
    e = RequestyModelsClient("http://x", "/m", "k").map_to_model_entry(
        raw,
        provider_id="requesty",
        available_endpoint_types={"openai", "anthropic"},
    )

    assert e.capabilities is not None
    assert e.capabilities.text is True
    assert e.capabilities.streaming is True


def test_wisgate_parser_filters_all_unsupported_modalities_to_none():
    """A model whose Modalities section explicitly marks every modality
    as not supported should produce ``capabilities=None`` — the
    ``_has_capabilities`` guard converts an all-False ``Capabilities`` to
    ``None`` rather than letting it leak into MODELS.json as a misleading
    empty object.

    This test exercises the guard directly: without it, the parser would
    set every modality field to ``False`` and the resulting
    ``Capabilities`` object would survive into the output.
    """
    markdown = """# Unknown Model

nvidia-nemotron-3-ultra-550b-a55b

## Modalities

### Text
Not supported

### Image
Not supported

### Audio
Not supported
"""
    entries = normalize_wisgate_markdown(
        markdown,
        "requesty",
        target_model_id="nvidia-nemotron-3-ultra-550b-a55b",
    )

    assert entries[0].capabilities is None
