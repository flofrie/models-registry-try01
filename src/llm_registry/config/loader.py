"""Configuration loader and models."""
from pathlib import Path
from typing import Optional

import orjson
from pydantic import BaseModel, Field


class WebsiteConfig(BaseModel):
    """Website scraping configuration for a provider."""
    models_page: str
    sample_model_url: Optional[str] = None
    model_url_template: Optional[str] = None
    scraping_strategy: str = "none"  # firecrawl, playwright, http, none
    selectors: Optional[dict] = None

    def has_model_detail_url_strategy(self) -> bool:
        """Return whether per-model detail URLs can be built safely."""
        return bool(self.model_url_template or _is_model_url_template(self.sample_model_url))

    def model_detail_url(self, model_id: str) -> str:
        """Build a model detail URL from an explicit template."""
        template = self.model_url_template
        if template is None and _is_model_url_template(self.sample_model_url):
            template = self.sample_model_url
        if template is None:
            raise ValueError("No model detail URL template configured")
        return template.format(model_id=model_id)


def _is_model_url_template(value: Optional[str]) -> bool:
    return bool(value and "{model_id}" in value)


class AuthConfig(BaseModel):
    """API authentication configuration.

    `required` is True for providers whose discovery endpoint refuses
    unauthenticated requests (e.g. Wisgate, CometAPI both return 401
    without a key) and False for providers whose `/v1/models` is
    public (e.g. OpenRouter, Requesty — both serve 200 anonymously).
    When `required=False`, the env_var may be unset and the client
    will send no Authorization header.
    """
    method: str = "bearer_token"  # bearer_token, api_key_header, api_key_query
    env_var: str
    header_name: Optional[str] = None  # default: Authorization
    required: bool = True


class EndpointConfig(BaseModel):
    """A single API surface offered by a provider.

    `type` is the wire/SDK style: "openai", "anthropic", or "google".
    `auth.method` is whatever the provider actually accepts — for the
    anthropic-style surface on most providers, this is bearer_token
    (the user wires the Anthropic SDK via ANTHROPIC_AUTH_TOKEN, not
    x-api-key). For cometapi's anthropic surface, it would be x-api-key.
    """
    type: str  # "openai" | "anthropic" | "google"
    base_url: str
    models_endpoint: Optional[str] = None  # present on the discovery endpoint
    messages_endpoint: Optional[str] = None  # for anthropic-style
    generate_content_endpoint: Optional[str] = None  # for google-style
    auth: AuthConfig
    notes: Optional[str] = None  # documented quirks (e.g. auth shim required)


class ProviderConfig(BaseModel):
    """Configuration for a single provider."""
    id: str
    name: str
    website: WebsiteConfig
    endpoints: list[EndpointConfig] = Field(default_factory=list)
    # Backward-compat: optional singular `api` block (single OpenAI-style
    # endpoint) for old configs. Normalised away at load time.
    api: Optional[dict] = None


class SettingsConfig(BaseModel):
    """Global settings."""
    max_concurrent_requests: int = 5
    request_timeout_seconds: int = 30
    retry_attempts: int = 3
    retry_backoff_factor: float = 2.0
    llm_cache_ttl_hours: int = 24
    backup_count: int = 5


class Config(BaseModel):
    """Root configuration."""
    version: str = "1.0"
    providers: list[ProviderConfig] = Field(default_factory=list)
    settings: SettingsConfig = Field(default_factory=SettingsConfig)


def load_config(config_path: Optional[Path] = None) -> Config:
    """Load and validate configuration from providers.json."""
    if config_path is None:
        # Look in current directory first, then package directory
        local_path = Path.cwd() / "providers.json"
        package_path = Path(__file__).parent.parent.parent.parent / "providers.json"

        if local_path.exists():
            config_path = local_path
        elif package_path.exists():
            config_path = package_path
        else:
            raise FileNotFoundError(f"Config file not found: providers.json (looked in {Path.cwd()} and {package_path})")

    with open(config_path, "rb") as f:
        data = orjson.loads(f.read())

    return Config(**data)
