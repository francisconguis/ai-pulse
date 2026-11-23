"""Unit tests for structured LLM JSON parsing and deterministic heuristic fallback."""

from ai_pulse.ai.enricher import ItemEnricher
from ai_pulse.models import RawItem, SourceType, TopicCategory


def test_parse_llm_json_handles_fenced_json() -> None:
    raw_response = """```json
    {
      "summary": "Introduces a new quantized attention kernel for fast LLM serving.",
      "category": "ML Systems & Infra",
      "tags": ["CUDA", "Inference", "Quantization", "inference"],
      "relevance_score": 9.2,
      "key_takeaway": "Cuts inference latency in half on single-GPU setups."
    }
    ```"""

    result = ItemEnricher.parse_llm_json(raw_response, mode="gemini")
    assert result.category == TopicCategory.ML_SYSTEMS
    assert result.enrichment_mode == "gemini"
    assert result.relevance_score == 9.2
    assert result.tags == ["cuda", "inference", "quantization"]


def test_heuristic_enricher_classifies_and_scores() -> None:
    raw = RawItem(
        source=SourceType.GITHUB_TRENDING,
        source_id="org/agent-kit",
        title="org/agent-kit",
        url="https://github.com/org/agent-kit",
        raw_content="Open-source Python framework for building RAG and LLM agents with tool use.",
        author="org",
        score=2400,
        language="Python",
    )

    result = ItemEnricher.heuristic_enrich(raw)
    assert result.enrichment_mode == "heuristic"
    assert result.category == TopicCategory.LLM_AGENTS
    assert "python" in result.tags
    assert result.relevance_score >= 7.0
    assert result.summary
