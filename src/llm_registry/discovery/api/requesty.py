"""API discovery for Requesty's /v1/models endpoint."""
import os
from typing import Optional

import httpx

from llm_registry.schema.model_entry import Capabilities, ModelEntry, Pricing


class RequestyModelsClient:
    """Client for Requesty's /v1/models endpoint.

    Requesty returns a custom format with top-level fields:
      id, input_price, cached_price, output_price, context_window,
      max_output_tokens, supports_vision, supports_tool_calling, ...
    Prices are in dollars per token (e.g. 3e-7 = $0.30 per 1M).
    """

    def __init__(self, base_url: str, endpoint: str, api_key: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def list_models(self) -> list[dict]:
        url = f"{self.base_url}{self.endpoint}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=self._get_headers())
            resp.raise_for_status()
            data = resp.json()
        return data.get("data", [])

    def map_to_model_entry(
        self, raw: dict, provider_id: str, available_endpoint_types: set[str]
    ) -> ModelEntry:
        model_id = raw.get("id", "")
        description = raw.get("description", "")

        api_type = self._infer_api_type(model_id, description, available_endpoint_types)
        openclaw_key = f"{provider_id}-{api_type}" if api_type else None

        pricing = self._parse_pricing(raw)
        context_window = raw.get("context_window")
        max_output_tokens = raw.get("max_output_tokens") or None
        # 0 is "unknown" for requesty; treat as None
        if max_output_tokens == 0:
            max_output_tokens = None

        capabilities = self._parse_capabilities(raw)

        return ModelEntry(
            model_id=model_id,
            provider=provider_id,
            display_name=None,  # Description is too long to use as a short name
            api_type=api_type,
            openclaw_provider_key=openclaw_key,
            context_window=context_window,
            max_output_tokens=max_output_tokens,
            pricing=pricing,
            capabilities=capabilities,
            source={
                "url": f"{self.base_url}{self.endpoint}",
                "method": "api",
            },
        )

    def _parse_pricing(self, raw: dict) -> Optional[Pricing]:
        input_price = raw.get("input_price")
        output_price = raw.get("output_price")
        cached_price = raw.get("cached_price")
        caching_price = raw.get("caching_price")  # cache write

        # Skip if all zero
        if (input_price is None or input_price == 0) and \
           (output_price is None or output_price == 0) and \
           (cached_price is None or cached_price == 0):
            return None

        # Prices are $/token; convert to $/1M
        try:
            inp = round(float(input_price) * 1_000_000, 4) if input_price else None
            out = round(float(output_price) * 1_000_000, 4) if output_price else None
            cache_read = round(float(cached_price) * 1_000_000, 4) if cached_price else None
            cache_write = round(float(caching_price) * 1_000_000, 4) if caching_price else None
        except (TypeError, ValueError):
            return None

        return Pricing(
            input_per_1m=inp,
            output_per_1m=out,
            cache_read_per_1m=cache_read,
            cache_write_per_1m=cache_write,
        )

    def _parse_capabilities(self, raw: dict) -> Optional[Capabilities]:
        caps = Capabilities()

        # If model has an API type of chat, it has text
        if raw.get("api") in ("chat", "responses"):
            caps.text = True
            caps.streaming = True

        if raw.get("supports_vision"):
            caps.vision = True

        # Tool calling is a capability worth tracking
        if raw.get("supports_tool_calling"):
            caps.tool_use = True

        # Audio is mentioned in description for some models
        desc = (raw.get("description") or "").lower()
        if "audio" in desc:
            caps.audio = True

        return caps if any([caps.text, caps.vision, caps.audio, caps.tool_use]) else None

    def _infer_api_type(
        self, model_id: str, description: str, available_endpoint_types: set[str]
    ) -> str:
        combined = f"{model_id} {description}".lower()

        # Anthropic family
        if any(t in combined for t in ("claude", "sonnet", "opus", "haiku", "fable", "mythos")):
            if "anthropic" in available_endpoint_types:
                return "anthropic"
        # OpenAI family
        if any(t in combined for t in ("gpt", "o1", "o3", "o4", "openai", "dall-e", "gpt-image", "sora")):
            if "openai" in available_endpoint_types:
                return "openai"
        # Google family
        if any(t in combined for t in ("gemini", "veo", "imagen", "google")):
            if "google" in available_endpoint_types:
                return "google"

        if "openai" in available_endpoint_types:
            return "openai"
        if available_endpoint_types:
            return next(iter(available_endpoint_types))
        return "openai"


async def discover_from_requesty(
    base_url: str,
    endpoint: str,
    env_var: str,
    provider_id: str,
    available_endpoint_types: set[str],
    timeout: float = 30.0,
) -> list[ModelEntry]:
    api_key = os.environ.get(env_var)
    if not api_key:
        raise ValueError(f"Missing API key: {env_var}")

    client = RequestyModelsClient(base_url, endpoint, api_key, timeout)
    raw_models = await client.list_models()

    entries = []
    for raw in raw_models:
        entry = client.map_to_model_entry(raw, provider_id, available_endpoint_types)
        entries.append(entry)
    return entries
