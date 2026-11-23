"""Rich Typer CLI for running AI Pulse scrapes, digests, exports, schedules, and the dashboard."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_pulse.config import Settings
from ai_pulse.models import SourceType
from ai_pulse.pipeline import PulsePipeline
from ai_pulse.scheduler import start_scheduler
from ai_pulse.storage import StorageRepository

app = typer.Typer(
    name="ai-pulse",
    help="AI Pulse — Automated AI/Tech web scraper, LLM enricher, and intelligence dashboard.",
    no_args_is_help=True,
)
console = Console()


def _configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command()
def scrape(
    sources: Optional[list[SourceType]] = typer.Option(
        None,
        "--source",
        "-s",
        help="Sources to scrape (repeatable). Defaults to all: arxiv, hackernews, github_trending.",
    ),
    limit: int = typer.Option(15, "--limit", "-l", min=1, max=50, help="Max items per source."),
    export_digest: bool = typer.Option(
        True, "--export-digest/--no-export-digest", help="Write exports/latest_digest.md after scraping."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Run an asynchronous scrape + AI enrichment + SQLite persistence cycle."""
    _configure_logging(verbose)
    settings = Settings.from_env()
    pipeline = PulsePipeline(settings)

    console.print(
        Panel.fit(
            f"[bold cyan]AI Pulse Pipeline[/bold cyan]\n"
            f"Enrichment mode: [bold green]{settings.active_llm_provider}[/bold green] | "
            f"Limit/source: [bold]{limit}[/bold]",
            border_style="cyan",
        )
    )

    with console.status("[bold green]Scraping sources & enriching items..."):
        stats = asyncio.run(
            pipeline.run(sources=sources, limit_per_source=limit, export_digest=export_digest)
        )

    table = Table(title="Pipeline Run Summary", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="bold")
    table.add_row("Sources Scraped", ", ".join(stats.sources_scraped))
    table.add_row("Total Fetched", str(stats.total_fetched))
    table.add_row("New Items Saved", f"[green]{stats.new_items_saved}[/green]")
    table.add_row("Duplicates Skipped", f"[yellow]{stats.duplicates_skipped}[/yellow]")
    table.add_row("Errors", f"[red]{len(stats.errors)}[/red]" if stats.errors else "0")
    console.print(table)

    if stats.errors:
        for err in stats.errors:
            console.print(f"[red]Error:[/red] {err}")


@app.command("list")
def list_items(
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Filter by source."),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category."),
    search: Optional[str] = typer.Option(None, "--search", "-q", help="Search title/summary/tags."),
    limit: int = typer.Option(15, "--limit", "-l", min=1, max=100),
) -> None:
    """Display recently collected and enriched items in a Rich table."""
    settings = Settings.from_env()
    repo = StorageRepository(settings.db_path)
    items = repo.query_items(source=source, category=category, search=search, limit=limit)

    if not items:
        console.print("[yellow]No matching items found. Run `ai-pulse scrape` first.[/yellow]")
        raise typer.Exit(code=0)

    table = Table(title=f"AI Pulse Feed ({len(items)} items)", show_lines=True)
    table.add_column("Source", style="cyan", width=15)
    table.add_column("Category", style="magenta", width=18)
    table.add_column("Rel.", justify="right", style="green", width=5)
    table.add_column("Title & Summary", style="white")

    for item in items:
        tags = " ".join(f"[dim]#{t}[/dim]" for t in item.tags[:4])
        body = f"[bold]{item.title}[/bold]\n{item.summary}\n{tags}"
        table.add_row(item.source.value, item.category.value, f"{item.relevance_score:.1f}", body)

    console.print(table)


@app.command()
def stats() -> None:
    """Show database statistics by source and category."""
    settings = Settings.from_env()
    repo = StorageRepository(settings.db_path)
    data = repo.get_stats()

    console.print(
        Panel.fit(
            f"[bold]Total Items:[/bold] {data['total_items']}\n"
            f"[bold]Average Relevance:[/bold] {data['avg_relevance']}/10\n"
            f"[bold]Active Enrichment Mode:[/bold] {settings.active_llm_provider}",
            title="AI Pulse Stats",
            border_style="green",
        )
    )

    if data["by_source"]:
        src_table = Table(title="Items by Source")
        src_table.add_column("Source", style="cyan")
        src_table.add_column("Count", justify="right")
        for src, cnt in data["by_source"].items():  # type: ignore[union-attr]
            src_table.add_row(str(src), str(cnt))
        console.print(src_table)


@app.command()
def digest(
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output Markdown path."),
    limit: int = typer.Option(25, "--limit", "-l", min=1, max=100),
) -> None:
    """Generate a Markdown intelligence digest from stored items."""
    settings = Settings.from_env()
    pipeline = PulsePipeline(settings)
    path = pipeline.export_latest_digest(output_path=output, limit=limit)
    console.print(f"[green]Markdown digest saved to:[/green] {path}")


@app.command()
def export(
    fmt: str = typer.Option("json", "--format", "-f", help="Export format: json or csv."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Destination file path."),
    limit: int = typer.Option(200, "--limit", "-l", min=1, max=2000),
) -> None:
    """Export stored items to JSON or CSV."""
    settings = Settings.from_env()
    repo = StorageRepository(settings.db_path)
    fmt_lower = fmt.lower()

    if fmt_lower == "json":
        dest = output or (settings.export_dir / "ai_pulse_items.json")
        repo.export_json(dest, limit=limit)
    elif fmt_lower == "csv":
        dest = output or (settings.export_dir / "ai_pulse_items.csv")
        repo.export_csv(dest, limit=limit)
    else:
        console.print("[red]Unsupported format. Choose 'json' or 'csv'.[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]Exported {fmt_lower.upper()} to:[/green] {dest}")


@app.command()
def schedule(
    interval: int = typer.Option(180, "--interval", "-i", min=5, help="Interval in minutes."),
    limit: int = typer.Option(15, "--limit", "-l", min=1, max=50),
    run_now: bool = typer.Option(True, "--run-now/--wait", help="Run immediately before waiting."),
) -> None:
    """Start the automated recurring scraper schedule."""
    _configure_logging(False)
    start_scheduler(interval_minutes=interval, limit_per_source=limit, run_immediately=run_now)


@app.command()
def dashboard() -> None:
    """Launch the interactive Streamlit intelligence dashboard."""
    app_path = Path(__file__).resolve().parents[2] / "dashboard" / "app.py"
    if not app_path.exists():
        console.print(f"[red]Dashboard file not found at {app_path}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[cyan]Launching Streamlit dashboard:[/cyan] {app_path}")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)], check=False)


if __name__ == "__main__":
    app()
