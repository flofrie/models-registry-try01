# LLM Models Registry — Software Specification

Document ID: SPEC-LLM-REG-002

Version: 1.3

Date: 2026-06-14

Author: Florian Friedrich

Status: Active

## 1. Overview

### 1.1 Purpose

The LLM Models Registry is a software tool that maintains an up-to-date, machine-readable database of available large language models (LLMs) across multiple API providers. It mirrors and extends the existing MODELS.json file currently populated for Wisgate, and generalises the process to any number of configurable providers.

### 1.2 Scope

In scope: Scraping provider websites for model listings, pricing, and capabilities; querying provider APIs for model metadata; normalising heterogeneous data into a common schema; outputting MODELS.json and an optional human-readable MODELS.md.

Out of scope: Real-time model availability monitoring, performance benchmarking, model quality evaluation, direct integration with OpenClaw configuration (that lives in a separate layer).

### 1.3 Target Providers (Initial)

| Provider | Models Page | Example URL for a specific model | Docs | API Docs | Notes |
|----------|-------------|----------------------------------|------|----------|-------|
| Wisgate | https://wisgate.ai/models | https://wisgate.ai/models/claude-opus-4-8 | https://wisdom-docs.juheapi.com/ | https://wisdom-docs.juheapi.com/api-reference/text/completion | |
| OpenRouter | https://openrouter.ai/models | https://openrouter.ai/anthropic/claude-opus-4.8 | https://openrouter.ai/docs/quickstart | https://openrouter.ai/docs/api/reference/overview | |
| CometAPI | https://www.cometapi.com/models/ | https://www.cometapi.com/models/anthropic/claude-opus-4-8/ | https://apidoc.cometapi.com/ | https://apidoc.cometapi.com/api/text | |
| Requesty | https://app.requesty.ai/model-library | https://app.requesty.ai/model-library | https://docs.requesty.ai/quickstart | https://docs.requesty.ai/api-reference/inference-apis | does not have individual pages for specific models, but contains relevant information in the model library within a detailed table |

The provider list must be configurable, allowing addition, removal, or modification without code changes.

> **[IMPL]** Simple providers with an OpenAI-compatible `/v1/models` endpoint need zero code — just config. Custom code (an API client in `discovery/api/`, a normaliser in `normalise/`) is only needed when the shape doesn't fit the standard client or the detail pages need provider-specific parsing. See `CONTRIBUTING.md` for the decision tree.


## 2. System Architecture

### 2.1 High-Level Flow

```
┌─────────────────────────────────────────────────────┐
│                  Provider Config                    │
│  (JSON: URLs, API types, scraping strategy, auth)   │
└────────────────────────┬────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   ┌──────────┐   ┌──────────┐   ┌──────────┐
   │ Website  │   │   API    │   │   API    │
   │ Scraper  │   │  Docs    │   │  Query   │
   │          │   │ Parser   │   │(list     │
   │ (JS-heavy│   │          │   │  models) │
   │  pages)  │   │          │   │          │
   └────┬─────┘   └────┬─────┘   └────┬─────┘
        │              │              │
        └──────────────┼──────────────┘
                       ▼
         ┌─────────────────────────┐
         │    Data Normaliser      │
         │  (unified schema,       │
         │   validation, dedup)    │
         └────────────┬────────────┘
                      ▼
         ┌─────────────────────────┐
         │    Output Generator     │
         │  MODELS.json + MODELS.md│
         └─────────────────────────┘
```


### 2.2 Components

Provider Configuration Loader — reads providers.json, validates entries, resolves authentication credentials

Website Scraper — crawls JS-heavy provider pages using a headless browser (Playwright/Puppeteer) or a dedicated scraping API (Firecrawl)

API Documentation Parser — extracts API base URLs, endpoint paths, and authentication schemes from provider docs

API Model Lister — calls provider APIs (e.g. /v1/models, /models) to programmatically enumerate available models

Data Normaliser — maps provider-specific fields to the common schema, deduplicates, validates

LLM Extraction Cache — caches LLM-parsed results to avoid redundant calls

Output Generator — writes MODELS.json and an optional human-readable MODELS.md

### 2.3 Technology Choices

| Concern | Recommendation | Rationale |
|---------|----------------|-----------|
| Language | Python 3.12+ | Existing ecosystem (Playwright, httpx, pydantic); Flo's primary language |
| Async runtime | asyncio + httpx [async] | I/O-bound; parallel provider fetching; cleaner than threading |
| Headless browser | Playwright (via playwright-python) | **Reserved / not yet used** — Firecrawl is the only scraping path currently wired up. Playwright is listed in `pyproject.toml` for future use. |
| Scraping fallback | Firecrawl API | Already configured (API key in TOOLS.md); handles JS rendering as a service |
| Data validation | Pydantic v2 | Schema enforcement, type coercion, validation |
| HTTP client | httpx | Async, HTTP/2, connection pooling |
| Local state | SQLite (internal) + JSON (output) | Zero-dep DB for state; JSON for interchange |
| Output format | JSON (primary) + Markdown (companion) | Machine-readable primary; human-readable secondary |


