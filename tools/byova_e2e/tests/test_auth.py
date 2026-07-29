import os
import stat
import time
from urllib.parse import parse_qs, urlparse

import pytest
from byova_e2e.auth import (
    SCOPES,
    OAuthCredentials,
    OAuthError,
    OAuthTokenStore,
    access_token_for_run,
    authorization_url,
    complete_login,
    default_token_path,
    load_local_environment,
)


def test_authorization_url_has_required_scopes_and_callback() -> None:
    credentials = OAuthCredentials(
        "client", "secret", "http://localhost:8765/oauth/callback"
    )

    query = parse_qs(urlparse(authorization_url(credentials, "state-value")).query)

    assert query["client_id"] == ["client"]
    assert query["redirect_uri"] == ["http://localhost:8765/oauth/callback"]
    assert query["scope"] == [" ".join(SCOPES)]
    assert query["state"] == ["state-value"]


def test_authorization_url_selects_configured_test_user() -> None:
    credentials = OAuthCredentials(
        "client", "secret", "http://localhost:8765/oauth/callback"
    )

    query = parse_qs(
        urlparse(
            authorization_url(
                credentials,
                "state-value",
                "testcaller@example.com",
            )
        ).query
    )

    assert query["prompt"] == ["select_account"]
    assert query["login_hint"] == ["testcaller@example.com"]


def test_token_store_uses_owner_only_permissions(tmp_path) -> None:
    store = OAuthTokenStore(tmp_path / "state" / "token.json")
    store.save({"access_token": "test-token", "expires_at": 9999999999})

    assert store.load() == {"access_token": "test-token", "expires_at": 9999999999}
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_default_token_path_is_user_level_and_shared_across_worktrees(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("BYOVA_E2E_WEBEX_TOKEN_PATH", raising=False)

    assert default_token_path() == (
        tmp_path / "state" / "byova-e2e" / "oauth-token.json"
    )


def test_default_token_path_honors_explicit_override(tmp_path, monkeypatch) -> None:
    configured_path = tmp_path / "credentials" / "test-user.json"
    monkeypatch.setenv("BYOVA_E2E_WEBEX_TOKEN_PATH", str(configured_path))

    assert default_token_path() == configured_path


def test_token_store_migrates_legacy_worktree_state(tmp_path) -> None:
    legacy_store = OAuthTokenStore(tmp_path / "worktree" / ".state" / "token.json")
    token = {
        "access_token": "legacy-access-token",
        "refresh_token": "legacy-refresh-token",
        "expires_at": 9999999999,
    }
    legacy_store.save(token)
    shared_store = OAuthTokenStore(
        tmp_path / "shared" / "token.json", legacy_path=legacy_store.path
    )

    assert shared_store.load() == token
    assert shared_store.path.is_file()
    assert stat.S_IMODE(shared_store.path.stat().st_mode) == 0o600


def test_access_token_environment_override_does_not_touch_store(
    tmp_path, monkeypatch
) -> None:
    store = OAuthTokenStore(tmp_path / "missing.json")
    monkeypatch.setenv("BYOVA_E2E_WEBEX_ACCESS_TOKEN", "override-token")

    assert access_token_for_run(store) == "override-token"
    assert not store.path.exists()


def test_expired_access_token_uses_and_saves_rotated_refresh_token(
    tmp_path, monkeypatch
) -> None:
    store = OAuthTokenStore(tmp_path / "token.json")
    store.save(
        {
            "access_token": "expired-access-token",
            "refresh_token": "original-refresh-token",
            "expires_at": time.time() - 1,
        }
    )
    monkeypatch.setenv("BYOVA_E2E_WEBEX_CLIENT_ID", "client")
    monkeypatch.setenv("BYOVA_E2E_WEBEX_CLIENT_SECRET", "secret")
    refreshes = []

    def fake_refresh(_credentials, refresh):
        refreshes.append(refresh)
        return {
            "access_token": "new-access-token",
            "refresh_token": "rotated-refresh-token",
            "expires_at": time.time() + 3600,
        }

    monkeypatch.setattr("byova_e2e.auth.refresh_token", fake_refresh)

    assert access_token_for_run(store) == "new-access-token"
    assert refreshes == ["original-refresh-token"]
    assert store.load()["refresh_token"] == "rotated-refresh-token"


def test_refresh_response_without_refresh_token_keeps_previous_token(
    tmp_path, monkeypatch
) -> None:
    store = OAuthTokenStore(tmp_path / "token.json")
    store.save(
        {
            "access_token": "expired-access-token",
            "refresh_token": "reusable-refresh-token",
            "expires_at": time.time() - 1,
        }
    )
    monkeypatch.setenv("BYOVA_E2E_WEBEX_CLIENT_ID", "client")
    monkeypatch.setenv("BYOVA_E2E_WEBEX_CLIENT_SECRET", "secret")
    monkeypatch.setattr(
        "byova_e2e.auth.refresh_token",
        lambda _credentials, _refresh: {
            "access_token": "new-access-token",
            "expires_at": time.time() + 3600,
        },
    )

    assert access_token_for_run(store) == "new-access-token"
    assert store.load()["refresh_token"] == "reusable-refresh-token"


def test_complete_login_persists_access_and_refresh_tokens(
    tmp_path, monkeypatch
) -> None:
    store = OAuthTokenStore(tmp_path / "token.json")
    monkeypatch.setenv("BYOVA_E2E_WEBEX_CLIENT_ID", "client")
    monkeypatch.setenv("BYOVA_E2E_WEBEX_CLIENT_SECRET", "secret")
    monkeypatch.setattr("byova_e2e.auth.OAuthCallbackServer", FakeOAuthCallback)
    monkeypatch.setattr(
        "byova_e2e.auth.exchange_code",
        lambda _credentials, _code: {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_at": time.time() + 3600,
        },
    )

    assert complete_login(store, 30) == str(store.path)
    assert store.load()["refresh_token"] == "refresh-token"


def test_complete_login_rejects_non_refreshable_authorization(
    tmp_path, monkeypatch
) -> None:
    store = OAuthTokenStore(tmp_path / "token.json")
    monkeypatch.setenv("BYOVA_E2E_WEBEX_CLIENT_ID", "client")
    monkeypatch.setenv("BYOVA_E2E_WEBEX_CLIENT_SECRET", "secret")
    monkeypatch.setattr("byova_e2e.auth.OAuthCallbackServer", FakeOAuthCallback)
    monkeypatch.setattr(
        "byova_e2e.auth.exchange_code",
        lambda _credentials, _code: {
            "access_token": "access-token",
            "expires_at": time.time() + 3600,
        },
    )

    with pytest.raises(OAuthError, match="did not contain a refresh token"):
        complete_login(store, 30)

    assert not store.path.exists()


def test_local_environment_loads_byova_values_without_overriding_shell(
    tmp_path, monkeypatch
) -> None:
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
        raise AssertionError(
            "Expected local environment loader to reject unrelated variables"
        )


class FakeOAuthCallback:
    def __init__(self, _redirect_uri) -> None:
        pass

    def start(self) -> None:
        pass

    def wait_for_code(self, _state, _timeout_seconds) -> str:
        return "authorization-code"

    def close(self) -> None:
        pass
