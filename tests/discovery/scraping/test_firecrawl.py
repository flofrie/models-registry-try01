# SPDX-License-Identifier: MIT
import asyncio

from llm_registry.discovery.scraping import firecrawl
from llm_registry.discovery.scraping.firecrawl import FirecrawlClient


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"success": True, "data": {"markdown": "# ok"}}


def test_firecrawl_scrape_omits_server_timeout_by_default(monkeypatch):
    captured = {}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["http_timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(firecrawl.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(FirecrawlClient(api_key="test-key").scrape("https://example.test"))

    assert result["success"] is True
    assert captured["http_timeout"] == 60.0
    assert captured["json"] == {
        "url": "https://example.test",
        "formats": ["markdown"],
    }


def test_firecrawl_scrape_converts_configured_timeout_to_milliseconds(monkeypatch):
    captured = {}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["http_timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(firecrawl.httpx, "AsyncClient", FakeAsyncClient)

    asyncio.run(
        FirecrawlClient(
            api_key="test-key",
            firecrawl_timeout_seconds=90,
        ).scrape("https://example.test")
    )

    assert captured["http_timeout"] == 120.0
    assert captured["json"]["timeout"] == 90_000


def test_firecrawl_scrape_includes_proxy_when_configured(monkeypatch):
    captured = {}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["http_timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(firecrawl.httpx, "AsyncClient", FakeAsyncClient)

    asyncio.run(
        FirecrawlClient(
            api_key="test-key",
            firecrawl_timeout_seconds=90,
            proxy="auto",
        ).scrape("https://example.test")
    )

    assert captured["json"]["timeout"] == 90_000
    assert captured["json"]["proxy"] == "auto"