## 3. Configuration

### 3.1 Provider Configuration File (providers.json)

This is the central configuration file. Each provider entry specifies how to discover its models.

This is an example, and the actual initial providers.json file should be created and populated as part of the tool design process.

NOTE: The example below shows the current multi-endpoint provider structure. Providers like Wisgate expose multiple API types (OpenAI, Anthropic, Google), each with different base URLs, so the `endpoints` field is an array of API surface definitions.

```
{
  "version": "1.0",
  "providers": [
    {
      "id": "wisgate",
      "name": "Wisgate",
      "website": {
        "models_page": "https://wisgate.ai/models",
        "scraping_strategy": "firecrawl"
      },
      "endpoints": [
        {
          "type": "openai",
          "base_url": "https://api.wisgate.ai/v1",
          "models_endpoint": "/models",
          "auth": { "method": "bearer_token", "env_var": "WISGATE_API_KEY" }
        },
        {
          "type": "anthropic",
          "base_url": "https://api.wisgate.ai/v1",
          "messages_endpoint": "/messages",
          "auth": { "method": "bearer_token", "env_var": "WISGATE_API_KEY" },
          "notes": "Undocumented /v1/messages used by Claude Code integrations. Wire via ANTHROPIC_AUTH_TOKEN (Bearer), not x-api-key."
        },
        {
          "type": "google",
          "base_url": "https://api.wisgate.ai/v1beta",
          "generate_content_endpoint": "/models/{model}:generateContent",
          "auth": { "method": "bearer_token", "env_var": "WISGATE_API_KEY" }
        }
      ]
    },
    {
      "id": "openrouter",
      "name": "OpenRouter",
      "website": {
        "models_page": "https://openrouter.ai/models",
        "scraping_strategy": "none"
      },
      "endpoints": [
        {
          "type": "openai",
          "base_url": "https://openrouter.ai/api/v1",
          "models_endpoint": "/models",
          "auth": { "method": "bearer_token", "env_var": "OPENROUTER_API_KEY" }
        },
        {
          "type": "anthropic",
          "base_url": "https://openrouter.ai/api",
          "messages_endpoint": "/v1/messages",
          "auth": { "method": "bearer_token", "env_var": "OPENROUTER_API_KEY" },
          "notes": "Wire the Anthropic SDK via ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN. Native x-api-key is not accepted."
        }
      ]
    },
    {
      "id": "requesty",
      "name": "Requesty",
      "website": {
        "models_page": "https://requesty.ai/models",
        "scraping_strategy": "firecrawl"
      },
      "endpoints": [
        {
          "type": "openai",
          "base_url": "https://router.requesty.ai/v1",
          "models_endpoint": "/models",
          "auth": { "method": "bearer_token", "env_var": "REQUESTY_API_KEY" }
        },
        {
          "type": "anthropic",
          "base_url": "https://router.requesty.ai",
          "messages_endpoint": "/anthropic/v1/messages",
          "auth": { "method": "bearer_token", "env_var": "REQUESTY_API_KEY" },
          "notes": "Exposes ALL Requesty models (including OpenAI/Google/Mistral) through the Anthropic SDK surface. Wire via ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN."
        }
      ]
    },
    {
      "id": "cometapi",
      "name": "CometAPI",
      "website": {
        "models_page": "https://www.cometapi.com/models",
        "sample_model_url": "https://www.cometapi.com/models/anthropic/claude-opus-4-8",
        "scraping_strategy": "firecrawl"
      },
      "endpoints": [
        {
          "type": "openai",
          "base_url": "https://api.cometapi.com/v1",
          "models_endpoint": "/models",
          "auth": { "method": "bearer_token", "env_var": "COMET_API_KEY" }
        },
        {
          "type": "anthropic",
          "base_url": "https://api.cometapi.com/v1",
          "messages_endpoint": "/messages",
          "auth": { "method": "bearer_token", "env_var": "COMET_API_KEY" },
          "notes": "CometAPI accepts both x-api-key (native Anthropic) and Authorization: Bearer. Use ANTHROPIC_AUTH_TOKEN when wiring the SDK."
        },
        {
          "type": "google",
          "base_url": "https://api.cometapi.com/v1beta",
          "generate_content_endpoint": "/models/{model}:generateContent",
          "auth": { "method": "bearer_token", "env_var": "COMET_API_KEY" }
        }
      ]
    }
  ],
  "settings": {
    "max_concurrent_requests": 5,
    "request_timeout_seconds": 30,
    "retry_attempts": 3,
    "retry_backoff_factor": 2.0,
    "llm_cache_ttl_hours": 24,
    "backup_count": 5
  }
}
```

