"""Async Hacker News scraper filtered for AI, ML, and software engineering stories."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ai_pulse.models import RawItem, SourceType
from ai_pulse.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

AI_TECH_KEYWORDS = (
    "ai",
    "llm",
    "gpt",
    "claude",
    "gemini",
    "openai",
    "anthropic",
    "deepmind",
    "machine learning",
    "neural",
    "transformer",
    "agent",
    "rag",
    "vector",
    "embedding",
    "diffusion",
    "model",
    "inference",
    "cuda",
    "gpu",
    "pytorch",
    "python",
    "rust",
    "open source",
    "benchmark",
    "robotics",
    "vision",
    "speech",
    "fine-tun",
)


class HackerNewsScraper(BaseScraper):
    """Fetches top Hacker News stories concurrently and filters for AI/tech relevance."""

    source = SourceType.HACKERNEWS
    BASE_URL = "https://hacker-news.firebaseio.com/v0"

    def __init__(self, ai_only: bool = True, candidate_pool: int = 60, **kwargs) -> None:
        super().__init__(max_concurrency=8, **kwargs)
        self.ai_only = ai_only
        self.candidate_pool = candidate_pool

    @staticmethod
    def is_relevant(title: str) -> bool:
        lowered = f" {title.lower()} "
        return any(
            (f" {kw} " in lowered if len(kw) <= 3 else kw in lowered)
            for kw in AI_TECH_KEYWORDS
        )

    def parse_story(self, payload: dict[str, Any]) -> RawItem | None:
        """Convert a Hacker News API story JSON payload into a RawItem."""
        if not payload or payload.get("type") != "story" or payload.get("deleted") or payload.get("dead"):
            return None

        story_id = payload.get("id")
        title = (payload.get("title") or "").strip()
        if not story_id or not title:
            return None

        if self.ai_only and not self.is_relevant(title):
            return None

        url = payload.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
        timestamp = payload.get("time")
        published_at = (
            datetime.fromtimestamp(timestamp, tz=timezone.utc)
            if isinstance(timestamp, (int, float))
            else datetime.now(timezone.utc)
        )
        score = max(0, int(payload.get("score") or 0))
        comments = int(payload.get("descendants") or 0)
        text = payload.get("text") or f"Hacker News discussion ({score} points, {comments} comments)."

        return RawItem(
            source=self.source,
            source_id=str(story_id),
            title=title,
            url=url,
            raw_content=text,
            author=str(payload.get("by") or "HN User"),
            published_at=published_at,
            score=score,
        )

    async def _fetch_story(
        self, client: httpx.AsyncClient, story_id: int
    ) -> dict[str, Any] | None:
        try:
            resp = await self.fetch_with_retry(client, f"{self.BASE_URL}/item/{story_id}.json")
            data = resp.json()
            return data if isinstance(data, dict) else None
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("[hackernews] Skipping story %s due to error: %s", story_id, exc)
            return None

    async def scrape(self, limit: int = 15) -> list[RawItem]:
        async with self._build_client() as client:
            top_resp = await self.fetch_with_retry(client, f"{self.BASE_URL}/topstories.json")
            story_ids: list[int] = top_resp.json()[: self.candidate_pool]

            tasks = [self._fetch_story(client, sid) for sid in story_ids]
            payloads = await asyncio.gather(*tasks)

        items: list[RawItem] = []
        for payload in payloads:
            if payload is None:
                continue
            item = self.parse_story(payload)
            if item is not None:
                items.append(item)
            if len(items) >= limit:
                break

        return items
