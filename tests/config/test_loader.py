# SPDX-License-Identifier: MIT
import pytest
from pydantic import ValidationError

from llm_registry.config.loader import SettingsConfig, WebsiteConfig


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


def test_website_config_rejects_unknown_placeholder_in_explicit_template():
    with pytest.raises(ValueError, match="\\{version\\}"):
        WebsiteConfig(
            models_page="https://example.com/models",
            model_url_template="https://example.com/models/{model_id}/{version}",
        )


def test_website_config_rejects_uppercase_placeholder_alias():
    with pytest.raises(ValueError, match="\\{Model_Id\\}"):
        WebsiteConfig(
            models_page="https://example.com/models",
            model_url_template="https://example.com/models/{Model_Id}",
        )


def test_website_config_requires_model_id_in_explicit_template():
    with pytest.raises(ValueError, match="must include \\{model_id\\}"):
        WebsiteConfig(
            models_page="https://example.com/models",
            model_url_template="https://example.com/models/static",
        )


def test_website_config_rejects_unknown_placeholder_in_legacy_sample_url_template():
    with pytest.raises(ValueError, match="\\{provider_slug\\}"):
        WebsiteConfig(
            models_page="https://example.com/models",
            sample_model_url="https://example.com/models/{provider_slug}/{model_id}",
        )


def test_website_config_rejects_sample_url_placeholder_without_model_id():
    with pytest.raises(ValueError, match="\\{version\\}"):
        WebsiteConfig(
            models_page="https://example.com/models",
            sample_model_url="https://example.com/models/{version}",
        )


def test_enrichment_strategy_default_is_none():
    website = WebsiteConfig(models_page="https://example.com/models")
    assert website.enrichment_strategy is None


def test_enrichment_strategy_wisgate_is_valid():
    website = WebsiteConfig(
        models_page="https://wisgate.ai/models",
        enrichment_strategy="wisgate",
    )
    assert website.enrichment_strategy == "wisgate"


def test_enrichment_strategy_unknown_raises():
    with pytest.raises(ValueError, match="bogus"):
        WebsiteConfig(
            models_page="https://example.com/models",
            enrichment_strategy="bogus",
        )


def test_firecrawl_timeout_seconds_defaults_to_none():
    settings = SettingsConfig()
    assert settings.firecrawl_timeout_seconds is None


def test_firecrawl_timeout_seconds_must_be_positive():
    with pytest.raises(ValidationError):
        SettingsConfig(firecrawl_timeout_seconds=0)
