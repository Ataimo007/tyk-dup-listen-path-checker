"""Tyk Dashboard API client: auth, pagination, retries.

Pagination contract (confirmed against Tyk's docs and a live dashboard,
see https://tyk.io/docs/5.0/tyk-apis/tyk-dashboard-api/pagination/):
`GET /api/apis?p=<n>` pages from 1, default page size 10 (configurable
server-side via `page_size` in `tyk_analytics.conf`, not reported in the
response, so it must never be assumed), and the response's `pages` field is
the total page count. Requesting a page beyond `pages` clamps to the last
page rather than erroring or returning empty, so the loop bound must be the
`pages` value itself, not an empty-page sentinel.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = 10
MAX_RETRIES = 3
BACKOFF_FACTOR = 0.5
RETRY_STATUS_CODES = (500, 502, 503, 504)


class TykClientError(Exception):
    """Base error for problems talking to the Tyk Dashboard API."""


class TykAuthError(TykClientError):
    """Missing or rejected API key."""


class TykConnectionError(TykClientError):
    """Could not reach the Dashboard at all."""

    def __init__(self, message: str, *, hints: list[str] | None = None) -> None:
        super().__init__(message)
        self.hints = hints or []


def _describe_connection_error(base_url: str, exc: BaseException) -> TykConnectionError:
    """Turn a low-level requests/urllib3 exception into a clean, actionable error.

    urllib3's default message is a nested repr of retry/pool internals (not
    something to put in front of a support engineer), so this pattern-matches
    the underlying reason and returns a short summary plus concrete checks —
    tailored for the host.docker.internal case, since that's the most common
    trap when running this CLI from inside the devcontainer.
    """
    text = str(exc).lower()
    host = urlparse(base_url).hostname or base_url

    if any(s in text for s in ("name or service not known", "nodename nor servname", "getaddrinfo failed")):
        return TykConnectionError(
            f"Could not resolve the hostname '{host}'.",
            hints=[
                f"Check TYK_DASHBOARD_URL / --dashboard-url — is '{host}' spelled correctly?",
                "Make sure you're on a network/VPN that can resolve this hostname.",
            ],
        )

    if "network is unreachable" in text:
        hints = [
            f"Confirm the Dashboard is actually reachable from here, e.g. `curl -I {base_url}`.",
            "Check whether a VPN or firewall is blocking the route.",
        ]
        if host == "host.docker.internal":
            hints.append(
                "'host.docker.internal' only routes to the host automatically on Docker "
                "Desktop (macOS/Windows). On Linux/plain Docker Engine it typically needs "
                "the container started with `--add-host=host.docker.internal:host-gateway` "
                "(add this to `runArgs` in devcontainer.json) — or use the host's LAN/bridge "
                "IP instead."
            )
        return TykConnectionError(f"No network route to '{host}'.", hints=hints)

    if "connection refused" in text:
        return TykConnectionError(
            f"Connection to '{host}' was refused.",
            hints=[
                f"Is the Tyk Dashboard actually running and listening on the port in {base_url}?",
                "Double-check the port number for typos.",
            ],
        )

    if "certificate verify failed" in text or "ssl" in text:
        return TykConnectionError(
            f"TLS/SSL handshake with '{host}' failed.",
            hints=[
                (
                    "If the Dashboard uses a self-signed or internal CA cert, that CA needs "
                    "to be trusted by this environment rather than disabling verification."
                ),
                "Confirm the URL scheme (http vs https) matches what the Dashboard serves.",
            ],
        )

    return TykConnectionError(
        f"Could not connect to '{host}'.",
        hints=[
            "Confirm TYK_DASHBOARD_URL / --dashboard-url is correct and reachable from here.",
            "Check VPN/firewall/network settings.",
        ],
    )


def load_credentials(
    dashboard_url: str | None = None, api_key: str | None = None
) -> tuple[str, str]:
    """Resolve dashboard URL/API key from CLI args, falling back to the environment.

    Callers are expected to have already loaded `.env` via `python-dotenv`
    (done once, at CLI startup) so `os.environ` is populated by the time this runs.
    """
    resolved_url = dashboard_url or os.environ.get("TYK_DASHBOARD_URL")
    resolved_key = api_key or os.environ.get("TYK_DASHBOARD_API_KEY")

    if not resolved_url:
        raise TykClientError(
            "No dashboard URL found. Set TYK_DASHBOARD_URL in .env or pass --dashboard-url."
        )
    if not resolved_key:
        raise TykAuthError(
            "No API key found. Set TYK_DASHBOARD_API_KEY in .env or pass --api-key."
        )

    return resolved_url.rstrip("/"), resolved_key


class TykDashboardClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

        self._session = requests.Session()
        retry = Retry(
            total=max_retries,
            backoff_factor=BACKOFF_FACTOR,
            status_forcelist=RETRY_STATUS_CODES,
            allowed_methods=("GET",),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._session.headers["Authorization"] = self.api_key

    def _get_page(self, page: int) -> dict[str, Any]:
        try:
            response = self._session.get(
                f"{self.base_url}/api/apis",
                params={"p": page},
                timeout=self.timeout,
            )
        except requests.exceptions.ConnectionError as exc:
            raise _describe_connection_error(self.base_url, exc) from exc
        except requests.exceptions.Timeout as exc:
            raise TykConnectionError(
                f"Timed out waiting for a response from {self.base_url}.",
                hints=[
                    (
                        "The Dashboard may be slow, overloaded, or behind a firewall "
                        "silently dropping packets."
                    ),
                    f"Try `curl -I {self.base_url}` to check reachability directly.",
                ],
            ) from exc

        if response.status_code == 401 or response.status_code == 403:
            raise TykAuthError(
                f"Tyk Dashboard rejected the API key (HTTP {response.status_code}). "
                "Check TYK_DASHBOARD_API_KEY / --api-key."
            )
        if response.status_code >= 400:
            raise TykClientError(
                f"Tyk Dashboard returned HTTP {response.status_code} for {response.url}"
            )

        return dict(response.json())

    def list_apis(self) -> list[dict[str, Any]]:
        """Fetch every API definition.

        Tries a single unpaginated request first (`p=-1`, which Tyk's Dashboard
        API pagination docs confirm disables paging and returns everything —
        `p` values of 0 or lower all mean "return all items") since that's one
        round trip instead of N. Falls back to paging through `p=1..pages` if
        the Dashboard doesn't cooperate (older versions, proxies that strip/
        reject `p<=0`, or a malformed response). Auth and connection failures
        are *not* retried this way — paging through would fail identically and
        just add a redundant, slower failure on top.
        """
        apis = self._get_all_apis_unpaginated()
        if apis is not None:
            return apis
        return self._list_apis_paginated()

    def _get_all_apis_unpaginated(self) -> list[dict[str, Any]] | None:
        try:
            response = self._get_page(-1)
        except (TykAuthError, TykConnectionError):
            raise
        except TykClientError:
            return None

        apis = response.get("apis")
        return apis if isinstance(apis, list) else None

    def _list_apis_paginated(self) -> list[dict[str, Any]]:
        first_page = self._get_page(1)
        apis: list[dict[str, Any]] = list(first_page.get("apis", []))
        total_pages = first_page.get("pages", 1)

        if not isinstance(total_pages, int) or total_pages <= 1:
            return apis

        for page_number in range(2, total_pages + 1):
            page = self._get_page(page_number)
            apis.extend(page.get("apis", []))

        return apis
