"""Async ArXiv scraper targeting recent AI, ML, and NLP research papers."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from ai_pulse.models import RawItem, SourceType
from ai_pulse.scrapers.base import BaseScraper

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


class ArxivScraper(BaseScraper):
    """Scrapes recent cs.AI, cs.LG, and cs.CL preprints via the ArXiv Atom API."""

    source = SourceType.ARXIV
    API_URL = "https://export.arxiv.org/api/query"

    def __init__(
        self,
        categories: tuple[str, ...] = ("cs.AI", "cs.LG", "cs.CL"),
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.categories = categories

    def parse_atom_feed(self, xml_text: str) -> list[RawItem]:
        """Parse ArXiv Atom XML into normalized RawItem records."""
        root = ET.fromstring(xml_text)
        items: list[RawItem] = []

        for entry in root.findall("atom:entry", ATOM_NS):
            raw_id = (entry.findtext("atom:id", default="", namespaces=ATOM_NS) or "").strip()
            title = (entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip()
            summary = (entry.findtext("atom:summary", default="", namespaces=ATOM_NS) or "").strip()
            published_str = (
                entry.findtext("atom:published", default="", namespaces=ATOM_NS) or ""
            ).strip()

            if not raw_id or not title:
                continue

            authors = [
                (author.findtext("atom:name", default="", namespaces=ATOM_NS) or "").strip()
                for author in entry.findall("atom:author", ATOM_NS)
            ]
            authors = [a for a in authors if a]
            author_display = ", ".join(authors[:3])
            if len(authors) > 3:
                author_display += f" +{len(authors) - 3} more"

            published_at = _parse_iso_datetime(published_str)
            arxiv_id = raw_id.rstrip("/").split("/")[-1]

            items.append(
                RawItem(
                    source=self.source,
                    source_id=arxiv_id,
                    title=title,
                    url=raw_id,
                    raw_content=summary,
                    author=author_display or "ArXiv Authors",
                    published_at=published_at,
                    score=0,
                )
            )

        return items

    async def scrape(self, limit: int = 15) -> list[RawItem]:
        query = " OR ".join(f"cat:{cat}" for cat in self.categories)
        params = {
            "search_query": query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": limit,
        }
        async with self._build_client() as client:
            response = await self.fetch_with_retry(client, self.API_URL, params=params)
        return self.parse_atom_feed(response.text)[:limit]


def _parse_iso_datetime(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
