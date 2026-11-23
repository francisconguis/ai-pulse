"""Unit tests for SQLite persistence, deduplication, querying, and exports."""

from pathlib import Path

from ai_pulse.models import EnrichedItem, EnrichmentResult, RawItem, SourceType, TopicCategory
from ai_pulse.storage import StorageRepository


def _make_item(source_id: str, title: str, score: float = 8.5) -> EnrichedItem:
    raw = RawItem(
        source=SourceType.ARXIV,
        source_id=source_id,
        title=title,
        url=f"https://arxiv.org/abs/{source_id}",
        raw_content="Detailed abstract about LLM agents and evaluation.",
        author="Research Team",
    )
    enrichment = EnrichmentResult(
        summary="A concise summary of the paper.",
        category=TopicCategory.LLM_AGENTS,
        tags=["llm", "agents"],
        relevance_score=score,
        key_takeaway="Improves agent reliability.",
        enrichment_mode="heuristic",
    )
    return EnrichedItem.from_raw(raw, enrichment)


def test_storage_deduplication_and_query(tmp_path: Path) -> None:
    repo = StorageRepository(tmp_path / "test.db")
    item1 = _make_item("2601.00001", "Agentic Tool Calling at Scale")
    item2 = _make_item("2601.00002", "Quantized Inference Kernels", score=7.2)

    saved, skipped = repo.save_items([item1, item2])
    assert (saved, skipped) == (2, 0)

    # Saving duplicates should skip both
    saved_again, skipped_again = repo.save_items([item1, item2])
    assert (saved_again, skipped_again) == (0, 2)

    results = repo.query_items(search="Agentic", min_relevance=8.0)
    assert len(results) == 1
    assert results[0].source_id == "2601.00001"

    stats = repo.get_stats()
    assert stats["total_items"] == 2


def test_storage_exports(tmp_path: Path) -> None:
    repo = StorageRepository(tmp_path / "export_test.db")
    repo.save_items([_make_item("2601.00003", "Structured Outputs for Production AI")])

    json_path = repo.export_json(tmp_path / "out.json")
    csv_path = repo.export_csv(tmp_path / "out.csv")
    md = repo.render_markdown_digest()

    assert json_path.exists() and "Structured Outputs" in json_path.read_text(encoding="utf-8")
    assert csv_path.exists() and "Structured Outputs" in csv_path.read_text(encoding="utf-8")
    assert "# AI Pulse" in md and "Structured Outputs" in md
