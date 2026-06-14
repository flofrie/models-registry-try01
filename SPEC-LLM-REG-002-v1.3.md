LLM Models Registry — Software Specification
Document ID: SPEC-LLM-REG-002
Version: 1.3
Date: 2026-06-14
Author: Florian Friedrich
Status: Active

> v1.3 changes from v1.2: Requesty base URL corrected to `https://router.requesty.ai/v1`. Requesty moved to a dedicated API client (not OpenAI-compatible). LLM extractor marked as future work — current implementation is fully deterministic (regex/table parsing). Coverage notes added for CometAPI (sitemap-gated). `openclaw_provider_keys` removed from `providers.json` — the `openclaw_provider_key` field on each model entry is now derived uniformly as `{provider_id}-{api_type_lowercased}` (e.g. `wisgate-anthropic`, `requesty-google`).


1. Overview
1.1 Purpose
The LLM Models Registry is a software tool that maintains an up-to-date, machine-readable database of available large language models (LLMs) across multiple API providers. It mirrors and extends the existing MODELS.json file currently populated for Wisgate, and generalises the process to any number of configurable providers.
1.2 Scope
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

> **[IMPL]** Simple providers need zero code - just config. Use GenericProviderParser for providers that can be driven entirely by providers.json fields (selectors, API type).


2. System Architecture
2.1 High-Level Flow


┌─────────────────────────────────────────────────────┐

│                  Provider Config                     │

│  (JSON: URLs, API types, scraping strategy, auth)    │

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
2.2 Components
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
| Headless browser | Playwright (via playwright-python) | Best JS-rendering support; async; can also use persistent browser profiles |
| Scraping fallback | Firecrawl API | Already configured (API key in TOOLS.md); handles JS rendering as a service |
| Data validation | Pydantic v2 | Schema enforcement, type coercion, validation |
| HTTP client | httpx | Async, HTTP/2, connection pooling |
| Local state | SQLite (internal) + JSON (output) | Zero-dep DB for state; JSON for interchange |
| Output format | JSON (primary) + Markdown (companion) | Machine-readable primary; human-readable secondary |


3. Configuration
3.1 Provider Configuration File (providers.json)
This is the central configuration file. Each provider entry specifies how to discover its models.

This is an example, and the actual initial providers.json file should be created and populated as part of the tool design process.

NOTE: The example below shows a simplified single-API structure. Providers like Wisgate expose multiple API types (OpenAI, Anthropic, Google), each with different base URLs. The  field should be an array to support multiple APIs per provider, e.g.: . The initial providers.json will be created and fully populated as part of the tool design/implementation process.

