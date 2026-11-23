"""Async scrapers for AI/Tech news, research papers, and trending repositories."""

from ai_pulse.scrapers.arxiv import ArxivScraper
from ai_pulse.scrapers.base import BaseScraper
from ai_pulse.scrapers.github_trending import GitHubTrendingScraper
from ai_pulse.scrapers.hackernews import HackerNewsScraper

__all__ = [
    "BaseScraper",
    "ArxivScraper",
    "HackerNewsScraper",
    "GitHubTrendingScraper",
]
