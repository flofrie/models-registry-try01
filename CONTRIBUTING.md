# Contributing to the LLM Models Registry

This guide is for both the human contributor and the Claude instance helping them.
A new provider typically means a new entry in `providers.json`, and — depending on
the provider — one or two new Python modules under `src/llm_registry/`. The five
steps below cover all the cases.

If you only skim this, the rule of thumb is: **start with a `providers.json` entry
and try `python -m llm_registry update --provider <id>`. If the discovery result
looks right, you're mostly done. Add a normaliser only if enrichment is missing
fields you need.**

## Contributor license terms

By submitting a contribution to this project, you agree that your contribution
is licensed under the same license as the project: the MIT License in `LICENSE`.

Do not submit code, fixtures, generated data, documentation, or other material
that you do not have the right to contribute. If a contribution contains
third-party material, identify its source and applicable license in the pull
request so it can be reviewed before merge.

## The five steps

1. Add the provider to `providers.json` (and `.env.example`).
2. (Optional) Add a custom API client in `src/llm_registry/discovery/api/`.
3. (Optional) Add a normaliser in `src/llm_registry/normalise/`.
4. Add a golden fixture + a regression test under `tests/`.
5. Run the full update and verify.

Details, pitfalls, and templates below.

---

## 1. `providers.json` entry

Three cases cover all current providers. Pick the closest one and copy the template.

### Case A — OpenAI-compatible `/v1/models` (most common)

If the provider exposes a standard `{ "data": [...] }` JSON at a `/v1/models`
endpoint with `Authorization: Bearer <key>`, this is all you need. **No new
Python code is required** — the existing `OpenAIModelsClient` will handle it.

```json
{
  "id": "yourprovider",
  "name": "Your Provider",
  "website": {
    "models_page": "https://yourprovider.com/models",
    "scraping_strategy": "firecrawl"
  },
  "endpoints": [
    {
      "type": "openai",
      "base_url": "https://api.yourprovider.com/v1",
      "models_endpoint": "/models",
      "auth": {
        "method": "bearer_token",
        "env_var": "YOURPROVIDER_API_KEY"
      }
    },
    {
      "type": "anthropic",
      "base_url": "https://api.yourprovider.com/v1",
      "messages_endpoint": "/messages",
      "auth": {
        "method": "bearer_token",
        "env_var": "YOURPROVIDER_API_KEY"
      }
    }
  ]
}
```

Add an `endpoint` per API surface the provider actually offers. The entry with
`models_endpoint` set is the **discovery endpoint** (typically the `openai` one).
Other endpoints are recorded for downstream SDK wiring.

### Case B — Custom JSON shape (the Requesty case)

If the provider's `/v1/models` is OpenAI-compatible in URL but the response
schema is very different, you'll need a custom client. See
`src/llm_registry/discovery/api/requesty.py` — it's the only example. The
shape of the response there (`input_price`, `output_price`, `cached_price`,
`caching_price` in $/token, plus capability flags) is the pattern to follow.

In `providers.json` the entry is otherwise identical to Case A.

### Case C — No `/v1/models` at all (only Anthropic or Google endpoints)

If the provider offers only an Anthropic-Messages-shaped or Google-GenAI-shaped
API, and no model-listing endpoint, you can't drive discovery from the config
alone. Today we don't have an example of this; the cleanest path is to add a
custom client that does its own discovery (e.g. by calling the provider's docs
site or by hardcoding a model list). This is a bigger change — please open a
discussion before writing the code.

### Auth options

`auth.method` is one of:
- `"bearer_token"` — sends `Authorization: Bearer <key>`
- `"api_key_header"` — sends a custom header (specify `auth.header_name`)
- `"api_key_query"` — passes the key as a query param (specify `auth.query_param`)

`auth.required` is `true` by default. Set it to `false` for providers whose
`/v1/models` endpoint serves unauthenticated requests (OpenRouter and
Requesty both do — verify with `curl -o /dev/null -w '%{http_code}'` before
assuming). When `required: false`, the env var may be unset; the client sends
no `Authorization` header and the discovery still works.

