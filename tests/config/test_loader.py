import pytest

from llm_registry.config.loader import WebsiteConfig


def test_website_config_builds_detail_url_from_explicit_template():
    website = WebsiteConfig(
        models_page="https://wisgate.ai/models",
        model_url_template="https://wisgate.ai/models/{model_id}",
    )

    assert website.has_model_detail_url_strategy() is True
    assert website.model_detail_url("claude-opus-4-8") == (
        "https://wisgate.ai/models/claude-opus-4-8"
    )


def test_website_config_does_not_infer_from_concrete_sample_url():
    website = WebsiteConfig(
        models_page="https://www.cometapi.com/models",
        sample_model_url="https://www.cometapi.com/models/anthropic/claude-opus-4-8",
    )

    assert website.has_model_detail_url_strategy() is False
    with pytest.raises(ValueError, match="No model detail URL template configured"):
        website.model_detail_url("claude-sonnet-4-6")


def test_website_config_accepts_legacy_sample_url_template():
    website = WebsiteConfig(
        models_page="https://openrouter.ai/models",
        sample_model_url="https://openrouter.ai/{model_id}",
    )

    assert website.has_model_detail_url_strategy() is True
    assert website.model_detail_url("anthropic/claude-3.5-sonnet") == (
        "https://openrouter.ai/anthropic/claude-3.5-sonnet"
    )
