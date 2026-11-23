"""SQLite persistence layer with deduplication, filtering, and export utilities."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ai_pulse.models import EnrichedItem, PipelineRunStats, SourceType, TopicCategory

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS items (
    content_hash TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    raw_content TEXT NOT NULL,
    author TEXT NOT NULL,
    published_at TEXT NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    language TEXT,
    summary TEXT NOT NULL,
    category TEXT NOT NULL,
    tags TEXT NOT NULL,
    relevance_score REAL NOT NULL,
    key_takeaway TEXT NOT NULL,
    enrichment_mode TEXT NOT NULL,
    scraped_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);
CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
CREATE INDEX IF NOT EXISTS idx_items_scraped_at ON items(scraped_at DESC);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    sources_scraped TEXT NOT NULL,
    total_fetched INTEGER NOT NULL,
    new_items_saved INTEGER NOT NULL,
    duplicates_skipped INTEGER NOT NULL,
    errors TEXT NOT NULL
);
"""


class StorageRepository:
    """Manages SQLite storage for enriched intelligence items and pipeline run logs."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def get_existing_hashes(self, hashes: Iterable[str]) -> set[str]:
        """Return the subset of content hashes that already exist in SQLite."""
        hash_list = list(hashes)
        if not hash_list:
            return set()
        placeholders = ",".join("?" for _ in hash_list)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT content_hash FROM items WHERE content_hash IN ({placeholders})",
                hash_list,
            ).fetchall()
        return {row["content_hash"] for row in rows}

    def save_items(self, items: Iterable[EnrichedItem]) -> tuple[int, int]:
        """Insert new items while skipping duplicates. Returns (saved_count, skipped_count)."""
        saved = 0
        skipped = 0
        with self._connect() as conn:
            for item in items:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO items (
                        content_hash, source, source_id, title, url, raw_content,
                        author, published_at, score, language, summary, category,
                        tags, relevance_score, key_takeaway, enrichment_mode, scraped_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.content_hash,
                        item.source.value,
                        item.source_id,
                        item.title,
                        item.url,
                        item.raw_content,
                        item.author,
                        item.published_at.isoformat(),
                        item.score,
                        item.language,
                        item.summary,
                        item.category.value,
                        json.dumps(item.tags),
                        item.relevance_score,
                        item.key_takeaway,
                        item.enrichment_mode,
                        item.scraped_at.isoformat(),
                    ),
                )
                if cursor.rowcount == 1:
                    saved += 1
                else:
                    skipped += 1
        return saved, skipped

    def log_run(self, stats: PipelineRunStats) -> None:
        """Persist pipeline run telemetry."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pipeline_runs (
                    started_at, finished_at, sources_scraped, total_fetched,
                    new_items_saved, duplicates_skipped, errors
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stats.started_at.isoformat(),
                    stats.finished_at.isoformat() if stats.finished_at else None,
                    json.dumps(stats.sources_scraped),
                    stats.total_fetched,
                    stats.new_items_saved,
                    stats.duplicates_skipped,
                    json.dumps(stats.errors),
                ),
            )

    def query_items(
        self,
        source: str | None = None,
        category: str | None = None,
        search: str | None = None,
        min_relevance: float = 0.0,
        limit: int = 100,
    ) -> list[EnrichedItem]:
        """Query persisted items with optional source, category, search, and score filters."""
        clauses = ["relevance_score >= ?"]
        params: list[object] = [min_relevance]

        if source and source != "All":
            clauses.append("source = ?")
            params.append(source)
        if category and category != "All":
            clauses.append("category = ?")
            params.append(category)
        if search:
            like = f"%{search.strip()}%"
            clauses.append("(title LIKE ? OR summary LIKE ? OR tags LIKE ? OR raw_content LIKE ?)")
            params.extend([like, like, like, like])

        where_sql = " AND ".join(clauses)
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM items
                WHERE {where_sql}
                ORDER BY scraped_at DESC, relevance_score DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        return [_row_to_item(row) for row in rows]

    def get_stats(self) -> dict[str, object]:
        """Return aggregate counts by source, category, and recent run metadata."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            by_source = {
                row["source"]: row["cnt"]
                for row in conn.execute(
                    "SELECT source, COUNT(*) AS cnt FROM items GROUP BY source"
                ).fetchall()
            }
            by_category = {
                row["category"]: row["cnt"]
                for row in conn.execute(
                    "SELECT category, COUNT(*) AS cnt FROM items GROUP BY category"
                ).fetchall()
            }
            avg_relevance = conn.execute(
                "SELECT COALESCE(AVG(relevance_score), 0.0) FROM items"
            ).fetchone()[0]
            last_run = conn.execute(
                "SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()

        return {
            "total_items": total,
            "by_source": by_source,
            "by_category": by_category,
            "avg_relevance": round(float(avg_relevance), 2),
            "last_run": dict(last_run) if last_run else None,
        }

    def export_json(self, output_path: Path, limit: int = 200) -> Path:
        items = self.query_items(limit=limit)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [item.model_dump(mode="json") for item in items]
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return output_path

    def export_csv(self, output_path: Path, limit: int = 200) -> Path:
        items = self.query_items(limit=limit)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "source",
            "title",
            "category",
            "relevance_score",
            "summary",
            "key_takeaway",
            "tags",
            "author",
            "score",
            "url",
            "enrichment_mode",
            "published_at",
            "scraped_at",
        ]
        with output_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for item in items:
                writer.writerow(
                    {
                        "source": item.source.value,
                        "title": item.title,
                        "category": item.category.value,
                        "relevance_score": item.relevance_score,
                        "summary": item.summary,
                        "key_takeaway": item.key_takeaway,
                        "tags": ", ".join(item.tags),
                        "author": item.author,
                        "score": item.score,
                        "url": item.url,
                        "enrichment_mode": item.enrichment_mode,
                        "published_at": item.published_at.isoformat(),
                        "scraped_at": item.scraped_at.isoformat(),
                    }
                )
        return output_path

    def render_markdown_digest(self, limit: int = 20) -> str:
        """Generate a clean Markdown intelligence digest of top recent items."""
        items = self.query_items(limit=limit)
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            "# AI Pulse — Automated Intelligence Digest",
            f"_Generated: {generated_at} | Items: {len(items)}_",
            "",
        ]
        if not items:
            lines.append("No items collected yet. Run `ai-pulse scrape` to populate the database.")
            return "\n".join(lines)

        grouped: dict[str, list[EnrichedItem]] = {}
        for item in items:
            grouped.setdefault(item.category.value, []).append(item)

        for category, cat_items in grouped.items():
            lines.append(f"## {category}")
            lines.append("")
            for item in cat_items:
                tag_str = ", ".join(f"`{t}`" for t in item.tags) if item.tags else "`ai`"
                lines.append(
                    f"- **[{item.title}]({item.url})** "
                    f"(`{item.source.value}` | Relevance: **{item.relevance_score:.1f}/10**)"
                )
                lines.append(f"  - **Summary:** {item.summary}")
                lines.append(f"  - **Takeaway:** {item.key_takeaway}")
                lines.append(f"  - **Tags:** {tag_str}")
            lines.append("")

        return "\n".join(lines)


def _row_to_item(row: sqlite3.Row) -> EnrichedItem:
    return EnrichedItem(
        content_hash=row["content_hash"],
        source=SourceType(row["source"]),
        source_id=row["source_id"],
        title=row["title"],
        url=row["url"],
        raw_content=row["raw_content"],
        author=row["author"],
        published_at=datetime.fromisoformat(row["published_at"]),
        score=int(row["score"]),
        language=row["language"],
        summary=row["summary"],
        category=TopicCategory(row["category"]),
        tags=json.loads(row["tags"]),
        relevance_score=float(row["relevance_score"]),
        key_takeaway=row["key_takeaway"],
        enrichment_mode=row["enrichment_mode"],
        scraped_at=datetime.fromisoformat(row["scraped_at"]),
    )
