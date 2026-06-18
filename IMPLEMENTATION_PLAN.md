# Implementation Plan: LLM Models Registry

> **Status as of v1.3 (2026-06-14):** All four target providers (Wisgate, OpenRouter, CometAPI, Requesty) are wired in. The data path is fully deterministic — LLM extraction is **deferred** (see spec §5.1, IMPL v1.3). State persistence is JSON-only (no SQLite). Tests exist for the cometapi parser; broader coverage TBD.

## Approach
**One provider first (Wisgate)** — Incremental implementation with early validation

## Phase 1: Foundation (Priority: High) ✅ Done

### 1.1 Project Scaffolding
```
llm-models-registry/
├── pyproject.toml
├── .env.example
├── providers.json
├── src/llm_registry/
│   ├── __init__.py
│   ├── cli.py
│   └── config/
│       ├── __init__.py
│       ├── loader.py      # loads + validates providers.json
│       └── models.py      # Pydantic models for config
```

**Key decisions:**
- Use `click` for CLI (rich ecosystem, good help)
- Config validation on load with clear errors
- `.env.example` for required env vars

### 1.2 Initial providers.json ✅ Done
Four providers configured: wisgate, openrouter, cometapi, requesty. See current `providers.json` for full schema.

**Deliverable:** `python -m llm_registry providers` lists configured providers ✅

---

## Phase 2: Core Discovery (Wisgate) ✅ Done

### 2.1 Schema & Data Models ✅ Done
```
src/llm_registry/
├── schema/
│   ├── __init__.py
│   ├── model_entry.py   # Pydantic ModelEntry
│   └── enums.py         # API types, scraping strategies
```

**ModelEntry fields (per spec Section 4.1):**
- model_id, provider, display_name, api_type
- openclaw_provider_key
- context_window, max_output_tokens
- pricing (nested: input/output/cache_*)
- capabilities (nested: vision, audio, tool_use, etc.)
- rate_limits (nested: RPM, TPM)
- available, deprecated, notes
- last_updated, source (nested: url, method, scraped_at)

### 2.2 API Discovery ✅ Done
```
src/llm_registry/discovery/
├── __init__.py
├── api/
│   ├── __init__.py
│   ├── openai.py     # OpenAI-compatible /models endpoint
│   └── requesty.py   # Custom Requesty client (NOT OpenAI-compatible)
```

**Flow:**
1. Load API credentials from env
2. Call `GET /v1/models` with bearer token
3. Parse response to list of model IDs
4. Map to ModelEntry (partial data from API)

**OpenRouter-specific handling:** OpenRouter returns prices in dollars (not per 1M), so we multiply by 1M and round to 2dp. Cache pricing (`input_cache_read` / `input_cache_write`) is also extracted.

**Requesty-specific handling:** Requesty's API is not OpenAI-compatible. It returns `input_price`/`output_price`/`cached_price` directly at the top level (in $/token), plus `supports_vision`/`supports_tool_calling`/etc. capability flags. A dedicated `RequestyModelsClient` is required.

**Deliverable:** `python -m llm_registry update --provider wisgate` discovers 99 models ✅

### 2.3 Website Scraping (Fallback) ✅ Done
```
src/llm_registry/discovery/
├── scraping/
│   ├── __init__.py
│   ├── firecrawl.py   # Firecrawl API client
│   └── http.py        # Simple HTTP + BeautifulSoup
```

**Flow:**
1. If `--enrich` flag set, scrape model detail pages for pricing/context
2. Per-provider logic:
   - **Wisgate**: `https://wisgate.ai/models/{model_id}` → markdown → regex parsing
   - **CometAPI**: fetch `sitemap-4.xml` → slug→(provider,slug) map → match API model_id → scrape detail page → regex parsing