### 3.2 Configuration Schema

### Provider Object Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | string | ✅ | Unique provider identifier (kebab-case) |
| name | string | ✅ | Human-readable provider name |
| website.models_page | string (URL) | ✅ | URL of the page listing all models |
| website.sample_model_url | string (URL) | ❌ | URL for a specific model detail page. **[IMPL v1.3]** The current code does not infer URL patterns from this field; per-provider enrichment uses hard-coded/provider-specific URL logic pending the explicit URL-template fix tracked in #13. |
| website.scraping_strategy | enum | ✅ | "firecrawl", "playwright", "http", or "none". **Only "firecrawl" and "none" are currently dispatched by the code** (see `cli.py::_enrich_cometapi` and the wisgate fallback branch). The "playwright" and "http" values are reserved for future implementation. |
| website.selectors | object | ❌ | CSS/playwright selectors for structured scraping. **Currently a reserved field** — defined in the schema (`config/loader.py::WebsiteConfig.selectors`) but not read by any code path. Reserved for a future config-driven generic scraper. |
| endpoints | Endpoint[] | ✅ | One entry per API surface the provider exposes (openai/anthropic/google) |
| openclaw_provider_keys | — | — | **Removed in v1.3.** The key is now derived as `{provider_id}-{api_type_lowercased}` (e.g. `wisgate-anthropic`, `requesty-google`). Exception: the `cometapi` provider's openclaw key uses the `comet-` prefix to match OpenClaw's actual config convention. The internal `provider_id` stays `cometapi`. No per-provider configuration needed. |

### Endpoint Object Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| type | enum | ✅ | Wire/SDK style: `"openai"`, `"anthropic"`, or `"google"` |
| base_url | string (URL) | ✅ | API base URL (no trailing slash) |
| models_endpoint | string | ❌ | Path to `/models` listing endpoint. Set on the **discovery endpoint** only (typically the `openai` one). The other endpoints are recorded for downstream SDK wiring. |
| messages_endpoint | string | ❌ | Path to `/messages` (anthropic-style). |
| generate_content_endpoint | string | ❌ | Path to `/models/{model}:generateContent` (google-style). |
| auth.method | enum | ✅ | `"bearer_token"`, `"api_key_header"`, `"api_key_query"` |
| auth.env_var | string | ✅ | Environment variable holding the credential |
| auth.header_name | string | ❌ | Custom auth header name (default: `Authorization`) |
| auth.required | bool | ✅ (`true`) | Whether the discovery endpoint refuses unauthenticated requests. Set to `false` for providers whose `/v1/models` is public (OpenRouter and Requesty both serve 200 anonymously). When `false`, the env var may be unset and no `Authorization` header is sent. **Always verify by hand before declaring a provider public** — don't guess. |
| notes | string | ❌ | Free-form notes for documented quirks (e.g. `"Native x-api-key is not accepted; wire via ANTHROPIC_AUTH_TOKEN."`) |

A provider typically exposes 1–3 endpoint entries. The `openai` endpoint is universal. The `anthropic` and `google` endpoints are only declared if the provider actually serves them — a provider without a `google` entry cannot route models to a google-style wire, so Gemini models on that provider fall back to `openai`.

### Global Settings Schema

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| max_concurrent_requests | int | 5 | Maximum parallel requests across all providers |
| request_timeout_seconds | int | 30 | Timeout for HTTP requests |
| firecrawl_timeout_seconds | int \| null | null | Optional Firecrawl scrape API server-side timeout, expressed in seconds in config and forwarded as milliseconds in the Firecrawl `timeout` payload field. When set, the local `httpx` timeout gets a small buffer so it does not fire before Firecrawl's configured timeout. |
| retry_attempts | int | 3 | Number of retries on failure |
| retry_backoff_factor | float | 2.0 | Exponential backoff multiplier |
| llm_cache_ttl_hours | int | 24 | How long to cache LLM extraction results |
| backup_count | int | 5 | Number of MODELS.json backups to keep |

### Scraping Strategy Detail

| Strategy | Description | When to Use |
|----------|-------------|-------------|
| firecrawl | Use Firecrawl API to scrape JS-rendered pages, returning LLM-ready markdown | Best for JS-heavy pages; already configured in this workspace |
| playwright | Use Playwright (headless Chromium) for interactive scraping + screenshot comparison | **Reserved / not yet implemented** — Firecrawl is the only scraping path currently wired up |
| http | Simple HTTP GET + BeautifulSoup/parsing | Lightweight pages with no JS rendering needed |
| none | Skip website scraping entirely; rely solely on API queries | Provider has a complete /models endpoint |

