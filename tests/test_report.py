import json

from tyk_dup_checker.models import ApiSummary, DuplicateGroup
from tyk_dup_checker.report import render_csv, render_json


def _api(api_id: str, domain: str, listen_path: str) -> ApiSummary:
    return ApiSummary(
        mongo_id=f"mongo-{api_id}",
        api_id=api_id,
        name=f"API {api_id}",
        listen_path=listen_path,
        domain=domain,
        is_internal=False,
        is_oas=False,
    )


def test_render_json_includes_per_api_domain_and_null_group_domain_when_mixed() -> None:
    group = DuplicateGroup(
        domain=None,
        listen_path="/v1/",
        apis=[_api("a1", "public.example.com", "/v1/"), _api("a2", "staging.example.com", "/v1/")],
    )

    payload = json.loads(render_json([group], [], 2, match_mode_label="listen-path-only"))

    assert payload["match_mode"] == "listen-path-only"
    assert payload["duplicate_groups"][0]["domain"] is None
    api_domains = {a["domain"] for a in payload["duplicate_groups"][0]["apis"]}
    assert api_domains == {"public.example.com", "staging.example.com"}


def test_render_csv_uses_each_apis_own_domain() -> None:
    group = DuplicateGroup(
        domain=None,
        listen_path="/v1/",
        apis=[_api("a1", "public.example.com", "/v1/"), _api("a2", "staging.example.com", "/v1/")],
    )

    csv_text = render_csv([group])
    rows = csv_text.strip().splitlines()

    assert rows[0] == "domain,listen_path,api_name,api_id,mongo_id"
    assert "public.example.com,/v1/,API a1,a1,mongo-a1" in rows[1]
    assert "staging.example.com,/v1/,API a2,a2,mongo-a2" in rows[2]
