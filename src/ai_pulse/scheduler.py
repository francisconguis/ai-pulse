"""Automated recurring scheduler powered by APScheduler."""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from ai_pulse.config import Settings
from ai_pulse.pipeline import PulsePipeline

logger = logging.getLogger(__name__)


def _execute_scheduled_job(settings: Settings, limit_per_source: int) -> None:
    pipeline = PulsePipeline(settings)
    stats = asyncio.run(pipeline.run(limit_per_source=limit_per_source, export_digest=True))
    logger.info(
        "Scheduled run finished: fetched=%d saved=%d skipped=%d errors=%d",
        stats.total_fetched,
        stats.new_items_saved,
        stats.duplicates_skipped,
        len(stats.errors),
    )


def start_scheduler(
    interval_minutes: int | None = None,
    limit_per_source: int | None = None,
    run_immediately: bool = True,
) -> None:
    """Start a blocking interval scheduler for continuous automated scraping."""
    settings = Settings.from_env()
    interval = interval_minutes or settings.schedule_minutes
    limit = limit_per_source or settings.max_items_per_source

    if run_immediately:
        logger.info("Running initial scrape before starting schedule...")
        _execute_scheduled_job(settings, limit)

    scheduler = BlockingScheduler()
    scheduler.add_job(
        _execute_scheduled_job,
        trigger="interval",
        minutes=interval,
        args=[settings, limit],
        id="ai_pulse_scrape_job",
        replace_existing=True,
    )

    logger.info("AI Pulse scheduler started (interval: every %d minutes). Press Ctrl+C to stop.", interval)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped gracefully.")
