"""Configuration loader and models."""
from pathlib import Path
from typing import Optional

import orjson
from pydantic import BaseModel, Field


class WebsiteConfig(BaseModel):
    """Website scraping configuration for a provider."""
    models_page: str
    sample_model_url: Optional[str] = None
    scraping_strategy: str = "none"  # firecrawl, playwright, http, none
    selectors: Optional[dict] = None


class AuthConfig(BaseModel):
    """API authentication configuration."""
    method: str = "bearer_token"  # bearer_token, api_key_header, api_key_query
    env_var: str
    header_name: Optional[str] = None  # default: Authorization


class ApiConfig(BaseModel):
    """API endpoint configuration."""
    type: str = "openai"  # openai, anthropic, google
    base_url: str
    models_endpoint: str = "/models"
    auth: AuthConfig


class ProviderConfig(BaseModel):
    """Configuration for a single provider."""
    id: str
    name: str
    website: WebsiteConfig
    api: Optional[ApiConfig] = None
    api_types: list[str] = Field(default_factory=list)


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