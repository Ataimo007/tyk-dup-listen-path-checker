"""Duplicate route grouping logic. Pure functions, no I/O."""

from __future__ import annotations

from collections import defaultdict
from enum import Enum

from tyk_dup_checker.models import ApiSummary, DuplicateGroup


class MatchMode(str, Enum):
    """How two APIs are considered to collide."""

    #: Default, per CLAUDE.md: both `domain` and `listen_path` must match
    #: exactly. A shared listen_path on different domain strings is not
    #: flagged.
    DOMAIN_AND_PATH = "domain-and-path"

    #: Opt-in, looser check: group on `listen_path` alone, ignoring domain.
    #: Catches cases the strict mode misses on purpose — e.g. Tyk's
    #: `{?:host1|host2}` multi-domain template syntax, where two APIs can
    #: have literally different `domain` strings that still overlap on one
    #: or more real hostnames (the `/dp-oauth/` case). Results here are
    #: "possible collision, domains differ — verify manually", not
    #: guaranteed real conflicts.
    LISTEN_PATH_ONLY = "listen-path-only"


def find_duplicates(
    apis: list[ApiSummary],
    *,
    include_internal: bool = False,
    match_mode: MatchMode = MatchMode.DOMAIN_AND_PATH,
) -> list[DuplicateGroup]:
    """Group APIs that share a route and return groups with >1 member.

    Internal (non-gateway-routable) APIs are excluded unless
    `include_internal=True`, since they don't bind a real route, regardless
    of `match_mode`.
    """
    candidates = apis if include_internal else [api for api in apis if not api.is_internal]

    if match_mode is MatchMode.DOMAIN_AND_PATH:
        return _find_duplicates_by_domain_and_path(candidates)
    return _find_duplicates_by_path_only(candidates)


def _find_duplicates_by_domain_and_path(candidates: list[ApiSummary]) -> list[DuplicateGroup]:
    groups: dict[tuple[str, str], list[ApiSummary]] = defaultdict(list)
    for api in candidates:
        groups[(api.domain, api.listen_path)].append(api)

    return [
        DuplicateGroup(domain=domain, listen_path=listen_path, apis=members)
        for (domain, listen_path), members in groups.items()
        if len(members) > 1
    ]


def _find_duplicates_by_path_only(candidates: list[ApiSummary]) -> list[DuplicateGroup]:
    groups: dict[str, list[ApiSummary]] = defaultdict(list)
    for api in candidates:
        groups[api.listen_path].append(api)

    result = []
    for listen_path, members in groups.items():
        if len(members) <= 1:
            continue
        distinct_domains = {api.domain for api in members}
        # Only meaningful as a single value when every member actually
        # shares one domain; otherwise leave it unset and let callers read
        # each ApiSummary's own `domain`.
        group_domain = next(iter(distinct_domains)) if len(distinct_domains) == 1 else None
        result.append(DuplicateGroup(domain=group_domain, listen_path=listen_path, apis=members))
    return result


def list_internal(apis: list[ApiSummary]) -> list[ApiSummary]:
    """APIs excluded from duplicate detection by default (not gateway-routable)."""
    return [api for api in apis if api.is_internal]
