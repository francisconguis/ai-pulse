"""Async HTML scraper for GitHub Trending repositories using BeautifulSoup4."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ai_pulse.models import RawItem, SourceType
from ai_pulse.scrapers.base import BaseScraper


class GitHubTrendingScraper(BaseScraper):
    """Scrapes trending open-source repositories from GitHub Trending."""

    source = SourceType.GITHUB_TRENDING
    BASE_URL = "https://github.com/trending"

    def __init__(self, language: str = "python", since: str = "daily", **kwargs) -> None:
        super().__init__(**kwargs)
        self.language = language
        self.since = since

    def parse_trending_html(self, html: str) -> list[RawItem]:
        """Parse GitHub Trending HTML markup into normalized RawItem objects."""
        soup = BeautifulSoup(html, "html.parser")
        articles = soup.select("article.Box-row")
        items: list[RawItem] = []

        for article in articles:
            link = article.select_one("h2 a")
            if not link or not link.get("href"):
                continue

            href = str(link["href"]).strip()
            repo_full_name = "/".join(part.strip() for part in href.strip("/").split("/")[:2])
            if not repo_full_name:
                continue

            owner = repo_full_name.split("/")[0]
            url = f"https://github.com/{repo_full_name}"

            desc_el = article.select_one("p")
            description = desc_el.get_text(" ", strip=True) if desc_el else "Trending GitHub repository."

            lang_el = article.select_one('[itemprop="programmingLanguage"]')
            programming_language = lang_el.get_text(strip=True) if lang_el else None

            stars = _extract_star_count(article)

            items.append(
                RawItem(
                    source=self.source,
                    source_id=repo_full_name,
                    title=repo_full_name,
                    url=url,
                    raw_content=description,
                    author=owner,
                    published_at=datetime.now(timezone.utc),
                    score=stars,
                    language=programming_language,
                )
            )

        return items

    async def scrape(self, limit: int = 15) -> list[RawItem]:
        target_url = f"{self.BASE_URL}/{self.language}" if self.language else self.BASE_URL
        params = {"since": self.since}
        async with self._build_client() as client:
            response = await self.fetch_with_retry(client, target_url, params=params)
        return self.parse_trending_html(response.text)[:limit]


def _extract_star_count(article) -> int:
    """Extract total stars or stars today from a GitHub Trending card."""
    star_link = article.select_one('a[href$="/stargazers"]')
    if star_link:
        digits = re.sub(r"[^\d]", "", star_link.get_text())
        if digits:
            return int(digits)

    today_span = article.select_one("span.d-inline-block.float-sm-right")
    if today_span:
        digits = re.sub(r"[^\d]", "", today_span.get_text())
        if digits:
            return int(digits)

    return 0
