"""Typer CLI entrypoint: wires client -> detector -> report."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from tyk_dup_checker.client import (
    TykClientError,
    TykConnectionError,
    TykDashboardClient,
    load_credentials,
)
from tyk_dup_checker.detector import MatchMode, find_duplicates, list_internal
from tyk_dup_checker.models import from_api_definition
from tyk_dup_checker.report import render_csv, render_json, render_table

app = typer.Typer(add_completion=False)
console = Console()
error_console = Console(stderr=True)


@app.command()
def main(
    dashboard_url: Annotated[
        str | None, typer.Option("--dashboard-url", help="Overrides TYK_DASHBOARD_URL.")
    ] = None,
    api_key: Annotated[
        str | None, typer.Option("--api-key", help="Overrides TYK_DASHBOARD_API_KEY.")
    ] = None,
    include_internal: Annotated[
        bool,
        typer.Option("--include-internal", help="Also check internal/non-routable APIs."),
    ] = False,
    match_mode: Annotated[
        MatchMode,
        typer.Option(
            "--match-mode",
            help=(
                "domain-and-path (default): only flag APIs whose domain AND listen_path "
                "both match exactly. listen-path-only: flag any APIs sharing a listen_path "
                "regardless of domain — looser, but catches cases like Tyk's overlapping "
                "'{?:host1|host2}' multi-domain templates, which strict mode misses on purpose."
            ),
        ),
    ] = MatchMode.DOMAIN_AND_PATH,
    output_format: Annotated[
        str, typer.Option("--format", help="Output format: table, json, or csv.")
    ] = "table",
    output: Annotated[
        Path | None, typer.Option("--output", help="Write output to a file instead of stdout.")
    ] = None,
) -> None:
    """Report Tyk APIs that share the same (domain, listen_path)."""
    # override=True: the devcontainer pre-declares these as empty env vars,
    # and python-dotenv otherwise refuses to overwrite already-set variables.
    load_dotenv(override=True)

    if output_format not in ("table", "json", "csv"):
        error_console.print(f"[red]Unknown --format '{output_format}'. Use table, json, or csv.[/red]")
        raise typer.Exit(code=2)

    try:
        resolved_url, resolved_key = load_credentials(dashboard_url, api_key)
        client = TykDashboardClient(resolved_url, resolved_key)
        raw_apis = client.list_apis()
    except TykConnectionError as exc:
        _render_connection_error(exc)
        raise typer.Exit(code=1) from None
    except TykClientError as exc:
        error_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    apis = [from_api_definition(raw) for raw in raw_apis]
    duplicates = find_duplicates(apis, include_internal=include_internal, match_mode=match_mode)
    internal = [] if include_internal else list_internal(apis)

    if output_format == "table":
        render_table(duplicates, internal, len(apis), console, match_mode_label=match_mode.value)
    elif output_format == "json":
        text = render_json(duplicates, internal, len(apis), match_mode_label=match_mode.value)
        _write_output(text, output)
    else:
        text = render_csv(duplicates)
        _write_output(text, output)

    raise typer.Exit(code=1 if duplicates else 0)


def _render_connection_error(exc: TykConnectionError) -> None:
    body = str(exc)
    if exc.hints:
        body += "\n\n[bold]Possible causes / things to check:[/bold]\n" + "\n".join(
            f"  • {hint}" for hint in exc.hints
        )
    error_console.print(
        Panel(body, title="Could not reach Tyk Dashboard", border_style="red", expand=False)
    )


def _write_output(text: str, output: Path | None) -> None:
    if output is None:
        print(text)
    else:
        output.write_text(text)
        console.print(f"Wrote output to {output}")


if __name__ == "__main__":
    app()
