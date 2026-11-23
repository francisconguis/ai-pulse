"""Base async scraper providing retries, exponential backoff, and polite rate limiting."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

from ai_pulse.models import RawItem, SourceType

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for all asynchronous source scrapers."""

    source: SourceType

    def __init__(
        self,
        timeout: float = 20.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        user_agent: str = "AIPulseBot/0.1 (+https://github.com/ai-pulse)",
        max_concurrency: int = 5,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.user_agent = user_agent
        self._semaphore = asyncio.Semaphore(max_concurrency)

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
        )

    async def fetch_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Perform a GET request with exponential backoff on transient errors."""
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                async with self._semaphore:
                    response = await client.get(url, params=params)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise httpx.HTTPStatusError(
                        f"Transient HTTP {response.status_code} for {url}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt == self.max_retries:
                    break
                delay = self.backoff_base * (2 ** (attempt - 1))
                logger.warning(
                    "[%s] Attempt %d/%d failed for %s (%s). Retrying in %.1fs...",
                    self.source.value,
                    attempt,
                    self.max_retries,
                    url,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        assert last_exc is not None
        raise last_exc

    @abstractmethod
    async def scrape(self, limit: int = 15) -> list[RawItem]:
        """Fetch and parse up to `limit` items from the target source."""
