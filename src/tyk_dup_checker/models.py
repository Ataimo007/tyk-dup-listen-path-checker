"""Dataclasses describing Tyk APIs and duplicate-route groups.

`from_api_definition` is the only place that reaches into the raw Dashboard
JSON (`GET /api/apis` entries) — isolate field access here so a Tyk field
rename touches one function, not the whole codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_DOMAIN = "(default)"


@dataclass(frozen=True, slots=True)
class ApiSummary:
    mongo_id: str
    api_id: str
    name: str
    listen_path: str
    domain: str
    is_internal: bool
    is_oas: bool


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    #: The shared domain, or None if this group's members span multiple
    #: domains (only possible under detector.MatchMode.LISTEN_PATH_ONLY) —
    #: in that case each ApiSummary's own `domain` is authoritative.
    domain: str | None
    listen_path: str
    apis: list[ApiSummary]


def from_api_definition(raw: dict[str, Any]) -> ApiSummary:
    """Build an ApiSummary from one entry of the `GET /api/apis` response.

    Each entry wraps the actual API definition under `api_definition`, with
    a couple of fields (`is_oas`) only present on the outer entry.
    """
    definition = raw["api_definition"]
    proxy = definition.get("proxy") or {}

    domain = definition.get("domain") or ""
    domain_disabled = bool(definition.get("domain_disabled"))
    normalized_domain = DEFAULT_DOMAIN if (not domain or domain_disabled) else domain

    return ApiSummary(
        mongo_id=definition.get("id", ""),
        api_id=definition.get("api_id", ""),
        name=definition.get("name", ""),
        listen_path=proxy.get("listen_path", ""),
        domain=normalized_domain,
        is_internal=bool(definition.get("internal")),
        is_oas=bool(raw.get("is_oas")),
    )
