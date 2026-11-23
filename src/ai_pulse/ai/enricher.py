"""Structured AI enrichment using Gemini, OpenAI, or a built-in heuristic fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx

from ai_pulse.config import Settings
from ai_pulse.models import EnrichedItem, EnrichmentResult, RawItem, SourceType, TopicCategory

logger = logging.getLogger(__name__)

CATEGORY_KEYWORDS: dict[TopicCategory, tuple[str, ...]] = {
    TopicCategory.LLM_AGENTS: (
        "llm",
        "agent",
        "agentic",
        "rag",
        "prompt",
        "gpt",
        "claude",
        "gemini",
        "reasoning",
        "chatbot",
        "mcp",
        "tool use",
        "function calling",
    ),
    TopicCategory.COMPUTER_VISION: (
        "vision",
        "image",
        "video",
        "diffusion",
        "multimodal",
        "3d",
        "segmentation",
        "object detection",
        "vlm",
    ),
    TopicCategory.ML_SYSTEMS: (
        "inference",
        "cuda",
        "gpu",
        "quantization",
        "compiler",
        "distributed",
        "kernel",
        "serving",
        "vllm",
        "onnx",
        "triton",
        "latency",
    ),
    TopicCategory.OPEN_SOURCE: (
        "open source",
        "open-source",
        "framework",
        "library",
        "sdk",
        "cli",
        "toolkit",
        "repository",
        "python",
        "rust",
    ),
    TopicCategory.RESEARCH: (
        "paper",
        "benchmark",
        "dataset",
        "theorem",
        "gradient",
        "transformer",
        "attention",
        "reinforcement learning",
        "pretraining",
        "fine-tuning",
    ),
    TopicCategory.INDUSTRY: (
        "startup",
        "funding",
        "launch",
        "release",
        "acquisition",
        "policy",
        "regulation",
        "enterprise",
        "api",
    ),
}

TAG_CANDIDATES: tuple[str, ...] = (
    "llm",
    "agents",
    "rag",
    "python",
    "pytorch",
    "transformers",
    "diffusion",
    "multimodal",
    "inference",
    "quantization",
    "open-source",
    "benchmark",
    "robotics",
    "vision",
    "nlp",
    "reinforcement-learning",
    "mcp",
    "evaluation",
    "fine-tuning",
    "cuda",
    "rust",
)

SYSTEM_PROMPT = """You are an AI software engineering analyst.
Given a scraped tech/AI item (research paper, Hacker News story, or GitHub repository),
return ONLY valid JSON matching this exact schema:
{
  "summary": "1-2 concise technical sentences summarizing what this is.",
  "category": "One of: LLMs & Agents | Computer Vision | ML Systems & Infra | Open Source Tools | AI Research | Tech & Industry | Other",
  "tags": ["up to 5 lowercase technical tags"],
  "relevance_score": 0.0 to 10.0 (float indicating relevance to AI software engineers),
  "key_takeaway": "One crisp sentence on why an AI engineer should care."
}
Do not wrap the JSON in markdown fences or add extra text."""


class ItemEnricher:
    """Enriches RawItems via Gemini/OpenAI structured JSON or a deterministic fallback."""

    def __init__(self, settings: Settings, max_concurrency: int = 4) -> None:
        self.settings = settings
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def enrich_many(self, items: list[RawItem]) -> list[EnrichedItem]:
        """Enrich a batch of raw items concurrently."""
        if not items:
            return []
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.settings.request_timeout)) as client:
            tasks = [self._enrich_one(client, item) for item in items]
            return list(await asyncio.gather(*tasks))

    async def _enrich_one(self, client: httpx.AsyncClient, item: RawItem) -> EnrichedItem:
        provider = self.settings.active_llm_provider
        result: EnrichmentResult | None = None

        if provider == "gemini":
            result = await self._enrich_with_gemini(client, item)
        elif provider == "openai":
            result = await self._enrich_with_openai(client, item)

        if result is None:
            result = self.heuristic_enrich(item)

        return EnrichedItem.from_raw(item, result)

    async def _enrich_with_gemini(
        self, client: httpx.AsyncClient, item: RawItem
    ) -> EnrichmentResult | None:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.gemini_model}:generateContent"
        )
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": self._build_user_prompt(item)}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        try:
            async with self._semaphore:
                resp = await client.post(
                    url,
                    params={"key": self.settings.gemini_api_key},
                    json=payload,
                )
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return self.parse_llm_json(text, mode="gemini")
        except Exception as exc:
            logger.warning("Gemini enrichment failed for '%s': %s. Using fallback.", item.title, exc)
            return None

    async def _enrich_with_openai(
        self, client: httpx.AsyncClient, item: RawItem
    ) -> EnrichmentResult | None:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
        payload = {
            "model": self.settings.openai_model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self._build_user_prompt(item)},
            ],
        }
        try:
            async with self._semaphore:
                resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            return self.parse_llm_json(text, mode="openai")
        except Exception as exc:
            logger.warning("OpenAI enrichment failed for '%s': %s. Using fallback.", item.title, exc)
            return None

    @staticmethod
    def _build_user_prompt(item: RawItem) -> str:
        snippet = item.raw_content[:1200] if item.raw_content else "No description provided."
        return (
            f"Source: {item.source.value}\n"
            f"Title: {item.title}\n"
            f"Author: {item.author}\n"
            f"Score/Stars: {item.score}\n"
            f"Language: {item.language or 'N/A'}\n"
            f"Content:\n{snippet}"
        )

    @staticmethod
    def parse_llm_json(raw_text: str, mode: str) -> EnrichmentResult:
        """Parse and validate LLM JSON output into an EnrichmentResult."""
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL).strip()

        parsed = json.loads(cleaned)
        valid_categories = {c.value: c for c in TopicCategory}
        raw_cat = str(parsed.get("category", "Other")).strip()
        category = valid_categories.get(raw_cat, TopicCategory.OTHER)

        return EnrichmentResult(
            summary=str(parsed.get("summary", "")).strip() or "Summary unavailable.",
            category=category,
            tags=parsed.get("tags", []),
            relevance_score=min(10.0, max(0.0, float(parsed.get("relevance_score", 6.5)))),
            key_takeaway=str(parsed.get("key_takeaway", "")).strip() or "Notable AI/tech update.",
            enrichment_mode=mode,
        )

    @staticmethod
    def heuristic_enrich(item: RawItem) -> EnrichmentResult:
        """Deterministic offline fallback enricher when no LLM API key is configured."""
        combined = f"{item.title} {item.raw_content}".lower()

        # 1. Category classification by keyword hits
        best_category = TopicCategory.OTHER
        best_hits = 0
        for category, keywords in CATEGORY_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in combined)
            if hits > best_hits:
                best_hits = hits
                best_category = category

        if best_category == TopicCategory.OTHER:
            if item.source == SourceType.ARXIV:
                best_category = TopicCategory.RESEARCH
            elif item.source == SourceType.GITHUB_TRENDING:
                best_category = TopicCategory.OPEN_SOURCE
            else:
                best_category = TopicCategory.INDUSTRY

        # 2. Extract concise tags
        tags = [tag for tag in TAG_CANDIDATES if tag.replace("-", " ") in combined or tag in combined]
        if item.language and item.language.lower() not in tags:
            tags.insert(0, item.language.lower())
        if not tags:
            tags = [item.source.value.replace("_", "-"), "ai"]
        tags = tags[:5]

        # 3. Extractive 1-2 sentence summary
        summary = _extractive_summary(item.raw_content, fallback=item.title)

        # 4. Relevance score (0.0 - 10.0)
        base_score = 6.0 + min(2.5, best_hits * 0.6)
        if item.score >= 500:
            base_score += 1.2
        elif item.score >= 100:
            base_score += 0.7
        elif item.source == SourceType.ARXIV:
            base_score += 0.5
        relevance_score = round(min(9.8, base_score), 1)

        # 5. Key takeaway
        takeaway_map = {
            SourceType.ARXIV: f"Recent research in {best_category.value} from {item.author}.",
            SourceType.GITHUB_TRENDING: (
                f"Trending {item.language or 'open-source'} repo with {item.score:,} stars in {best_category.value}."
            ),
            SourceType.HACKERNEWS: (
                f"Active community discussion ({item.score} pts) on {best_category.value}."
            ),
        }

        return EnrichmentResult(
            summary=summary,
            category=best_category,
            tags=tags,
            relevance_score=relevance_score,
            key_takeaway=takeaway_map[item.source],
            enrichment_mode="heuristic",
        )


def _extractive_summary(text: str, fallback: str, max_chars: int = 240) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return fallback[:max_chars]
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    selected = sentences[0]
    if len(selected) < 90 and len(sentences) > 1:
        selected = f"{selected} {sentences[1]}"
    if len(selected) > max_chars:
        return selected[: max_chars - 3].rstrip() + "..."
    return selected
