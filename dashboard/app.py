"""Interactive Streamlit dashboard for AI Pulse."""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

# Allow `streamlit run dashboard/app.py` to work even without `pip install -e .`
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_pulse.config import Settings  # noqa: E402
from ai_pulse.models import SourceType, TopicCategory  # noqa: E402
from ai_pulse.pipeline import PulsePipeline  # noqa: E402
from ai_pulse.storage import StorageRepository  # noqa: E402

st.set_page_config(
    page_title="AI Pulse: Automated AI Intelligence",
    page_icon="⚡",
    layout="wide",
)

settings = Settings.from_env()
repo = StorageRepository(settings.db_path)

st.title("⚡ AI Pulse: Automated AI/Tech Intelligence")
st.caption(
    "Async multi-source scraper (ArXiv, Hacker News, GitHub Trending) + "
    "Pydantic-validated AI enrichment + SQLite deduplication"
)

# --- Sidebar: Live Scraper & Filters ---
with st.sidebar:
    st.header("🔄 Live Scraper")
    st.info(f"Enrichment mode: **{settings.active_llm_provider.upper()}**")

    selected_sources = st.multiselect(
        "Sources to scrape",
        options=[s.value for s in SourceType],
        default=[s.value for s in SourceType],
    )
    limit_per_source = st.slider("Max items per source", min_value=5, max_value=30, value=10, step=5)

    if st.button("🚀 Run Scrape Now", type="primary", use_container_width=True):
        if not selected_sources:
            st.warning("Select at least one source.")
        else:
            with st.spinner("Scraping sources and enriching new items..."):
                pipeline = PulsePipeline(settings)
                source_enums = [SourceType(s) for s in selected_sources]
                stats = asyncio.run(
                    pipeline.run(
                        sources=source_enums,
                        limit_per_source=limit_per_source,
                        export_digest=True,
                    )
                )
            st.success(
                f"Done! Fetched {stats.total_fetched} | "
                f"Saved {stats.new_items_saved} new | "
                f"Skipped {stats.duplicates_skipped} duplicates"
            )
            if stats.errors:
                for err in stats.errors:
                    st.error(err)
            st.rerun()

    st.divider()
    st.header("🔍 Filter Feed")
    source_filter = st.selectbox("Source", ["All"] + [s.value for s in SourceType])
    category_filter = st.selectbox("Category", ["All"] + [c.value for c in TopicCategory])
    min_relevance = st.slider("Min relevance score", 0.0, 10.0, 0.0, 0.5)
    search_query = st.text_input("Search keywords", placeholder="e.g. agents, rag, pytorch...")

# --- KPI Row ---
db_stats = repo.get_stats()
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Stored Items", int(db_stats["total_items"]))
col2.metric("Avg Relevance Score", f"{db_stats['avg_relevance']} / 10")
col3.metric("Active Sources", len(db_stats["by_source"]))  # type: ignore[arg-type]
col4.metric("Enrichment Mode", settings.active_llm_provider.upper())

items = repo.query_items(
    source=source_filter,
    category=category_filter,
    search=search_query or None,
    min_relevance=min_relevance,
    limit=150,
)

tab_feed, tab_analytics, tab_digest = st.tabs(
    ["📰 Intelligence Feed", "📊 Analytics", "📝 Daily Digest & Export"]
)

with tab_feed:
    if not items:
        st.warning(
            "No items match your filters yet. Click **Run Scrape Now** in the sidebar "
            "or run `ai-pulse scrape` in your terminal."
        )
    else:
        st.caption(f"Showing {len(items)} items")
        for item in items:
            with st.container(border=True):
                top_left, top_right = st.columns([5, 1])
                with top_left:
                    st.markdown(f"### [{item.title}]({item.url})")
                    st.caption(
                        f"**{item.source.value}** · {item.category.value} · "
                        f"By {item.author} · Enriched via `{item.enrichment_mode}`"
                    )
                with top_right:
                    st.metric("Relevance", f"{item.relevance_score:.1f}/10")

                st.write(item.summary)
                st.markdown(f"**Key Takeaway:** {item.key_takeaway}")
                if item.tags:
                    st.markdown(" ".join(f"`#{t}`" for t in item.tags))

with tab_analytics:
    if not items:
        st.info("Collect some data first to see analytics charts.")
    else:
        left, right = st.columns(2)
        with left:
            st.subheader("Items by Category")
            cat_counts = Counter(item.category.value for item in items)
            cat_df = pd.DataFrame(cat_counts.items(), columns=["Category", "Count"]).set_index(
                "Category"
            )
            st.bar_chart(cat_df)

        with right:
            st.subheader("Items by Source")
            src_counts = Counter(item.source.value for item in items)
            src_df = pd.DataFrame(src_counts.items(), columns=["Source", "Count"]).set_index(
                "Source"
            )
            st.bar_chart(src_df)

        st.subheader("Top Extracted Tags")
        tag_counts = Counter(tag for item in items for tag in item.tags)
        if tag_counts:
            top_tags_df = pd.DataFrame(
                tag_counts.most_common(12), columns=["Tag", "Mentions"]
            ).set_index("Tag")
            st.bar_chart(top_tags_df)

with tab_digest:
    markdown_digest = repo.render_markdown_digest(limit=25)
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "⬇️ Download Markdown Digest (.md)",
            data=markdown_digest,
            file_name="ai_pulse_digest.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with dl2:
        json_payload = json.dumps([item.model_dump(mode="json") for item in items], indent=2)
        st.download_button(
            "⬇️ Download Filtered Items (.json)",
            data=json_payload,
            file_name="ai_pulse_items.json",
            mime="application/json",
            use_container_width=True,
        )
    st.divider()
    st.markdown(markdown_digest)