**Always verify by hand first** — don't just guess that the endpoint is
public. Some providers gate `/v1/models` behind auth but serve their docs
site anonymously, which can mislead a quick check.

### Also update `.env.example`

Add the new env var (e.g. `YOURPROVIDER_API_KEY=`) so contributors know what
to set. Mark it as `# required` or `# optional (discovery is public)` so
contributors know which keys are mandatory. Real values live in `.env`,
which is gitignored.

---

## 2. Custom API client (Cases B / C only)

If the existing `OpenAIModelsClient` doesn't fit, create
`src/llm_registry/discovery/api/yourprovider.py`. The interface contract is:

```python
class YourProviderModelsClient:
    def __init__(self, base_url: str, endpoint: str, api_key: str, timeout: float = 30.0):
        ...

    async def list_models(self) -> list[dict]:
        """Call the discovery endpoint and return raw model dicts."""
        ...

    def map_to_model_entry(
        self, raw: dict, provider_id: str, available_endpoint_types: set[str]
    ) -> ModelEntry:
        """Map one raw model dict to a ModelEntry.

        `available_endpoint_types` is the set of api types the provider
        exposes (e.g. {"openai", "anthropic"}). The returned `api_type`
        must be one of these strings (lowercase) or your `_infer_api_type`
        should fall back to "openai" (which every provider exposes).
        """
        ...
```

Use the existing `_keys.openclaw_provider_key(provider_id, api_type)` helper
for the openclaw key — don't inline the `f"{provider_id}-{api_type}"` pattern.
The `cometapi → comet` alias lives in that helper.

