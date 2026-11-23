"""Pydantic v2 data models for scraped items, AI enrichment, and pipeline runs."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class SourceType(str, Enum):
    ARXIV = "arxiv"
    HACKERNEWS = "hackernews"
    GITHUB_TRENDING = "github_trending"


class TopicCategory(str, Enum):
    LLM_AGENTS = "LLMs & Agents"
    COMPUTER_VISION = "Computer Vision"
    ML_SYSTEMS = "ML Systems & Infra"
    OPEN_SOURCE = "Open Source Tools"
    RESEARCH = "AI Research"
    INDUSTRY = "Tech & Industry"
    OTHER = "Other"


class RawItem(BaseModel):
    """Normalized record produced by any scraper before AI enrichment."""

    source: SourceType
    source_id: str = Field(..., min_length=1, description="Unique identifier within the source")
    title: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    raw_content: str = Field(default="", description="Abstract, repo description, or story text")
    author: str = Field(default="Unknown")
    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    score: int = Field(default=0, ge=0, description="Upvotes, stars, or source popularity signal")
    language: str | None = Field(default=None, description="Programming language if applicable")

    @field_validator("title", "raw_content", "author", mode="before")
    @classmethod
    def clean_whitespace(cls, value: object) -> str:
        if value is None:
            return ""
        return " ".join(str(value).split())

    @property
    def content_hash(self) -> str:
        """Deterministic deduplication key based on source and canonical URL/ID."""
        key = f"{self.source.value}:{self.source_id}:{self.url}".encode("utf-8")
        return hashlib.sha256(key).hexdigest()[:24]


class EnrichmentResult(BaseModel):
    """Structured output schema produced by the LLM or heuristic fallback enricher."""

    summary: str = Field(..., min_length=1, max_length=600)
    category: TopicCategory = Field(default=TopicCategory.OTHER)
    tags: list[str] = Field(default_factory=list, max_length=6)
    relevance_score: float = Field(..., ge=0.0, le=10.0)
    key_takeaway: str = Field(..., min_length=1, max_length=300)
    enrichment_mode: str = Field(default="heuristic", description="'gemini', 'openai', or 'heuristic'")

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: object) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",")]
        cleaned: list[str] = []
        seen: set[str] = set()
        for tag in value:  # type: ignore[union-attr]
            t = str(tag).strip().lower()
            if t and t not in seen:
                seen.add(t)
                cleaned.append(t)
        return cleaned[:6]


class EnrichedItem(RawItem):
    """Full persisted intelligence item combining scraped metadata and AI enrichment."""

    content_hash: str
    summary: str
    category: TopicCategory
    tags: list[str] = Field(default_factory=list)
    relevance_score: float = Field(ge=0.0, le=10.0)
    key_takeaway: str
    enrichment_mode: str = "heuristic"
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_raw(cls, raw: RawItem, enrichment: EnrichmentResult) -> EnrichedItem:
        return cls(
            **raw.model_dump(),
            content_hash=raw.content_hash,
            summary=enrichment.summary,
            category=enrichment.category,
            tags=enrichment.tags,
            relevance_score=enrichment.relevance_score,
            key_takeaway=enrichment.key_takeaway,
            enrichment_mode=enrichment.enrichment_mode,
        )


class PipelineRunStats(BaseModel):
    """Summary metrics for a single automated scrape-and-enrich execution."""

    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    sources_scraped: list[str] = Field(default_factory=list)
    total_fetched: int = 0
    new_items_saved: int = 0
    duplicates_skipped: int = 0
    errors: list[str] = Field(default_factory=list)
