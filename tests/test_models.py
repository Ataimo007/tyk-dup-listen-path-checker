from tyk_dup_checker.models import DEFAULT_DOMAIN, from_api_definition


def _raw(**overrides: object) -> dict:
    base = {
        "api_definition": {
            "id": "mongoid123",
            "api_id": "apiid456",
            "name": "Test API",
            "domain": "",
            "domain_disabled": False,
            "internal": False,
            "proxy": {"listen_path": "/test/"},
        },
        "is_oas": False,
    }
    base["api_definition"].update(overrides.pop("api_definition", {}))
    base.update(overrides)
    return base


def test_maps_core_fields() -> None:
    summary = from_api_definition(_raw())
    assert summary.mongo_id == "mongoid123"
    assert summary.api_id == "apiid456"
    assert summary.name == "Test API"
    assert summary.listen_path == "/test/"
    assert summary.is_internal is False
    assert summary.is_oas is False


def test_empty_domain_normalizes_to_default() -> None:
    summary = from_api_definition(_raw(api_definition={"domain": ""}))
    assert summary.domain == DEFAULT_DOMAIN


def test_disabled_domain_normalizes_to_default_even_if_domain_string_set() -> None:
    summary = from_api_definition(
        _raw(api_definition={"domain": "was-set.example.com", "domain_disabled": True})
    )
    assert summary.domain == DEFAULT_DOMAIN


def test_active_domain_is_preserved() -> None:
    summary = from_api_definition(
        _raw(api_definition={"domain": "api.example.com", "domain_disabled": False})
    )
    assert summary.domain == "api.example.com"


def test_internal_flag_is_read() -> None:
    summary = from_api_definition(_raw(api_definition={"internal": True}))
    assert summary.is_internal is True


def test_is_oas_read_from_outer_entry() -> None:
    summary = from_api_definition(_raw(is_oas=True))
    assert summary.is_oas is True
