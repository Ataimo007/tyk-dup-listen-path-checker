import json
from pathlib import Path

import pytest

from tyk_dup_checker.detector import MatchMode, find_duplicates, list_internal
from tyk_dup_checker.models import from_api_definition

FIXTURES = Path(__file__).parent / "fixtures"


def _load_apis(filename: str) -> list:
    raw = json.loads((FIXTURES / filename).read_text())
    return [from_api_definition(entry) for entry in raw["apis"]]


def test_clean_fixture_has_no_duplicates() -> None:
    apis = _load_apis("clean.json")
    assert find_duplicates(apis) == []


def test_same_domain_same_path_is_a_duplicate() -> None:
    apis = _load_apis("same_domain_collision.json")
    groups = find_duplicates(apis)
    assert len(groups) == 1
    group = groups[0]
    assert group.domain == "api.example.com"
    assert group.listen_path == "/dp-oauth/"
    assert {api.api_id for api in group.apis} == {"api10", "api11"}


def test_same_path_different_domain_is_not_a_duplicate() -> None:
    apis = _load_apis("cross_domain_no_collision.json")
    assert find_duplicates(apis) == []


def test_internal_apis_excluded_by_default() -> None:
    apis = _load_apis("internal_excluded.json")
    assert find_duplicates(apis) == []


def test_internal_apis_included_when_flagged() -> None:
    apis = _load_apis("internal_excluded.json")
    groups = find_duplicates(apis, include_internal=True)
    assert len(groups) == 1
    assert {api.api_id for api in groups[0].apis} == {"api30", "api31"}


def test_list_internal_surfaces_internal_apis() -> None:
    apis = _load_apis("internal_excluded.json")
    internal = list_internal(apis)
    assert [api.api_id for api in internal] == ["api31"]


@pytest.mark.parametrize("fixture", ["clean.json", "cross_domain_no_collision.json"])
def test_no_internal_apis_in_clean_fixtures(fixture: str) -> None:
    apis = _load_apis(fixture)
    assert list_internal(apis) == []


def test_default_match_mode_is_domain_and_path() -> None:
    apis = _load_apis("same_domain_collision.json")
    assert find_duplicates(apis) == find_duplicates(apis, match_mode=MatchMode.DOMAIN_AND_PATH)


def test_listen_path_only_mode_catches_same_path_different_domain() -> None:
    # This is the /dp-oauth/-shaped case: same listen_path, distinct domain
    # strings that domain-and-path mode (correctly) does not flag but that
    # can still collide at the gateway if the domains are Tyk's overlapping
    # `{?:host1|host2}` multi-domain templates.
    apis = _load_apis("cross_domain_no_collision.json")

    assert find_duplicates(apis, match_mode=MatchMode.LISTEN_PATH_ONLY) != []
    groups = find_duplicates(apis, match_mode=MatchMode.LISTEN_PATH_ONLY)
    assert len(groups) == 1
    group = groups[0]
    assert group.listen_path == "/v1/"
    # Members span two different domains, so the group-level domain is
    # unset — callers must read each ApiSummary's own domain.
    assert group.domain is None
    assert {api.domain for api in group.apis} == {"public.example.com", "staging.example.com"}
    assert {api.api_id for api in group.apis} == {"api20", "api21"}


def test_listen_path_only_mode_still_reports_uniform_domain_when_all_members_share_one() -> None:
    apis = _load_apis("same_domain_collision.json")
    groups = find_duplicates(apis, match_mode=MatchMode.LISTEN_PATH_ONLY)
    assert len(groups) == 1
    assert groups[0].domain == "api.example.com"
    assert {api.api_id for api in groups[0].apis} == {"api10", "api11"}


def test_listen_path_only_mode_still_excludes_internal_by_default() -> None:
    apis = _load_apis("internal_excluded.json")
    assert find_duplicates(apis, match_mode=MatchMode.LISTEN_PATH_ONLY) == []


def test_listen_path_only_mode_includes_internal_when_flagged() -> None:
    apis = _load_apis("internal_excluded.json")
    groups = find_duplicates(
        apis, include_internal=True, match_mode=MatchMode.LISTEN_PATH_ONLY
    )
    assert len(groups) == 1
    assert {api.api_id for api in groups[0].apis} == {"api30", "api31"}
