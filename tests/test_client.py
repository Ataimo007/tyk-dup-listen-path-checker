import pytest
import requests
import responses
from responses import matchers

from tyk_dup_checker.client import (
    TykAuthError,
    TykClientError,
    TykConnectionError,
    TykDashboardClient,
    _describe_connection_error,
    load_credentials,
)

BASE_URL = "https://dashboard.example.com"


@pytest.mark.parametrize(
    ("raw_message", "expected_snippet"),
    [
        ("Name or service not known", "resolve the hostname"),
        ("Network is unreachable", "No network route"),
        ("Connection refused", "was refused"),
        ("certificate verify failed", "TLS/SSL handshake"),
        ("some other low-level socket weirdness", "Could not connect to"),
    ],
)
def test_describe_connection_error_classifies_known_reasons(
    raw_message: str, expected_snippet: str
) -> None:
    err = _describe_connection_error(BASE_URL, requests.exceptions.ConnectionError(raw_message))

    assert isinstance(err, TykConnectionError)
    assert expected_snippet in str(err)
    assert err.hints


def test_describe_connection_error_flags_host_docker_internal_specifically() -> None:
    err = _describe_connection_error(
        "http://host.docker.internal:3000",
        requests.exceptions.ConnectionError("Network is unreachable"),
    )

    assert any("host.docker.internal" in hint for hint in err.hints)


def _stub_unpaginated_unsupported() -> None:
    # Simulates a Dashboard that rejects/ignores `p=-1` (older versions, or a
    # proxy in front of it), forcing list_apis() to fall back to paging.
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/apis",
        json={"Status": "Error", "Message": "bad p value"},
        status=400,
        match=[matchers.query_param_matcher({"p": "-1"})],
    )


@responses.activate
def test_list_apis_uses_single_unpaginated_request_when_supported() -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/apis",
        json={"apis": [{"api_definition": {"api_id": "a1"}}, {"api_definition": {"api_id": "a2"}}]},
        match=[matchers.query_param_matcher({"p": "-1"})],
    )

    client = TykDashboardClient(BASE_URL, "secret-key")
    apis = client.list_apis()

    assert [a["api_definition"]["api_id"] for a in apis] == ["a1", "a2"]
    assert len(responses.calls) == 1
    assert responses.calls[0].request.headers["Authorization"] == "secret-key"


@responses.activate
def test_list_apis_falls_back_to_pagination_when_unpaginated_request_fails() -> None:
    _stub_unpaginated_unsupported()
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/apis",
        json={"apis": [{"api_definition": {"api_id": "a1"}}], "pages": 1},
        match=[matchers.query_param_matcher({"p": "1"})],
    )

    client = TykDashboardClient(BASE_URL, "secret-key")
    apis = client.list_apis()

    assert len(apis) == 1
    assert apis[0]["api_definition"]["api_id"] == "a1"


@responses.activate
def test_list_apis_falls_back_to_pagination_when_unpaginated_response_malformed() -> None:
    # Dashboard returns 200 but without a usable "apis" list.
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/apis",
        json={"pages": 1},
        match=[matchers.query_param_matcher({"p": "-1"})],
    )
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/apis",
        json={"apis": [{"api_definition": {"api_id": "a1"}}], "pages": 1},
        match=[matchers.query_param_matcher({"p": "1"})],
    )

    client = TykDashboardClient(BASE_URL, "secret-key")
    apis = client.list_apis()

    assert len(apis) == 1


@responses.activate
def test_list_apis_does_not_fall_back_to_pagination_on_auth_error() -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/apis",
        json={"Status": "Error", "Message": "Authorization field empty"},
        status=401,
        match=[matchers.query_param_matcher({"p": "-1"})],
    )

    client = TykDashboardClient(BASE_URL, "bad-key")
    with pytest.raises(TykAuthError):
        client.list_apis()

    # Only the unpaginated attempt should have been made — paging through
    # wouldn't fix a rejected key, so it's not worth the extra round trips.
    assert len(responses.calls) == 1


@responses.activate
def test_list_apis_does_not_fall_back_to_pagination_on_connection_error() -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/apis",
        body=requests.exceptions.ConnectionError("boom"),
        match=[matchers.query_param_matcher({"p": "-1"})],
    )

    client = TykDashboardClient(BASE_URL, "secret-key", max_retries=0)
    with pytest.raises(TykConnectionError):
        client.list_apis()

    assert len(responses.calls) == 1


@responses.activate
def test_list_apis_pages_through_all_results() -> None:
    _stub_unpaginated_unsupported()
    for page in (1, 2, 3):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/apis",
            json={
                "apis": [{"api_definition": {"api_id": f"a{page}"}}],
                "pages": 3,
            },
            match=[matchers.query_param_matcher({"p": str(page)})],
        )

    client = TykDashboardClient(BASE_URL, "secret-key")
    apis = client.list_apis()

    assert [a["api_definition"]["api_id"] for a in apis] == ["a1", "a2", "a3"]
    assert len(responses.calls) == 4


@responses.activate
def test_list_apis_stops_at_reported_pages_not_on_empty_page() -> None:
    # Tyk's real API clamps out-of-range pages to the last page rather than
    # returning empty, so the loop must be bounded by `pages`, not by an
    # empty-page sentinel.
    _stub_unpaginated_unsupported()
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/apis",
        json={"apis": [{"api_definition": {"api_id": "only"}}], "pages": 1},
        match=[matchers.query_param_matcher({"p": "1"})],
    )

    client = TykDashboardClient(BASE_URL, "secret-key")
    apis = client.list_apis()

    assert len(apis) == 1
    assert len(responses.calls) == 2


@responses.activate
def test_401_raises_auth_error() -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/apis",
        json={"Status": "Error", "Message": "Authorization field empty"},
        status=401,
    )

    client = TykDashboardClient(BASE_URL, "bad-key")
    with pytest.raises(TykAuthError):
        client.list_apis()


@responses.activate
def test_connection_error_raises_tyk_connection_error() -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/apis",
        body=requests.exceptions.ConnectionError("boom"),
    )

    client = TykDashboardClient(BASE_URL, "secret-key", max_retries=0)
    with pytest.raises(TykConnectionError):
        client.list_apis()


@responses.activate
def test_unexpected_4xx_raises_generic_client_error() -> None:
    responses.add(responses.GET, f"{BASE_URL}/api/apis", json={}, status=404)

    client = TykDashboardClient(BASE_URL, "secret-key")
    with pytest.raises(TykClientError):
        client.list_apis()


def test_load_credentials_prefers_cli_args_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYK_DASHBOARD_URL", "https://env.example.com")
    monkeypatch.setenv("TYK_DASHBOARD_API_KEY", "env-key")

    url, key = load_credentials("https://cli.example.com/", "cli-key")

    assert url == "https://cli.example.com"
    assert key == "cli-key"


def test_load_credentials_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYK_DASHBOARD_URL", "https://env.example.com")
    monkeypatch.setenv("TYK_DASHBOARD_API_KEY", "env-key")

    url, key = load_credentials(None, None)

    assert url == "https://env.example.com"
    assert key == "env-key"


def test_load_credentials_missing_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYK_DASHBOARD_URL", raising=False)
    monkeypatch.setenv("TYK_DASHBOARD_API_KEY", "env-key")

    with pytest.raises(TykClientError):
        load_credentials(None, None)


def test_load_credentials_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYK_DASHBOARD_URL", "https://env.example.com")
    monkeypatch.delenv("TYK_DASHBOARD_API_KEY", raising=False)

    with pytest.raises(TykAuthError):
        load_credentials(None, None)
