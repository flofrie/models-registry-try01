"""API discovery for OpenAI-compatible /v1/models endpoint."""
import os
from typing import Optional

import httpx

from llm_registry.discovery.api._keys import openclaw_provider_key
from llm_registry.schema.model_entry import Capabilities, ModelEntry, Pricing


class OpenAIModelsClient:
    """Client for OpenAI-compatible /v1/models endpoint."""

    def __init__(self, base_url: str, endpoint: str, api_key: str | None = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.endpoint = endpoint
        self.api_key = api_key or None  # treat empty string as None
        self.timeout = timeout

    def _get_headers(self) -> dict:
        """Build request headers.

        When `api_key` is None, no Authorization header is sent (the
        provider's discovery endpoint must be public — see
        `AuthConfig.required` in `config/loader.py`).
        """
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def list_models(self) -> list[dict]:
        """Call /v1/models and return raw model data."""
        url = f"{self.base_url}{self.endpoint}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=self._get_headers())
            resp.raise_for_status()
            data = resp.json()

        return data.get("data", [])

    def map_to_model_entry(
        self, raw: dict, provider_id: str, available_endpoint_types: set[str]
    ) -> ModelEntry:
        """Map API response to ModelEntry.

        `available_endpoint_types` is the set of api styles this provider
        exposes (e.g. {"openai", "anthropic"} for OpenRouter). It gates
        which inferred api_type values are accepted — if we infer
        "anthropic" but the provider only has an "openai" endpoint, we
        fall back to "openai" since that's the only way to reach the model.
        """
        model_id = raw.get("id", "")
        name = raw.get("name", "")
        # Use None/empty as "" so the heuristic treats missing
        # descriptions the same as present-but-blank ones.
        description = (raw.get("description") or "").strip()

        api_type = self._infer_api_type(
            model_id, name, available_endpoint_types, description
        )
        openclaw_key = openclaw_provider_key(provider_id, api_type)

        # Parse pricing - handle both standard and OpenRouter format
        pricing_data = raw.get("pricing", {})
        pricing = self._parse_pricing(pricing_data)

        # Parse context window
        context_length = raw.get("context_length")

        # Use top_provider for max completion tokens if available
        top_provider = raw.get("top_provider", {})
        max_output_tokens = top_provider.get("max_completion_tokens")

        # Parse capabilities from architecture
        capabilities = self._parse_capabilities(raw.get("architecture", {}))

        return ModelEntry(
            model_id=model_id,
            provider=provider_id,
            display_name=name,
            api_type=api_type,
            openclaw_provider_key=openclaw_key,
            context_window=context_length,
            max_output_tokens=max_output_tokens,
            pricing=pricing,
            capabilities=capabilities,
            source={
                "url": f"{self.base_url}{self.endpoint}",
                "method": "api",
            },
        )

    def _parse_pricing(self, pricing_data: dict) -> Optional[Pricing]:
        """Parse pricing from API response (handles OpenRouter format)."""
        if not pricing_data:
            return None

        # OpenRouter: prices are in dollars (not per 1M), convert to per 1M
        prompt_price = pricing_data.get("prompt")
        completion_price = pricing_data.get("completion")

        # Skip if prices are -1 (N/A)
        if prompt_price == "-1" or completion_price == "-1":
            return None

        try:
            # OpenRouter returns dollar amounts, convert to per 1M
            # Round to 2 decimal places to avoid floating point issues
            prompt = round(float(prompt_price) * 1_000_000, 2) if prompt_price else None
            completion = round(float(completion_price) * 1_000_000, 2) if completion_price else None
        except (TypeError, ValueError):
            return None

        pricing = Pricing(
            input_per_1m=prompt,
            output_per_1m=completion,
        )

        # Cache pricing (OpenRouter specific)
        cache_read = pricing_data.get("input_cache_read")
        cache_write = pricing_data.get("input_cache_write")
        if cache_read and cache_read != "-1":
            try:
                pricing.cache_read_per_1m = round(float(cache_read) * 1_000_000, 2)
            except (TypeError, ValueError):
                pass
        if cache_write and cache_write != "-1":
            try:
                pricing.cache_write_per_1m = round(float(cache_write) * 1_000_000, 2)
            except (TypeError, ValueError):
                pass

        return pricing

    def _parse_capabilities(self, architecture: dict) -> Optional[Capabilities]:
        """Parse capabilities from architecture field."""
        if not architecture:
            return None

        caps = Capabilities()

        input_modalities = architecture.get("input_modalities", [])
        output_modalities = architecture.get("output_modalities", [])

        # Text
        if "text" in input_modalities or "text" in output_modalities:
            caps.text = True
            caps.streaming = True

        # Vision
        if "image" in input_modalities:
            caps.vision = True

        # Audio
        if "audio" in input_modalities:
            caps.audio = True

        # Video — no field in current schema
        if "video" in input_modalities or "video" in output_modalities:
            pass

        return caps if any([caps.text, caps.vision, caps.audio]) else None

    def _infer_api_type(
        self,
        model_id: str,
        name: str,
        available_endpoint_types: set[str],
        description: str = "",
    ) -> str:
        """Infer the API type from model id + name + (optionally) description.

        Two-pass design:
        1. Search model_id + name for a family keyword. If found, return
           that family. This pass uses ONLY the id+name, so a clear
           signal there (e.g. "gpt-4o") cannot be overridden by a
           description that mentions a different family in passing
           (e.g. "compare to Claude 3.5").
        2. If pass 1 found no family signal, consult the description as
           a tiebreaker. This helps when the id+name are uninformative
           (e.g. an opaque model id) and the description is the only
           identifying text.

        Note: pass 2 can still produce false positives. A description
        that mentions "Claude" in passing ("compatible with Claude
        3.5", "recreate Claude-style verbosity") will tip the
        inference to anthropic. There's no robust way to tell those
        mentions apart from a real "this IS a Claude model" claim, so
        the cost is documented and accepted.

        Returns one of the strings in `available_endpoint_types`. If
        no family matches, falls back to the first available type
        (typically "openai", which every provider exposes).
        """
        # Pass 1: model_id + name only.
        first = f"{model_id} {name}".lower()
        family = self._match_family(first, available_endpoint_types)
        if family is not None:
            return family

        # Pass 2: tiebreaker — also consult the description. Only kicks
        # in when pass 1 found no family signal.
        if description:
            second = f"{model_id} {name} {description}".lower()
            family = self._match_family(second, available_endpoint_types)
            if family is not None:
                return family

        # Default: prefer "openai" if available (every provider exposes
        # it), otherwise the first type in the set. Set iteration order
        # is not guaranteed across Python versions, so we don't use it
        # directly.
        if "openai" in available_endpoint_types:
            return "openai"
        if available_endpoint_types:
            return next(iter(available_endpoint_types))
        return "openai"

    @staticmethod
    def _match_family(text: str, available: set[str]) -> str | None:
        """Return the first family whose keyword appears in `text`,
        or None if no family matches. Does NOT fall back to a default.
        """
        if "anthropic" in available and any(
            t in text
            for t in ("claude", "sonnet", "opus", "haiku", "fable", "mythos")
        ):
            return "anthropic"
        if "openai" in available and any(
            t in text
            for t in ("gpt", "o1", "o3", "o4", "openai", "dall-e", "gpt-image", "sora")
        ):
            return "openai"
        if "google" in available and any(
            t in text for t in ("gemini", "veo", "imagen", "google")
        ):
            return "google"
        return None


async def discover_from_api(
    base_url: str,
    endpoint: str,
    env_var: str,
    provider_id: str,
    available_endpoint_types: set[str],
    *,
    auth_required: bool = True,
    timeout: float = 30.0,
) -> list[ModelEntry]:
    """Discover models from an OpenAI-compatible API endpoint.

    `auth_required=False` means the provider's discovery endpoint
    serves unauthenticated requests; the env var may be unset and
    no Authorization header will be sent.
    """
    api_key = os.environ.get(env_var) or None
    if auth_required and not api_key:
        raise ValueError(f"Missing API key: {env_var}")

    client = OpenAIModelsClient(base_url, endpoint, api_key, timeout)
    raw_models = await client.list_models()

    entries = []
    for raw in raw_models:
        entry = client.map_to_model_entry(raw, provider_id, available_endpoint_types)
        entries.append(entry)

    return entries
