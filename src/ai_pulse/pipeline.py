"""End-to-end async scraping, deduplication, AI enrichment, and storage pipeline."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from ai_pulse.ai.enricher import ItemEnricher
from ai_pulse.config import Settings
from ai_pulse.models import PipelineRunStats, RawItem, SourceType
from ai_pulse.scrapers import (
    ArxivScraper,
    BaseScraper,
    GitHubTrendingScraper,
    HackerNewsScraper,
)
from ai_pulse.storage import StorageRepository

logger = logging.getLogger(__name__)


class PulsePipeline:
    """Coordinates concurrent scraping, pre-enrichment deduplication, and persistence."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.storage = StorageRepository(self.settings.db_path)
        self.enricher = ItemEnricher(self.settings)

    def _build_scrapers(self, sources: list[SourceType] | None = None) -> list[BaseScraper]:
        selected = sources or [
            SourceType.ARXIV,
            SourceType.HACKERNEWS,
            SourceType.GITHUB_TRENDING,
        ]
        common_kwargs = {
            "timeout": self.settings.request_timeout,
            "user_agent": self.settings.user_agent,
        }
        registry: dict[SourceType, BaseScraper] = {
            SourceType.ARXIV: ArxivScraper(**common_kwargs),
            SourceType.HACKERNEWS: HackerNewsScraper(**common_kwargs),
            SourceType.GITHUB_TRENDING: GitHubTrendingScraper(**common_kwargs),
        }
        return [registry[src] for src in selected if src in registry]

    async def run(
        self,
        sources: list[SourceType] | None = None,
        limit_per_source: int | None = None,
        export_digest: bool = False,
    ) -> PipelineRunStats:
        """Execute a full scrape -> deduplicate -> enrich -> store run."""
        limit = limit_per_source or self.settings.max_items_per_source
        scrapers = self._build_scrapers(sources)
        stats = PipelineRunStats(sources_scraped=[s.source.value for s in scrapers])

        # 1. Scrape all enabled sources concurrently
        results = await asyncio.gather(
            *(scraper.scrape(limit=limit) for scraper in scrapers),
            return_exceptions=True,
        )

        fetched_items: list[RawItem] = []
        for scraper, outcome in zip(scrapers, results):
            if isinstance(outcome, Exception):
                err_msg = f"{scraper.source.value}: {outcome}"
                logger.error("Scraper failed: %s", err_msg)
                stats.errors.append(err_msg)
            else:
                fetched_items.extend(outcome)

        stats.total_fetched = len(fetched_items)

        # 2. Deduplicate in-batch AND against SQLite before calling AI enrichment
        unique_by_hash: dict[str, RawItem] = {}
        for item in fetched_items:
            unique_by_hash.setdefault(item.content_hash, item)

        existing_hashes = self.storage.get_existing_hashes(unique_by_hash.keys())
        new_raw_items = [
            item for h, item in unique_by_hash.items() if h not in existing_hashes
        ]
        stats.duplicates_skipped = stats.total_fetched - len(new_raw_items)

        # 3. Enrich only genuinely new items (saves LLM tokens & latency)
        if new_raw_items:
            enriched_items = await self.enricher.enrich_many(new_raw_items)
            saved, extra_skipped = self.storage.save_items(enriched_items)
            stats.new_items_saved = saved
            stats.duplicates_skipped += extra_skipped

        stats.finished_at = datetime.now(timezone.utc)
        self.storage.log_run(stats)

        # 4. Optionally export a Markdown digest
        if export_digest:
            digest_path = self.export_latest_digest()
            logger.info("Exported Markdown digest to %s", digest_path)

        return stats

    def export_latest_digest(self, output_path: Path | None = None, limit: int = 25) -> Path:
        target = output_path or (self.settings.export_dir / "latest_digest.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        markdown = self.storage.render_markdown_digest(limit=limit)
        target.write_text(markdown, encoding="utf-8")
        return target