Firecrawl timeout behaviour: when `settings.firecrawl_timeout_seconds` is set,
the Firecrawl client forwards it as the scrape API's `timeout` value in
milliseconds. If unset, the `timeout` key is omitted from the Firecrawl payload
and Firecrawl's service default applies. This setting is separate from the
generic HTTP request timeout.

Failed enrichment retry: enrichment failures are recorded in
`.cache/failed_enrichments.json` with a provider/model/url key, a failure
category, attempt counts, cooldown (`next_eligible_at`), and exhaustion state.
Categories are `no_sitemap_page`, `sitemap_url_404`, `scrape_transient`,
`scrape_permanent`, `parse_empty`, `parse_error`, and `unknown`. Later
successful enrichment clears matching failures. `retry-failed` retries
eligible unresolved failures; `--try-harder` uses twice the configured
Firecrawl timeout and `proxy: "auto"` for categories likely to benefit from a
stronger network path. Automatic end-of-run retry queues are out of scope.


## 4. Data Model

### 4.1 Common Schema (MODELS.json)

Each model entry in the output MODELS.json SHALL conform to this schema:

```
{
  // The model key is always prefixed with the provider ID.
  // It MUST be unique across all providers.  Format: "{provider}_{model_id}" — always prefixed, no collision logic
  // This ensures stable, predictable keys regardless of which providers are configured.

  "<model_key>": {
    "model_id": "string",          // Provider's native model identifier
    "provider": "string",          // Provider id from providers.json
    "display_name": "string",      // Optional human-friendly name
    "api_type": "string",          // "openai" | "anthropic" | "google" | "other"  (lowercase, v1.3)
    "openclaw_provider_key": "string",
    "context_window": "number",    // Total context window size
    "max_output_tokens": "number",  // Maximum tokens the model can generate
    "pricing": {
      "input_per_1m": "number",       // USD per 1M input tokens
      "output_per_1m": "number",      // USD per 1M output tokens
      "cache_read_per_1m": "number | null",  // USD per 1M cache-read tokens
      "cache_write_per_1m": "number | null", // USD per 1M cache-write tokens
      "image_input": "number | null",        // USD per image (if applicable)
      "audio_input_per_1m": "number | null"  // USD per 1M audio tokens
    },
    "capabilities": {              // Optional: what the model supports
      "vision": "boolean | null",
      "audio": "boolean | null",
      "tool_use": "boolean | null",
      "structured_output": "boolean | null",
      "streaming": "boolean | null",
      "thinking": "boolean | null"
    },
    "rate_limits": {               // Optional: RPM/TPM limits if known
      "requests_per_minute": "number | null",
      "tokens_per_minute": "number | null"
    },
    "available": "boolean",        // Currently listed/enabled by provider
    "deprecated": "boolean",       // Marked as deprecated/sunsetting
    "notes": "string | null",      // Free-form notes (quirks, observations)
    "last_updated": "string",      // ISO 8601 timestamp of when this entry was last refreshed
    "source": {                    // Provenance: where this data came from
      "url": "string | null",      // URL scraped or API endpoint queried
      "method": "string",          // "scrape" | "api" | "docs" | "manual"
      "scraped_at": "string"       // ISO 8601 timestamp
    }
  }
}
```

### 4.2 Field Derivation Rules

These rules define how to populate the common schema from heterogeneous provider data:

| Field | Priority Sources |
|-------|------------------|
| model_id | API response > website scrape > docs |
| context_window | API response (context_length) > website > docs > manual (ask) |
| pricing.* | Website pricing table > API response > docs |
| api_type | Each model uses one preferred API. Derive from: API response metadata, model name patterns (claude-* = Anthropic, gpt-* = OpenAI), or provider docs. Track only the first/preferred API. |
| capabilities | API response (capabilities, modalities) > docs |
| max_output_tokens | API response (max_tokens, max_completion_tokens) > docs |
| available | true if model appears in current scrape/API response; false if previously seen but now absent (soft-delete) |

### 4.3 Handling Conflicts

When a model exists in the current MODELS.json and new data is scraped:

New fields: Add without removing existing data (merge)

Conflicting fields: Overwrite with new data; take data as it comes with no priority ordering

Missing models: Mark available: false and add notes: "No longer listed by provider as of {date}"

New models: Add with all available fields; leave unknown fields as null

Post-update quality check: compare two concrete MODELS.json snapshots with
`scripts/check_diff.py` to warn about large provider count drops, field-coverage
drops, and missing or newly unavailable model IDs. This check is deliberately
outside the default update path. It detects suspicious output changes, but it
does not fully detect fresh enrichment failures hidden by merge preservation
when the final output retains old non-null values.


## 5. Scraping & Discovery Flows

**Architecture: API-first, scrape-to-fill-gaps.** The default discovery strategy is to query provider APIs (Section 5.2) first, as APIs return structured, versioned data. Website scraping (Section 5.1) is used as a fallback only for fields the API does not expose (e.g. per-model API type, cache pricing, or when the API is unavailable).