3. Extract with deterministic regex/table parsing
4. Cross-reference with API data (merge, don't overwrite)

### 2.4 LLM Extraction ⏸ Deferred
```
src/llm_registry/discovery/
└── llm/
    ├── __init__.py
    └── extractor.py   # (NOT YET IMPLEMENTED)
```

Per spec §5.1 [IMPL v1.3]: Tier 2 (LLM fallback) and Tier 3 (verification mode) are **not yet implemented**. The current data path is fully deterministic. The `discovery/llm/` package is a reserved directory stub.

When implemented, the LLM client will use:
- Provider: Requesty
- Model: deepseek/deepseek-v4-pro
- Cache: SHA256(content) keyed with 24h TTL

---

## Phase 3: Normalization & Output ✅ Done

### 3.1 Normalizer ✅ Done
```
src/llm_registry/
├── normalise/
│   ├── __init__.py
│   ├── normaliser.py   # Wisgate markdown → ModelEntry
│   └── cometapi.py     # CometAPI sitemap + detail page → ModelEntry
```

Per-provider parsers handle provider-specific quirks (e.g. CometAPI's `Input:$X/M` inline format vs. Wisgate's `$X • $Y` format). The dispatch lives in `cli.py::_enrich_cometapi` and the wisgate fallback branch.

**Merge logic (per spec Section 4.3):** `read_models_json()` loads the existing file; new entries overwrite by `provider_model_id` key; new models are added with nulls for unknown fields.

### 3.2 Output Writer ✅ Done
```
src/llm_registry/output/
├── __init__.py
└── writer.py    # Atomic write + backup rotation
```

**Atomic write:**
1. Write to `MODELS.json.tmp`
2. Validate schema
3. `os.replace()` to `MODELS.json`
4. Rotate backups (keep last N)

**Deliverable:** `python -m llm_registry update` produces valid MODELS.json ✅

---

## Phase 4: CLI Commands ✅ Done (with stubs)

### Implemented Commands
```bash
# Core
models-registry update                    # Full refresh
models-registry update --provider wisgate # Single provider
models-registry update --dry-run          # No write
models-registry update --enrich           # Also scrape detail pages

# Output
models-registry generate-md               # MODELS.md from JSON
models-registry validate                  # Schema check

# Debug
models-registry providers                 # List configured
models-registry retry-failed              # Retry unresolved failed enrichment records
models-registry retry-failed --try-harder # 2x Firecrawl timeout + proxy:auto
models-registry diff --provider wisgate   # NOT YET IMPLEMENTED (stub)
models-registry cache-clear               # NOT YET IMPLEMENTED (stub; no LLM cache yet)
```

---

## Tests ✅ Partial

`tests/normalise/test_cometapi.py` covers the cometapi parser with golden fixtures. Other modules are untested.

To re-capture fixtures: see `CONTRIBUTING.md` §4 (no `--capture` CLI flag exists; the recipe is a one-liner that copies a page out of `.cache/firecrawl_scrape_cache.json`).

---

## Error Handling ⏸ Partial

### Retry Logic ✅
The httpx client is configured with `retry_attempts` and `retry_backoff_factor` from settings. Transient Firecrawl 502/429 errors are caught per-model and logged, so the rest of the enrichment continues.

Failed enrichment retry state is persisted in `.cache/failed_enrichments.json`.
The `retry-failed` command retries eligible unresolved failures, clears ledger
entries after successful enrichment, and can use `--try-harder` for a stronger
Firecrawl retry path.

### Circuit Breaker ⏸ Deferred
Not implemented. There is no `resilience/` directory in `src/llm_registry/`; the plan in earlier spec drafts to place a circuit breaker there is **deferred**, not in progress.

---

## Dependencies (Current)

```toml
[project.dependencies]
pydantic = ">=2.0"
httpx = ">=0.27"
playwright = ">=1.45"        # **listed for future use, not currently imported** — no `playwright.py` module exists and no provider uses the playwright scraping strategy
python-dotenv = ">=1.0"
rich = ">=13.0"
click = ">=8.1"
aiofiles = ">=23.0"        # **listed for future use, not currently imported** — file writes are sync via `orjson`
orjson = ">=3.9"
beautifulsoup4 = ">=4.12"    # **listed for future use, not currently imported** — the only HTML parsing is via Firecrawl markdown output

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "ruff>=0.1",
]
```

`firecrawl` SDK is **not** in the dependencies — the project calls the Firecrawl HTTP API directly via `httpx`.

---

## File Structure (Actual)

```
llm-models-registry/
├── pyproject.toml
├── .env.example
├── README.md
├── SPEC-LLM-REG-002-v1.2.md      # frozen at v1.2
├── SPEC-LLM-REG-002-v1.3.md      # current
├── IMPLEMENTATION_PLAN.md
├── providers.json
├── MODELS.json (generated)
├── MODELS.md (generated)
├── src/llm_registry/
│   ├── __init__.py
│   ├── __main__.py                # entry point for python -m
│   ├── cli.py
│   ├── config/
│   │   ├── __init__.py
│   │   ├── loader.py
│   │   └── models.py
│   ├── schema/
│   │   ├── __init__.py
│   │   └── model_entry.py
│   ├── discovery/
│   │   ├── __init__.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── openai.py
│   │   │   └── requesty.py
│   │   └── scraping/
│   │       ├── __init__.py
│   │       ├── firecrawl.py
│   │       └── http.py
│   ├── normalise/
│   │   ├── __init__.py
│   │   ├── normaliser.py
│   │   └── cometapi.py
│   └── output/
│       ├── __init__.py
│       └── writer.py
└── tests/
    ├── fixtures/
    │   └── cometapi_*.md          # golden fixtures
    └── normalise/
        └── test_cometapi.py
```

## Status Summary

| Phase | Status | Notes |
|-------|--------|-------|
| 1. Foundation | ✅ Done | 4 providers in `providers.json` |
| 2.1 Schema | ✅ Done | Pydantic v2 |
| 2.2 API discovery | ✅ Done | OpenAI + Requesty clients |
| 2.3 Website scraping | ✅ Done | Firecrawl, per-provider parsers |
| 2.4 LLM extraction | ⏸ Deferred | Directory reserved |
| 3.1 Normaliser | ✅ Done | Wisgate + CometAPI |
| 3.2 Output writer | ✅ Done | Atomic writes, backups |
| 4. CLI | ✅ Mostly | `diff` and `cache-clear` are stubs (print "Not yet implemented") |
| Tests | ✅ Partial | cometapi parser only |
| Circuit breaker | ⏸ Deferred | `resilience/` empty |
| State persistence | ⏸ JSON only | No SQLite yet |
