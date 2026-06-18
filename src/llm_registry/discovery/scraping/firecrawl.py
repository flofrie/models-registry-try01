# SPDX-License-Identifier: MIT
"""Firecrawl scraping client."""
import os
from typing import Optional

import httpx

DEFAULT_HTTP_TIMEOUT_SECONDS = 60.0
HTTP_TIMEOUT_BUFFER_SECONDS = 30.0


class FirecrawlClient:
    """Client for Firecrawl API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: Optional[float] = DEFAULT_HTTP_TIMEOUT_SECONDS,
        firecrawl_timeout_seconds: Optional[int] = None,
    ):
        self.api_key = api_key or os.environ.get("FIRECRAWL_API_KEY")
        self.firecrawl_timeout_seconds = firecrawl_timeout_seconds
        self.timeout = _http_timeout(
            timeout=timeout,
            firecrawl_timeout_seconds=firecrawl_timeout_seconds,
        )
        if not self.api_key:
            raise ValueError("Firecrawl API key required (set FIRECRAWL_API_KEY)")

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def scrape(self, url: str, formats: list[str] = None) -> dict:
        """Scrape a URL and return the response."""
        if formats is None:
            formats = ["markdown"]

        payload = {
            "url": url,
            "formats": formats,
        }
        if self.firecrawl_timeout_seconds is not None:
            payload["timeout"] = self.firecrawl_timeout_seconds * 1000

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                "https://api.firecrawl.dev/v1/scrape",
                headers=self._get_headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()


def _http_timeout(
    *,
    timeout: Optional[float],
    firecrawl_timeout_seconds: Optional[int],
) -> Optional[float]:
    if firecrawl_timeout_seconds is None:
        return timeout
    buffered_timeout = firecrawl_timeout_seconds + HTTP_TIMEOUT_BUFFER_SECONDS
    if timeout is None:
        return buffered_timeout
    return max(timeout, buffered_timeout)


async def scrape_with_firecrawl(
    url: str,
    api_key: Optional[str] = None,
    firecrawl_timeout_seconds: Optional[int] = None,
) -> str:
    """Scrape a URL using Firecrawl and return markdown content."""
    client = FirecrawlClient(
        api_key,
        firecrawl_timeout_seconds=firecrawl_timeout_seconds,
    )
    result = await client.scrape(url)

    if not result.get("success"):
        raise Exception(f"Firecrawl scrape failed: {result}")

    return result.get("data", {}).get("markdown", "")