Use the existing `_infer_api_type` heuristic as a template (it's duplicated in
`openai.py` and `requesty.py` — that's a known smell, not a feature). The
heuristic is:
- Anthropic family: id/name contains `claude` / `sonnet` / `opus` / `haiku` / `fable` / `mythos`
- OpenAI family: contains `gpt` / `o1` / `o3` / `o4` / `openai` / `dall-e` / `gpt-image` / `sora`
- Google family: contains `gemini` / `veo` / `imagen` / `google`
- Fallback: `"openai"` if exposed, else the first item in the set

After writing the client, register it in
`src/llm_registry/discovery/api/__init__.py` and the
`discover_from_*` dispatch in `src/llm_registry/cli.py`.

---

## 3. Custom normaliser (only for enrichment)

The registry discovers a basic model list via the API client. **Enrichment** is
the optional `--enrich` pass that scrapes individual model detail pages for
pricing, context window, and max output tokens.

A normaliser parses a single detail page (in markdown) into a `ModelEntry`
that gets merged on top of the API-discovered entry. The interface is:

```python
def parse_yourprovider_detail_page(
    markdown: str, model_id: str, provider_id: str
) -> Optional[ModelEntry]:
    """Parse one detail page. Return None for 404 / not-found pages
    (HTTP 200 with a 'Page Not Found' body)."""
```

`src/llm_registry/normalise/cometapi.py` is the reference implementation. It
shows:
- Inline-format pricing (e.g. `Input:$1.6/M` / `Output:$9.6/M`)
- Spec-table regex for `Context window` / `Max output tokens` (any column-1
  header containing the word "context" or "max output", not just the
  literal labels)
- 404 detection: if the body contains `Page Not Found` / `404` / "page
  you're looking for doesn't exist", return `None`
- A shared `_parse_token_count` helper for `"1,048,576 tokens"` /
  `"Up to 1M"` / `"1 million tokens"`

The matching URL pattern lives in `cli.py::_enrich_yourprovider` and is wired
into the `--enrich` branch. If your provider exposes a sitemap (CometAPI does
via `sitemap-4.xml`), start there — see `_enrich_cometapi` for the pattern.

When scraping, use `scrape_with_firecrawl_cached` (not bare
`scrape_with_firecrawl`) so the per-URL 24h success / 5min error TTL cache
applies. The cache ledger lives at `.cache/firecrawl_scrape_cache.json` and
is gitignored.

`settings.firecrawl_timeout_seconds` controls the server-side timeout sent to
Firecrawl's scrape API, not the generic HTTP request timeout. When it is set,
the client sends Firecrawl `timeout` in milliseconds and gives the local
`httpx` request a small buffer so it does not cut off the scrape first. When it
is unset, the Firecrawl payload omits `timeout` and uses Firecrawl's default.
The checked-in config sets this to 90 seconds to give slow JS-rendered pages
enough time to complete.

---

## 4. Test fixture + regression test

Tests use **real saved fixtures**, not synthetic data. To add one:

```bash
# 1. Run the scraper once to populate the cache (if it isn't already)
python -m llm_registry update --provider yourprovider --enrich

# 2. Pick the URL you want a fixture for, then dump its cached markdown
.venv/bin/python -c "
import json
cache = json.load(open('.cache/firecrawl_scrape_cache.json'))
url = 'https://yourprovider.com/models/example-model/'
md = cache[url]['markdown']
open('tests/fixtures/yourprovider_example-model.md', 'w').write(md)
"

# 3. Add a regression test in tests/normalise/test_yourprovider.py
```

The fixture gives you a real page (including the exact whitespace and
formatting quirks the parser must handle). Tests should pin specific field
values (`context_window`, `pricing.input_per_1m`, etc.) so any drift in
upstream page formatting surfaces as a test failure.

For API-client tests, capture a real `/v1/models` response the same way and
save it as `tests/fixtures/yourprovider_models.json`. There aren't any API
fixtures today — the existing tests only cover the normaliser side. If you
add one, follow the golden-fixture pattern.

Run the suite with:
```bash
.venv/bin/pytest tests/ -q
```

---

## 5. Verification

Before committing:

```bash
# Does your entry parse? Lists all four providers + yours.
python -m llm_registry providers

# Discovery only, no write — does the API client work?
python -m llm_registry update --provider yourprovider --dry-run

# Full discovery + enrichment — does the normaliser work?
python -m llm_registry update --provider yourprovider --enrich --dry-run

# All four providers, no dry-run, writes MODELS.json
python -m llm_registry update --enrich
```

Then inspect `MODELS.json` (gitignored — it gets regenerated) and check:
- `yourprovider_*` entries are present, one per API-discovered model
- `openclaw_provider_key` is `yourprovider-<api_type>` (or `comet-*` for
  the special-cased cometapi provider)
- For enriched models, `context_window`, `max_output_tokens`, and `pricing`
  are populated
- `python -m llm_registry validate` passes

`MODELS.json` and `MODELS.md` are gitignored. The diff you commit is the
**code and config** — not the generated artefacts.

### After updating: check for suspicious output changes

After a real update, compare the previous and current `MODELS.json` snapshots
with the standalone checker:

```bash
python scripts/check_diff.py .backups/MODELS.backup.<timestamp>.json MODELS.json
```

The checker warns about large provider-level count drops, field-coverage drops
for fields such as context and pricing, and model IDs that disappeared or were
marked unavailable. Defaults are a 25% provider count-drop threshold and a 10%
field-coverage-drop threshold; both are configurable with script flags. Use
`--strict` in CI to return a non-zero exit code when warnings are found.

This compares two concrete output files. Because normal updates preserve old
non-null enrichment when fresh scraped data is missing, comparing ordinary
merged outputs can miss fresh scraper failures that were hidden by merge
preservation. Treat this checker as a guardrail for suspicious output changes,
not as a complete fresh-enrichment audit.

---

## Gotchas

- **`endpoints[]` not `api`.** The `endpoints` array replaces the older
  single `api` block + `api_types` list. Don't reintroduce them.
- **`models_endpoint` on exactly one entry.** The discovery code picks the
  first endpoint with `models_endpoint` set. Other endpoints are for
  downstream SDK wiring, not discovery.
- **`api_type` is lowercase.** `openai` / `anthropic` / `google` —
  uppercase variants will break matches.
- **Gated fallback.** If the inferred `api_type` isn't in your provider's
  `available_endpoint_types`, the code falls back to `"openai"` (which
  every provider exposes). Don't depend on the order of set iteration
  — it isn't guaranteed.
- **The `cometapi → comet` alias.** The `openclaw_provider_key` for the
  `cometapi` provider is `comet-<api_type>`, not `cometapi-<api_type>`.
  This matches OpenClaw's actual config convention. Use the
  `openclaw_provider_key(provider_id, api_type)` helper in
  `discovery/api/_keys.py` so the alias is applied automatically.
- **Firecrawl cache.** Per-URL, 24h success / 5min error TTL, retries on
  408/425/429/5xx with exponential backoff. See
  `src/llm_registry/discovery/scraping/cache.py`.
- **Failed enrichment ledger.** Unresolved enrichment failures are stored in
  `.cache/failed_enrichments.json`, not `MODELS.json`. Successful later
  enrichment clears the matching failure. Use `python -m llm_registry
  retry-failed` to retry eligible unresolved failures; `--try-harder` uses 2x
  Firecrawl timeout plus `proxy: "auto"`.
- **404 detection in normalisers.** Some scrapes return HTTP 200 with a
  "Page Not Found" body — return `None` from your `parse_*_detail_page`,
  don't synthesise a partial entry.
- **`MODELS.json` / `MODELS.md` / `.cache/` are gitignored.** Don't
  `git add` them. A fresh `python -m llm_registry update --enrich`
  regenerates them.
- **The user's `~/.openclaw/openclaw.json` is a separate concern.** Don't
  touch `agents.defaults.*` in that file from this project — there's a
  separate one-off script (see your local notes) for syncing registry
  data into OpenClaw config.

## What NOT to do

These are deliberately deferred or out of scope. Don't reintroduce them:

- **No LLM extraction.** Tier 2 / Tier 3 LLM fallback is **deferred** (spec
  §5.1). The data path is fully deterministic. `discovery/llm/` is a
  reserved directory stub.
- **No SQLite.** State persistence is JSON-only. `MODELS.json` is the
  source of truth.
- **No circuit breaker.** Retries live in the httpx + Firecrawl-cache
  layer. There is no `resilience/` module at all in the source tree
  (no `src/llm_registry/resilience/` directory).
- **No `openclaw_provider_keys` in providers.json.** Removed in v1.3.
  Derived per-entry via `openclaw_provider_key(provider_id, api_type)`.
- **No multi-API `api` object.** Use the `endpoints: [...]` array.
- **No data writes from the `--dry-run` path.** A dry run must leave
  `MODELS.json` untouched.

## Pointers

- **Schema & rules** (read first): `SPEC-LLM-REG-002-v1.3.md` §3.2
  (`providers.json` + `Endpoint`), §4.2 (field derivation), §4.3
  (conflict handling).
- **Quick orientation** (skim first): `README.md`, then
  `CLAUDE.md` (project-level), then `IMPLEMENTATION_PLAN.md` (file
  structure + status).
- **Reference code to copy**:
  - `discovery/api/openai.py` — Case A (OpenAI-compatible)
  - `discovery/api/requesty.py` — Case B (custom JSON)
  - `normalise/cometapi.py` — enrichment normaliser
  - `discovery/scraping/cache.py` — scrape cache + retry
  - `tests/normalise/test_cometapi.py` — test patterns
- **Open questions / known gaps** (don't fix unless asked):
  - LLM extraction (deferred)
  - Circuit breaker (deferred)
  - SQLite state (deferred)
  - "Generic" provider (config-only) parser (never built — the spec
    reference is aspirational)