{

  "version": "1.0",

  "providers": [

    {

      "id": "wisgate",

      "name": "Wisgate",

      "website": {

        "models_page": "https://wisgate.ai/pricing",

        "sample_model_url": null,

        "scraping_strategy": "firecrawl",

        "selectors": {

          "model_table": "table.pricing-table",

          "model_name": "td.model-name",

          "pricing_cols": ["td.price-input", "td.price-output"]

        }

      },

      "api": {

        "type": "openai",

        "base_url": "https://api.wisgate.ai/v1",

        "models_endpoint": "/models",

        "auth": {

          "method": "bearer_token",

          "env_var": "WISGATE_API_KEY"

        }

      },

      "api_types": ["OpenAI", "Anthropic", "Google"]

    },

    {

      "id": "openrouter",

      "name": "OpenRouter",

      "website": {

        "models_page": "https://openrouter.ai/models",

        "sample_model_url": "https://openrouter.ai/openrouter/auto",

        "scraping_strategy": "playwright",

        "selectors": null

      },

      "api": {

        "type": "openai",

        "base_url": "https://openrouter.ai/api/v1",

        "models_endpoint": "/models",

        "auth": {

          "method": "bearer_token",

          "env_var": "OPENROUTER_API_KEY"

        }

      },

      "api_types": ["OpenAI"]

    },

    {

      "id": "requesty",

      "name": "Requesty",

      "website": {

        "models_page": "https://requesty.ai/models",

        "sample_model_url": null,

        "scraping_strategy": "firecrawl",

        "selectors": null

      },

      "api": {

        "type": "requesty",

        "base_url": "https://router.requesty.ai/v1",

        "models_endpoint": "/models",

        "auth": {

          "method": "bearer_token",

          "env_var": "REQUESTY_API_KEY"

        }

      },

      "api_types": ["OpenAI"]

    },

    {

      "id": "cometapi",

      "name": "CometAPI",

      "website": {

        "models_page": "https://www.cometapi.com/models/",

        "sample_model_url": "https://www.cometapi.com/models/anthropic/claude-opus-4-8/",

        "scraping_strategy": "http",

        "selectors": null

      },

      "api": {

        "type": "openai",

        "base_url": "https://api.cometapi.com/v1",

        "models_endpoint": "/models",

        "auth": {

          "method": "bearer_token",

          "env_var": "COMET_API_KEY"

        }

      },

      "api_types": ["OpenAI", "Anthropic", "Google"]

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
3.2 Configuration Schema
### Provider Object Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | string | ✅ | Unique provider identifier (kebab-case) |
| name | string | ✅ | Human-readable provider name |
| website.models_page | string (URL) | ✅ | URL of the page listing all models |
| website.sample_model_url | string (URL) | ❌ | URL for a specific model detail page (used to infer URL pattern) |
| website.scraping_strategy | enum | ✅ | "firecrawl", "playwright", "http", or "none" |
| website.selectors | object | ❌ | CSS/playwright selectors for structured scraping (null = use AI extraction) |
| api.type | enum | ❌ | API compatibility type: "openai", "anthropic", "google" |
| api.base_url | string (URL) | ❌ | API base URL |
| api.models_endpoint | string | ❌ | Path to the models listing endpoint (relative to base_url) |
| api.auth.method | enum | ❌ | "bearer_token", "api_key_header", "api_key_query" |
| api.auth.env_var | string | ❌ | Environment variable holding the credential |
| api.auth.header_name | string | ❌ | Custom auth header name (default: Authorization) |
| api_types | string[] | ✅ | API standards this provider exposes (e.g. ["OpenAI", "Anthropic"]) |
| openclaw_provider_keys | — | — | **Removed in v1.3.** The key is now derived as `{provider_id}-{api_type_lowercased}` (e.g. `wisgate-anthropic`, `requesty-google`). No per-provider configuration needed. |

### Global Settings Schema

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| max_concurrent_requests | int | 5 | Maximum parallel requests across all providers |
| request_timeout_seconds | int | 30 | Timeout for HTTP requests |
| retry_attempts | int | 3 | Number of retries on failure |
| retry_backoff_factor | float | 2.0 | Exponential backoff multiplier |
| llm_cache_ttl_hours | int | 24 | How long to cache LLM extraction results |
| backup_count | int | 5 | Number of MODELS.json backups to keep |

### Scraping Strategy Detail

| Strategy | Description | When to Use |
|----------|-------------|-------------|
| firecrawl | Use Firecrawl API to scrape JS-rendered pages, returning LLM-ready markdown | Best for JS-heavy pages; already configured in this workspace |
| playwright | Use Playwright (headless Chromium) for interactive scraping + screenshot comparison | When selectors are complex or pages require interaction |
| http | Simple HTTP GET + BeautifulSoup/parsing | Lightweight pages with no JS rendering needed |
| none | Skip website scraping entirely; rely solely on API queries | Provider has a complete /models endpoint |


4. Data Model
4.1 Common Schema (MODELS.json)
Each model entry in the output MODELS.json SHALL conform to this schema:

{

  // The model key is always prefixed with the provider ID.

  // It MUST be unique across all providers.  Format: "{provider}_{model_id}" — always prefixed, no collision logic

  // This ensures stable, predictable keys regardless of which providers are configured.

  "<model_key>": {

    "model_id": "string",          // Provider's native model identifier

    "provider": "string",          // Provider id from providers.json

    "display_name": "string",      // Optional human-friendly name

    "api_type": "string",          // "OpenAI" | "Anthropic" | "Google" | "Other"

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


5. Scraping & Discovery Flows

**Architecture: API-first, scrape-to-fill-gaps.** The default discovery strategy is to query provider APIs (Section 5.2) first, as APIs return structured, versioned data. Website scraping (Section 5.1) is used as a fallback only for fields the API does not expose (e.g. per-model API type, cache pricing, or when the API is unavailable).

> **[IMPL]** The orchestrator calls API Query first, then invokes Website Scraper only for gaps. API-first is mandatory - scraping is never the primary path.
5.1 Website Scraping
For each provider with scraping_strategy != "none":

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

> **[IMPL v1.3]** Tier 2 (LLM fallback) and Tier 3 (verification mode) are **not yet implemented**. The current data path is fully deterministic: API endpoints + regex/table parsing of scraped markdown. Coverage gaps (e.g. CometAPI's 578 API models but only ~150 with marketing pages) are an accepted limitation, not an LLM-fallback trigger. The `discovery/llm/` package and `llm_cache` are reserved directory stubs pending future work.

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
5.2 API Model Discovery
For each provider with api.models_endpoint configured:

Call the models endpoint with appropriate authentication
Parse the response:
OpenAI-compatible: GET /v1/models → { data: [ { id, owned_by, ... } ] }
Anthropic: Not all providers expose this natively; map via the overlay API
Google: GET /v1beta/models (if GenAI-compatible)
Cross-reference with scraped website data to fill gaps
Query model-specific endpoints if available (e.g. GET /v1/models/{model_id})
5.3 API Documentation Parsing
For each provider:

Identify the documentation URL (from providers.json or auto-discovered)
Scrape the API reference pages for:
Base URL
Authentication scheme
Available endpoints (especially models-related)
Rate limits
Validate discovered endpoints with a test request where possible
Update providers.json with discovered API details (self-improving config)
5.4 Model Detail Enrichment (Optional)
If a provider exposes per-model detail pages or API endpoints:

Construct model detail URLs using the pattern from sample_model_url or API convention
Scrape/query each model individually for deep metadata:
Full capabilities list
Rate limits
Deprecation notices
Fine-tuning availability
Modality support


6. Output
6.1 Primary Output: MODELS.json
Written to a configurable output path (default: ./MODELS.json). This is the authoritative machine-readable database.

> **[IMPL]** MODELS.json is also the canonical state store - read it as input for merge logic (Section 4.3) and soft-delete detection (available:false).

File structure: A single JSON object where keys are model identifiers and values are model entry objects as defined in §4.1.

Update behaviour:

Full refresh (default): Replace the entire file with fresh data
Incremental update (flag): Only update models from specified providers, merge with existing data for other providers
6.2 Companion Output: MODELS.md
A human-readable Markdown companion generated from MODELS.json. Grouped by provider, with tables per model.

Format:

# MODELS.md — LLM Models Registry

*Last updated: 2026-06-13T12:00:00Z*

## Wisgate (88 models)

| Model ID | API Type | Context | Max Output | Input $/1M | Output $/1M | Cache Read | Cache Write |

|----------|----------|---------|------------|------------|-------------|------------|-------------|

| MiniMax-M2.7 | OpenAI | 200K | 131K | $0.30 | $1.20 | $0.30 | $0.30 |


7. Change Detection
Before overwriting MODELS.json:

Generate a candidate file
Diff against current MODELS.json
Log the diff to a changelog (models_changelog.jsonl)
Optionally notify (console output, OpenClaw message, or file) about significant changes (price changes > threshold, new models, deprecated models)


8. CLI Interface
# Full update across all providers

models-registry update

# Update specific providers

models-registry update --provider wisgate --provider openrouter

# Force full re-scrape (ignore cache)

models-registry update --force

# Incremental: only update one provider, merge with existing

models-registry update --provider requesty --merge

# Dry run: scrape but don't write output

models-registry update --dry-run

# Validate current MODELS.json against schema

models-registry validate

# List configured providers

models-registry providers

# Generate MODELS.md from existing MODELS.json

models-registry generate-md

# Show diff between current MODELS.json and what a refresh would produce

models-registry diff --provider wisgate

# Show changelog of historical updates

models-registry changelog

# Clear LLM extraction cache

models-registry cache clear

# Set max concurrent requests (default: 5)

models-registry update --parallel 3


9. Error Handling & Resilience
9.1 Failure Modes
Failure
	Behaviour

Provider website unreachable
	Log error, skip provider, continue with others

API auth failure
	Log error with provider name, skip API discovery for that provider

Data extraction fails (no models found)
	Log warning, keep existing data for that provider, do not overwrite with empty

Schema validation failure on scraped data
	Log validation errors per model, still write valid models

Rate limiting from provider
	Exponential backoff with jitter; respect Retry-After headers
9.2 Circuit Breaker
For providers that repeatedly fail:

- After 3 consecutive failures: mark provider as "unhealthy"
- Circuit opens: skip provider for 5 minutes
- After timeout: allow single test request
- If test succeeds: close circuit, resume normal operation
- Log all state transitions (open/closed/half-open)
9.3 Data Integrity
Never delete the existing MODELS.json before having a valid replacement
Atomic writes: Write to a temp file, validate it, then os.replace() into place
Keep backups: Rotate last N versions (default: 5)
Changelog: Append every change to models_changelog.jsonl with timestamp and diff


10. Dependencies
10.1 Python Packages
pydantic>=2.0

httpx>=0.27

playwright>=1.45      # For JS-heavy scraping

python-dotenv>=1.0    # Environment variable management

rich>=13.0            # Beautiful CLI output

aiofiles>=23.0        # Async file I/O

orjson>=3.9           # Fast JSON serialization
### 10.2 External Services

| Service | Purpose | Credential |
|---------|---------|------------|
| Firecrawl API | JS-heavy page scraping (already configured) | FIRECRAWL_API_KEY env var |
| Wisgate API | Model listing via API | WISGATE_API_KEY env var |
| OpenRouter API | Model listing via API | OPENROUTER_API_KEY env var |
| Requesty API (model listing) | Model listing via API | REQUESTY_API_KEY env var |
| Requesty API (LLM fallback) | LLM-based page parsing (deepseek-v4-pro) | REQUESTY_API_KEY env var |
| CometAPI | Model listing via API | COMET_API_KEY env var |


## 11. Roadmap / Phases
Phase 1 — Core (MVP)
Specification document (this file)
providers.json config loader with validation
Wisgate website scraper (Firecrawl + selectors)
Data normaliser with Pydantic schema
MODELS.json output writer
CLI: update, validate
Phase 2 — Multi-Provider
OpenRouter scraper
Requesty scraper
API model discovery (OpenAI-compatible /models endpoint)
Incremental merge mode
MODELS.md generator
LLM extraction cache
Phase 3 — Automation
Change detection and diff logging
Provider self-healing (API endpoint discovery from docs)
Per-model detail enrichment
Circuit breaker for failing providers
Phase 4 — Polish
Changelog viewer
Price change alerts (threshold-based)
Web dashboard (optional)
OpenClaw integration (notifications via message)


12. Resolved Decisions

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
- State persistence: **JSON only (no SQLite yet)**. The `cache/` and `resilience/` modules are reserved for future work but currently empty. Output format and intermediate state both live in MODELS.json.
- Parser threshold: 90% field coverage for 90% of models gates custom code
- Current coverage by provider (v1.3): Wisgate 99/99, OpenRouter 333/337, CometAPI 109/578 (sitemap-gated), Requesty 512/512


13. Implementation Approach

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
│   ├── cli.py
│   ├── config/ (loader.py, models.py)
│   ├── schema/ (model_entry.py, enums.py)
│   ├── discovery/
│   │   ├── api/ (base.py, openai.py, anthropic.py, google.py)
│   │   ├── scraping/ (base.py, firecrawl.py, playwright.py, http.py)
│   │   └── llm/ (extractor.py)
│   ├── cache/ (llm_cache.py)
│   ├── resilience/ (circuit_breaker.py)
│   ├── parsers/ (base.py, wisgate.py, openrouter.py, cometapi.py, requesty.py)
│   ├── normalise/ (normaliser.py, merge.py, dedup.py)
│   └── output/ (json_writer.py, markdown_writer.py)
└── tests/
    ├── fixtures/ (golden fixtures per provider)
    ├── unit/
    └── integration/
```

> **[IMPL]** The discovery/ layer is organised by mechanism (API type, scraping strategy). The parsers/ layer is organised by provider so provider-specific quirks are isolated.

### 13.2 Per-Provider Parser Module Design

Each provider gets a dedicated module under parsers/ implementing a common interface. Providers without a custom class fall back to a GenericProviderParser that uses only config-driven behaviour.

> **[IMPL]** A ParserRegistry maps provider_id to ParserClass. Simple providers need zero code - just config. Custom parser needed only if generic approach yields <90% field coverage for >90% of models.

### 13.3 Golden Fixture / Test Strategy

Network-dependent scraping and API calls are non-deterministic, so tests SHALL run against captured fixtures by default.

- **Fixture capture:** A --capture CLI mode saves raw responses to tests/fixtures/<provider>/
- **Golden outputs:** expected_output.json holds normalised ModelEntry records
- **Test layers:** Unit (no network), Parser/golden (no network), Integration/live (opt-in)

### 13.4 Development Workflow: Adding a New Provider

1. Add config entry to providers.json
2. Attempt generic path: llm-registry discover --provider <id> --dry-run
3. Capture fixtures: --capture
4. Add custom parser only if generic is insufficient (coverage < 90%)
5. Create golden output (expected_output.json)
6. Run tests: pytest tests/ -k <id>
7. Document quirks in the parser module docstring


---

Appendix A: Provider Website Analysis

A.4 CometAPI (https://www.cometapi.com/models/)
Type: Static model listing page
Content: Model name, provider (Anthropic/OpenAI/Google), context window, input/output pricing
API endpoint: https://api.cometapi.com/v1/models (OpenAI-compatible, requires key)
Note: Comprehensive model catalogue; API returns pricing and context length data
A.1 Wisgate (https://wisgate.ai/pricing)
Type: JS-heavy single-page pricing table
Content: Model name, context window, input price, output price per 1M tokens
Extraction strategy: Firecrawl scrape → LLM parse markdown table → structured data
Missing from website: API type per model (OpenAI vs Anthropic vs Google), max output tokens, cache pricing
API endpoint: https://api.wisgate.ai/v1/models (OpenAI-compatible, requires key)
A.2 OpenRouter (https://openrouter.ai/models)
Type: JS-heavy interactive model browser with filters
Content: Model name, provider, context length, prompt price, completion price, capabilities tags
API endpoint: https://openrouter.ai/api/v1/models (returns full model list with pricing)
Advantage: The API returns richer data than the website — API-first approach recommended
A.3 Requesty (https://requesty.ai/models)
Type: JS-rendered model listing
Content: Model names, pricing tiers
API endpoint: https://router.requesty.ai/v1/models (custom JSON format — NOT OpenAI-compatible; prices in $/token at top level, plus capability flags)
Note: v1.3 — uses a dedicated `RequestyModelsClient` (not the OpenAI-compatible path). 512 models exposed, 506 with pricing.


Appendix B: Existing MODELS.json Structure (for reference)
Current file: ~/.openclaw/workspace/MODELS.json

88 models from Wisgate
Schema fields: model_id, provider, api_type, openclaw_provider_key, context_window, max_output_tokens, pricing (input/output/cache read/cache write per 1M), available, optional notes


Appendix C: Example Model Entry (Target Format)
{

  "wisgate_deepseek-v4-pro": {

    "model_id": "deepseek-v4-pro",

    "provider": "wisgate",

    "display_name": "DeepSeek V4 Pro",

    "api_type": "OpenAI",

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

    "last_updated": "2026-06-13T11:00:00Z",

    "source": {

      "url": "https://wisgate.ai/pricing",

      "method": "scrape",

      "scraped_at": "2026-06-13T11:00:00Z"

    }

  }

}


End of specification.