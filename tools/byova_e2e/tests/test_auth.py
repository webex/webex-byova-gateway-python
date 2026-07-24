import os
import stat
from urllib.parse import parse_qs, urlparse

from byova_e2e.auth import (
    OAuthCredentials,
    OAuthTokenStore,
    SCOPES,
    access_token_for_run,
    authorization_url,
    load_local_environment,
)


def test_authorization_url_has_required_scopes_and_callback() -> None:
    credentials = OAuthCredentials("client", "secret", "http://localhost:8765/oauth/callback")

    query = parse_qs(urlparse(authorization_url(credentials, "state-value")).query)

    assert query["client_id"] == ["client"]
    assert query["redirect_uri"] == ["http://localhost:8765/oauth/callback"]
    assert query["scope"] == [" ".join(SCOPES)]
    assert query["state"] == ["state-value"]


def test_token_store_uses_owner_only_permissions(tmp_path) -> None:
    store = OAuthTokenStore(tmp_path / "state" / "token.json")
    store.save({"access_token": "test-token", "expires_at": 9999999999})

    assert store.load() == {"access_token": "test-token", "expires_at": 9999999999}
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_access_token_environment_override_does_not_touch_store(tmp_path, monkeypatch) -> None:
    store = OAuthTokenStore(tmp_path / "missing.json")
    monkeypatch.setenv("BYOVA_E2E_WEBEX_ACCESS_TOKEN", "override-token")

    assert access_token_for_run(store) == "override-token"
    assert not store.path.exists()


def test_local_environment_loads_byova_values_without_overriding_shell(tmp_path, monkeypatch) -> None:
    environment = tmp_path / ".env"
    environment.write_text(
        "BYOVA_E2E_WEBEX_CLIENT_ID=file-client\n"
        "BYOVA_E2E_TEST_USER_EMAIL=tester@example.com\n"
    )
    monkeypatch.setenv("BYOVA_E2E_WEBEX_CLIENT_ID", "shell-client")
    monkeypatch.delenv("BYOVA_E2E_TEST_USER_EMAIL", raising=False)

    load_local_environment(environment)

    assert os.environ["BYOVA_E2E_WEBEX_CLIENT_ID"] == "shell-client"
    assert os.environ["BYOVA_E2E_TEST_USER_EMAIL"] == "tester@example.com"


def test_local_environment_rejects_unrelated_variables(tmp_path) -> None:
    environment = tmp_path / ".env"
    environment.write_text("UNRELATED_VALUE=must-not-load\n")

    try:
        load_local_environment(environment)
    except Exception as error:
        assert "Only BYOVA_E2E" in str(error)
    else:
        raise AssertionError("Expected local environment loader to reject unrelated variables")
