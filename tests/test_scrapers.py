"""Offline unit tests for ArXiv, Hacker News, and GitHub Trending parsers."""

from ai_pulse.models import SourceType
from ai_pulse.scrapers.arxiv import ArxivScraper
from ai_pulse.scrapers.github_trending import GitHubTrendingScraper
from ai_pulse.scrapers.hackernews import HackerNewsScraper

SAMPLE_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2601.12345v1</id>
    <published>2026-01-15T18:00:00Z</published>
    <title> Efficient Agentic Reasoning with Tool Verification </title>
    <summary> We introduce a lightweight verification layer for multi-step LLM agents. </summary>
    <author><name>Jane Doe</name></author>
    <author><name>John Smith</name></author>
  </entry>
</feed>
"""

SAMPLE_GITHUB_HTML = """
<html>
  <body>
    <article class="Box-row">
      <h2><a href="/acme-ai/fast-rag">acme-ai / fast-rag</a></h2>
      <p>High-throughput RAG evaluation framework in Python.</p>
      <span itemprop="programmingLanguage">Python</span>
      <a href="/acme-ai/fast-rag/stargazers">12,345</a>
    </article>
  </body>
</html>
"""


def test_arxiv_parse_atom_feed() -> None:
    scraper = ArxivScraper()
    items = scraper.parse_atom_feed(SAMPLE_ARXIV_XML)

    assert len(items) == 1
    item = items[0]
    assert item.source == SourceType.ARXIV
    assert item.source_id == "2601.12345v1"
    assert item.title == "Efficient Agentic Reasoning with Tool Verification"
    assert item.author == "Jane Doe, John Smith"
    assert "lightweight verification layer" in item.raw_content


def test_hackernews_parse_and_relevance_filter() -> None:
    scraper = HackerNewsScraper(ai_only=True)

    ai_story = {
        "id": 998877,
        "type": "story",
        "title": "Open-source LLM inference engine hits 2x throughput on consumer GPUs",
        "url": "https://example.com/llm-engine",
        "by": "ml_builder",
        "score": 320,
        "descendants": 84,
        "time": 1737000000,
    }
    unrelated_story = {
        "id": 112233,
        "type": "story",
        "title": "Best sourdough bread recipes for winter mornings",
        "url": "https://example.com/bread",
        "by": "baker",
        "score": 150,
        "time": 1737000000,
    }

    parsed_ai = scraper.parse_story(ai_story)
    parsed_unrelated = scraper.parse_story(unrelated_story)

    assert parsed_ai is not None
    assert parsed_ai.source == SourceType.HACKERNEWS
    assert parsed_ai.score == 320
    assert parsed_unrelated is None


def test_github_trending_parse_html() -> None:
    scraper = GitHubTrendingScraper()
    items = scraper.parse_trending_html(SAMPLE_GITHUB_HTML)

    assert len(items) == 1
    item = items[0]
    assert item.source == SourceType.GITHUB_TRENDING
    assert item.source_id == "acme-ai/fast-rag"
    assert item.url == "https://github.com/acme-ai/fast-rag"
    assert item.score == 12345
    assert item.language == "Python"