> **[IMPL]** The orchestrator calls API Query first, then invokes Website Scraper only for gaps. API-first is mandatory - scraping is never the primary path.

### 5.1 Website Scraping

For each provider with scraping_strategy != "none":

> **[IMPL v1.3]** Tier 2 (LLM fallback) and Tier 3 (verification mode) are **not yet implemented**. The current data path is fully deterministic: API endpoints + regex/table parsing of scraped markdown. Coverage gaps (e.g., CometAPI's API models without marketing pages) are an accepted limitation, not an LLM-fallback trigger.

Load the models page using the configured strategy

Extract structured data:

Tier 1: Deterministic — use CSS/Playwright selectors or regex patterns hard-coded per provider

Tier 2: LLM fallback — if Tier 1 returns less than 50 percent of expected fields, use LLM to parse against target schema

For each model entry found, attempt to follow the detail page URL if available (for additional metadata)

Normalise extracted fields to the common schema

Flag uncertainties: If a value is ambiguous (e.g., multiple prices listed), mark it and log the ambiguity

Tier 3: Verification mode (optional) — After deterministic extraction, sample 3 random models and use LLM to parse their detail pages; compare results and log discrepancies if found

LLM Configuration (for Tiers 2 and 3):
- Provider: Requesty (OpenAI-compatible)
- Model: deepseek/deepseek-v4-pro
- API key: REQUESTY_API_KEY environment variable

> **[IMPL v1.3]** The `discovery/llm/` package and `llm_cache` are reserved directory stubs pending future work.

### 5.1.1 LLM Extraction Caching

Cache LLM-parsed results to avoid redundant API calls and reduce costs:

```
Cache key: sha256(source_url + content_hash)[:16]
Storage:  SQLite table or JSON file
TTL:      24 hours (configurable via llm_cache_ttl_hours)
Invalidation: Manual --force flag or cache age > TTL
```

The cache stores:
- Source URL
- Content hash (SHA256 of page content)
- Parsed result (JSON)
- Timestamp

On cache hit: return cached result

On cache miss: call LLM, store result, return

### 5.2 API Model Discovery

For each provider with api.models_endpoint configured:

Call the models endpoint with appropriate authentication

Parse the response:

OpenAI-compatible: GET /v1/models → { data: [ { id, owned_by, ... } ] }

Anthropic: Not all providers expose this natively; map via the overlay API

Google: GET /v1beta/models (if GenAI-compatible)

Cross-reference with scraped website data to fill gaps

Query model-specific endpoints if available (e.g. GET /v1/models/{model_id})

### 5.3 API Documentation Parsing

For each provider:

Identify the documentation URL (from providers.json or auto-discovered)

Scrape the API reference pages for:

Base URL

Authentication scheme

Available endpoints (especially models-related)

Rate limits

Validate discovered endpoints with a test request where possible

Update providers.json with discovered API details (self-improving config)

### 5.4 Model Detail Enrichment (Optional)

If a provider exposes per-model detail pages or API endpoints:

Construct model detail URLs using a configured provider URL pattern or provider-specific API convention.

> **[IMPL v1.3]** `sample_model_url` is currently documentation/config context only; the CLI does not infer URL patterns from concrete sample URLs. See #13 for the code fix to use an explicit URL template/strategy.

Scrape/query each model individually for deep metadata:

Full capabilities list

Rate limits

Deprecation notices

Fine-tuning availability

Modality support


## 6. Output

### 6.1 Primary Output: MODELS.json

Written to a configurable output path (default: ./MODELS.json). This is the authoritative machine-readable database.

> **[IMPL]** MODELS.json is also the canonical state store - read it as input for merge logic (Section 4.3) and soft-delete detection (available:false).

File structure: A single JSON object where keys are model identifiers and values are model entry objects as defined in §4.1.

Update behaviour:

Full refresh (default): Replace the entire file with fresh data

Incremental update (flag): Only update models from specified providers, merge with existing data for other providers

### 6.2 Companion Output: MODELS.md

A human-readable Markdown companion generated from MODELS.json. Grouped by provider, with tables per model.

Format:

```
# MODELS.md — LLM Models Registry

*Last updated: 2026-06-15T12:00:00Z*

## Wisgate (88 models)

| Model ID | API Type | Context | Max Output | Input $/1M | Output $/1M | Cache Read | Cache Write |
|----------|----------|---------|------------|------------|-------------|------------|-------------|
| MiniMax-M2.7 | openai | 200K | 131K | $0.30 | $1.20 | $0.30 | $0.30 |

```

## 7. Change Detection

Before overwriting MODELS.json:

Generate a candidate file

Diff against current MODELS.json

Report the diff in console output. **[IMPL v1.3]** A persistent changelog file is deferred; the diff is only printed to stdout. See §9.3 for the deferred-modules list.

Optionally notify (console output, OpenClaw message, or file) about significant changes (price changes > threshold, new models, deprecated models)


## 8. CLI Interface

```
# Full update across all providers

models-registry update

# Update specific providers

models-registry update --provider wisgate --provider openrouter

# Force full re-scrape (ignore cache)

models-registry update --force

# Retry unresolved failed enrichment records

models-registry retry-failed
models-registry retry-failed --provider cometapi
models-registry retry-failed --try-harder   # 2x Firecrawl timeout + proxy:auto
models-registry retry-failed --force        # ignore retry cooldowns/exhaustion

# Update only one provider; other providers' data is preserved as-is (incremental update)

models-registry update --provider requesty

# Dry run: scrape but don't write output

models-registry update --dry-run

# Validate current MODELS.json against schema

models-registry validate

# List configured providers

models-registry providers

# Generate MODELS.md from existing MODELS.json

models-registry generate-md

# Show diff between current MODELS.json and what a refresh would produce

models-registry diff --provider wisgate   # ⚠ stub — prints "Not yet implemented"

# Clear LLM extraction cache

models-registry cache-clear   # ⚠ stub — prints "Not yet implemented"

# Set max concurrent requests (default: 5)

models-registry update --parallel 3


```

## 9. Error Handling & Resilience

### 9.1 Failure Modes

| Failure | Behaviour |
| --- | --- |
| Provider website unreachable | 	Log error, skip provider, continue with others |
| API auth failure | 	Log error with provider name, skip API discovery for that provider |
| Data extraction fails (no models found) | 	Log warning, keep existing data for that provider, do not overwrite with empty |
| Schema validation failure on scraped data | 	Log validation errors per model, still write valid models |
| Rate limiting from provider | 	Exponential backoff with jitter; respect Retry-After headers |

### 9.2 Circuit Breaker

> **[IMPL v1.3]** Deferred. The current implementation logs provider failures during a run but does not persist circuit-breaker state.

For providers that repeatedly fail:

- After 3 consecutive failures: mark provider as "unhealthy"
- Circuit opens: skip provider for 5 minutes
- After timeout: allow single test request
- If test succeeds: close circuit, resume normal operation
- Log all state transitions (open/closed/half-open)

### 9.3 Data Integrity

Never delete the existing MODELS.json before having a valid replacement

Atomic writes: Write to a temp file, validate it, then os.replace() into place

Keep backups: Rotate last N versions (default: 5)

Changelog: Deferred; no `models_changelog.jsonl` file is written in v1.3.


## 10. Dependencies

### 10.1 Python Packages

pydantic>=2.0

httpx>=0.27

playwright>=1.45      # For JS-heavy scraping — **listed for future use, not currently imported**

python-dotenv>=1.0    # Environment variable management

rich>=13.0            # Beautiful CLI output

aiofiles>=23.0        # Async file I/O — **listed for future use, not currently imported** (file writes are sync via `orjson`)

orjson>=3.9           # Fast JSON serialization

### 10.2 External Services

| Service | Purpose | Required for `--enrich`? | Required for plain `update`? | Credential |
|---------|---------|--------------------------|------------------------------|------------|
| Firecrawl API | JS-heavy page scraping | ✅ | ❌ | FIRECRAWL_API_KEY env var |
| Wisgate API | Model listing via API | n/a | ✅ (returns 401 without a key) | WISGATE_API_KEY env var |
| OpenRouter API | Model listing via API | n/a | ❌ (discovery endpoint is public) | OPENROUTER_API_KEY env var |
| Requesty API (model listing) | Model listing via API | n/a | ❌ (discovery endpoint is public) | REQUESTY_API_KEY env var |
| Requesty API (LLM fallback) | LLM-based page parsing (deepseek-v4-pro) | n/a (Tier 2 deferred) | n/a | REQUESTY_API_KEY env var |
| CometAPI | Model listing via API | n/a | ✅ (returns 401 without a key) | COMET_API_KEY env var |

> **Concretely:** a `python -m llm_registry update` run needs only
> `WISGATE_API_KEY`, `COMET_API_KEY`, and `FIRECRAWL_API_KEY` (the last
> only if you pass `--enrich`). `OPENROUTER_API_KEY` and `REQUESTY_API_KEY`
> are optional — both providers serve 200 anonymously. The behaviour is
> controlled by `auth.required` in `providers.json` (default `true`).


## 11. Roadmap / Phases

### Phase 1 — Core (MVP)

Specification document (this file)

providers.json config loader with validation

Wisgate website scraper (Firecrawl + selectors)

Data normaliser with Pydantic schema

MODELS.json output writer

CLI: update, validate

### Phase 2 — Multi-Provider

OpenRouter scraper

Requesty scraper

API model discovery (OpenAI-compatible /models endpoint)

Incremental merge mode

MODELS.md generator

LLM extraction cache

### Phase 3 — Automation

Change detection and diff logging

Provider self-healing (API endpoint discovery from docs)

Per-model detail enrichment

Circuit breaker for failing providers

### Phase 4 — Polish

Changelog viewer

Price change alerts (threshold-based)

Web dashboard (optional)

OpenClaw integration (notifications via message)


## 12. Resolved Decisions

The following questions have been answered and are implemented in this specification:

- LLM usage: **Deferred** (v1.3). The runtime LLM fallback (Requesty/deepseek-v4-pro) is reserved for future work. Current implementation is fully deterministic — see [IMPL v1.3] note in §5.1.
- LLM caching: **Deferred** (v1.3). Cache layer to be added when LLM extractor lands.
- Authentication rotation: API keys do not expire / do not rotate
- Soft-delete policy: Models marked available:false are retained forever
- Multi-region pricing: Capture default/US pricing only
- Model aliases: Use the provider's canonical model name
- Max parallel requests: 5 concurrent (configurable via settings)
- Source confidence ranking: None — take data as it comes, no priority ordering
- Change detection threshold: 10% price change triggers notification
- Async execution: asyncio + httpx async throughout
- State persistence: **JSON only (no SQLite yet)**. Deferred modules: a future LLM-extraction cache, a circuit breaker, and a SQLite state layer are listed in `IMPLEMENTATION_PLAN.md` but not built. The currently-shipped Firecrawl cache lives at `src/llm_registry/discovery/scraping/cache.py` and the runtime ledger at `.cache/firecrawl_scrape_cache.json` (gitignored). Failed enrichment state lives in `.cache/failed_enrichments.json` and is operational state, not canonical model data. Output format and intermediate state both live in MODELS.json.
- Parser threshold: 90% field coverage for 90% of models gates custom code
- Current coverage by provider (v1.3): Wisgate 99/99, OpenRouter 333/337, CometAPI 109/578 (sitemap-gated), Requesty 512/512


## 13. Implementation Approach

The tool SHALL be organised as a Python package with clear separation between configuration, discovery, normalisation, and output concerns:

```
llm-models-registry/
├── pyproject.toml
├── README.md
├── providers.json
├── MODELS.json
├── MODELS.md
├── .env
├── src/llm_registry/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config/ (loader.py)             # providers.json loader + Pydantic models
│   ├── schema/ (model_entry.py)        # ModelEntry, Pricing, Capabilities
│   ├── discovery/
│   │   ├── api/
│   │   │   ├── openai.py              # OpenAI-compatible /v1/models client
│   │   │   ├── requesty.py            # Custom Requesty /v1/models client
│   │   │   └── _keys.py               # openclaw_provider_key() helper
│   │   └── scraping/
│   │       ├── firecrawl.py           # Firecrawl API client
│   │       ├── http.py                # Simple HTTP + BeautifulSoup (reserved, not yet used)
│   │       ├── cache.py               # Per-URL scrape cache + retry
│   │       └── failures.py            # Failed enrichment ledger + retry eligibility
│   ├── normalise/
│   │   ├── normaliser.py              # Generic helpers (parse_price, etc.)
│   │   └── cometapi.py                # CometAPI sitemap + detail page → ModelEntry
│   └── output/ (writer.py)            # JSON + Markdown writers
└── tests/
    ├── fixtures/ (cometapi_*.md)      # golden fixtures (real scraped pages)
    ├── discovery/scraping/ (test_cache.py)
    └── normalise/ (test_cometapi.py)
```

> **[IMPL]** The `discovery/` layer is organised by mechanism (API type, scraping strategy). The `normalise/` layer is organised by provider so provider-specific quirks are isolated. The current `cometapi.py` normaliser is the only provider-specific one — the wisgate path uses inline `normalize_wisgate_markdown(...)` called from `cli.py`.
>
> **Deferred directories** (planned but not built): `discovery/llm/` for the LLM extractor, `cache/` for the LLM cache, `resilience/` for the circuit breaker. See `CONTRIBUTING.md` "What NOT to do" for the list of things that should not be reintroduced.

### 13.2 Per-Provider Normaliser Module Design

When a provider's detail pages need custom parsing beyond the inline `normalize_*_markdown(...)` pattern, it gets a dedicated module under `normalise/`. Today the only example is `normalise/cometapi.py`, which exposes `parse_cometapi_detail_page(markdown, model_id, provider_id) -> Optional[ModelEntry]` plus helpers for sitemap URL discovery and slug matching. The interface contract is documented in `CONTRIBUTING.md` §3.

> **[IMPL]** There is no `parsers/` layer and no `GenericProviderParser` — that was an earlier aspirational design. Simple providers with an OpenAI-compatible `/v1/models` endpoint need zero code; only shape-mismatched APIs or unique page formats require new modules.

### 13.3 Golden Fixture / Test Strategy

Network-dependent scraping and API calls are non-deterministic, so tests run against captured fixtures by default.

- **Fixture capture:** Real pages are saved from `.cache/firecrawl_scrape_cache.json` (the runtime scrape ledger, gitignored) into `tests/fixtures/cometapi_*.md`. There is no `--capture` CLI mode — see `CONTRIBUTING.md` §4 for the manual recipe.
- **Golden outputs:** expected_output.json holds normalised ModelEntry records
- **Test layers:** Unit (no network), Parser/golden (no network), Integration/live (opt-in)

### 13.4 Development Workflow: Adding a New Provider

The detailed 5-step recipe — providers.json templates for the three discovery
cases, custom-client interfaces, normaliser patterns, fixture workflow, gotchas,
and the list of what's deliberately deferred — lives in `CONTRIBUTING.md` at
the repo root. Read it first when adding a new provider; this section is just
a pointer.


---

## Appendix A: Provider Website Analysis

## A.1 Wisgate (https://wisgate.ai/pricing)

Type: JS-heavy single-page pricing table

Content: Model name, context window, input price, output price per 1M tokens

Extraction strategy: Firecrawl scrape → LLM parse markdown table → structured data

Missing from website: API type per model (OpenAI vs Anthropic vs Google), max output tokens, cache pricing

API endpoint: https://api.wisgate.ai/v1/models (OpenAI-compatible, requires key)

### A.2 OpenRouter (https://openrouter.ai/models)

Type: JS-heavy interactive model browser with filters

Content: Model name, provider, context length, prompt price, completion price, capabilities tags

API endpoint: https://openrouter.ai/api/v1/models (returns full model list with pricing)

Advantage: The API returns richer data than the website — API-first approach recommended

### A.3 Requesty (https://requesty.ai/models)

Type: JS-rendered model listing

Content: Model names, pricing tiers

API endpoint: https://router.requesty.ai/v1/models (custom JSON format — NOT OpenAI-compatible; prices in $/token at top level, plus capability flags)

Note: v1.3 — uses a dedicated `RequestyModelsClient` (not the OpenAI-compatible path). 512 models exposed, 506 with pricing.

## A.4 CometAPI (https://www.cometapi.com/models/)

Type: Static model listing page

Content: Model name, provider (Anthropic/OpenAI/Google), context window, input/output pricing

API endpoint: https://api.cometapi.com/v1/models (OpenAI-compatible, requires key)

Note: Comprehensive model catalogue; API returns pricing and context length data



## Appendix B: Example Model Entry (Target Format)

```
{
  "wisgate_deepseek-v4-pro": {
    "model_id": "deepseek-v4-pro",
    "provider": "wisgate",
    "display_name": "DeepSeek V4 Pro",
    "api_type": "openai",
    "openclaw_provider_key": "wisgate-openai",
    "context_window": 200000,
    "max_output_tokens": 32000,
    "pricing": {
      "input_per_1m": 2.0,
      "output_per_1m": 8.0,
      "cache_read_per_1m": 0.20,
      "cache_write_per_1m": 2.50,
      "image_input": null,
      "audio_input_per_1m": null
    },
    "capabilities": {
      "vision": false,
      "audio": false,
      "tool_use": true,
      "structured_output": true,
      "streaming": true,
      "thinking": true
    },
    "rate_limits": {
      "requests_per_minute": null,
      "tokens_per_minute": null
    },
    "available": true,
    "deprecated": false,
    "notes": null,
    "last_updated": "2026-06-15T11:00:00Z",
    "source": {
      "url": "https://wisgate.ai/pricing",
      "method": "scrape",
      "scraped_at": "2026-06-15T12:00:00Z"
    }
  }
}
```

## Document Version History

* v1.3 changes from v1.2: 
  - Requesty base URL corrected to `https://router.requesty.ai/v1`. Requesty moved to a dedicated API client (not OpenAI-compatible). LLM extractor marked as future work — current implementation is fully deterministic (regex/table parsing). Coverage notes added for CometAPI (sitemap-gated). `openclaw_provider_keys` removed from `providers.json` — the `openclaw_provider_key` field on each model entry is now derived uniformly as `{provider_id}-{api_type_lowercased}` (e.g. `wisgate-anthropic`, `requesty-google`).
  - **Schema refactor:** the per-provider `api` block + `api_types` array were replaced by a single `endpoints: [...]` array. Each entry is one real API surface the provider exposes (e.g. one `openai` for OpenAI-compatible, one `anthropic` for Anthropic-Messages-shaped, one `google` for GenAI-shaped), each with its own `base_url` and `auth`. The discovery endpoint is the one with `models_endpoint` set (typically the `openai` one). `api_type` values on model entries are now lowercase: `openai` / `anthropic` / `google`.

End of specification.
