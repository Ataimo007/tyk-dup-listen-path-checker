"""Console (rich table), JSON, and CSV renderers for duplicate-route reports."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from rich.console import Console
from rich.table import Table

from tyk_dup_checker.models import ApiSummary, DuplicateGroup


def render_table(
    duplicates: list[DuplicateGroup],
    internal: list[ApiSummary],
    total_apis: int,
    console: Console,
    *,
    match_mode_label: str = "domain-and-path",
) -> None:
    if not duplicates:
        console.print(f"[green]No duplicate listen paths across {total_apis} APIs.[/green]")
    else:
        table = Table(title=f"Duplicate routes (match mode: {match_mode_label})")
        table.add_column("Domain")
        table.add_column("Listen path")
        table.add_column("API name")
        table.add_column("API ID")

        for group in duplicates:
            # group.domain is None when members span multiple domains (only
            # possible in listen-path-only mode) — show each API's own
            # domain in that case instead of a misleading blank/shared cell.
            uniform_domain = group.domain is not None
            for index, api in enumerate(group.apis):
                domain_cell = (group.domain or "") if uniform_domain else api.domain
                if uniform_domain and index != 0:
                    domain_cell = ""
                table.add_row(
                    domain_cell,
                    group.listen_path if index == 0 else "",
                    api.name,
                    api.api_id,
                )
            table.add_row("", "", "", "")

        console.print(table)
        console.print(
            f"[red]Found {len(duplicates)} duplicate route group(s) "
            f"across {total_apis} APIs.[/red]"
        )

    if internal:
        console.print(
            f"[yellow]Skipped {len(internal)} internal/non-routable API(s) "
            "(use --include-internal to check them too).[/yellow]"
        )


def _duplicates_to_dicts(duplicates: list[DuplicateGroup]) -> list[dict[str, Any]]:
    return [
        {
            # None when members span multiple domains (listen-path-only mode) —
            # each entry under "apis" always carries its own accurate domain.
            "domain": group.domain,
            "listen_path": group.listen_path,
            "apis": [
                {
                    "name": api.name,
                    "api_id": api.api_id,
                    "mongo_id": api.mongo_id,
                    "domain": api.domain,
                }
                for api in group.apis
            ],
        }
        for group in duplicates
    ]


def render_json(
    duplicates: list[DuplicateGroup],
    internal: list[ApiSummary],
    total_apis: int,
    *,
    match_mode_label: str = "domain-and-path",
) -> str:
    payload = {
        "total_apis": total_apis,
        "match_mode": match_mode_label,
        "duplicate_groups": _duplicates_to_dicts(duplicates),
        "skipped_internal": [
            {"name": api.name, "api_id": api.api_id, "mongo_id": api.mongo_id} for api in internal
        ],
    }
    return json.dumps(payload, indent=2)


def render_csv(duplicates: list[DuplicateGroup]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["domain", "listen_path", "api_name", "api_id", "mongo_id"])
    for group in duplicates:
        for api in group.apis:
            # Read domain from the API itself, not the group, so rows stay
            # accurate even when a group spans multiple domains.
            writer.writerow([api.domain, group.listen_path, api.name, api.api_id, api.mongo_id])
    return buffer.getvalue()
