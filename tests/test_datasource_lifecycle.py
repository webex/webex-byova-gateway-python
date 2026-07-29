"""Tests for BYODS datasource startup registration and token renewal."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, call

import pytest

from src.core.datasource_lifecycle import (
    DataSourceLifecycle,
    DataSourceLifecycleError,
    create_data_source_lifecycle,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
SCHEMA_ID = "5397013b-7920-4ffc-807c-e8a3e0a18f43"
URL = "https://gateway.example.com"


def lifecycle_config(**overrides):
    config = {
        "url": URL,
        "schema_id": SCHEMA_ID,
        "audience": "BYOVAGateway",
        "subject": "callAudioData",
        "token_lifetime_minutes": 1440,
        "renewal_lead_time_minutes": 60,
        "retry_interval_seconds": 10,
    }
    config.update(overrides)
    return config


def data_source(
    *,
    data_source_id="source-1",
    expires_at=None,
    audience="BYOVAGateway",
    subject="callAudioData",
    status="active",
):
    return {
        "id": data_source_id,
        "url": URL,
        "schemaId": SCHEMA_ID,
        "audience": audience,
        "subject": subject,
        "status": status,
        "tokenExpiryTime": (expires_at or NOW + timedelta(hours=24))
        .isoformat()
        .replace("+00:00", "Z"),
    }


def success(data):
    return {"success": True, "data": data, "status_code": 200}


def test_factory_returns_none_when_management_is_disabled():
    assert create_data_source_lifecycle({"data_source": {"enabled": False}}) is None


def test_factory_reuses_jwt_url_and_schema(monkeypatch):
    monkeypatch.setenv("BYODS_TOKEN", "secret-token")
    config = {
        "jwt_validation": {
            "datasource_url": URL,
            "datasource_schema_uuid": SCHEMA_ID,
        },
        "data_source": {
            "enabled": True,
            "auth": {
                "type": "static",
                "access_token_env": "BYODS_TOKEN",
            },
        },
    }

    lifecycle = create_data_source_lifecycle(config)

    assert lifecycle is not None
    assert lifecycle.url == URL
    assert lifecycle.schema_id == SCHEMA_ID


def test_factory_rejects_url_that_differs_from_jwt_validation(monkeypatch):
    monkeypatch.setenv("BYODS_TOKEN", "secret-token")
    config = {
        "jwt_validation": {"datasource_url": URL},
        "data_source": {
            "enabled": True,
            "url": "https://other.example.com",
            "auth": {
                "type": "static",
                "access_token_env": "BYODS_TOKEN",
            },
        },
    }

    with pytest.raises(ValueError, match="must exactly match"):
        create_data_source_lifecycle(config)


def test_start_registers_when_no_matching_data_source_exists():
    client = Mock()
    registered = data_source()
    client.list_all_data_sources.return_value = success({"items": []})
    client.register_data_source.return_value = {
        "success": True,
        "data": registered,
        "status_code": 201,
    }
    lifecycle = DataSourceLifecycle(client, lifecycle_config(), now=lambda: NOW)

    result = lifecycle.start()
    lifecycle.stop()

    assert result == registered
    payload = client.register_data_source.call_args.args[0]
    assert payload["schemaId"] == SCHEMA_ID
    assert payload["url"] == URL
    assert payload["audience"] == "BYOVAGateway"
    assert payload["subject"] == "callAudioData"
    assert payload["tokenLifetimeMinutes"] == 1440
    assert payload["nonce"]
    client.update_data_source.assert_not_called()
    client.extend_data_source_token.assert_not_called()


def test_start_discovers_existing_data_source_without_creating_duplicate():
    client = Mock()
    existing = data_source()
    client.list_all_data_sources.return_value = success({"items": [existing]})
    client.get_data_source_details.return_value = success(existing)
    lifecycle = DataSourceLifecycle(client, lifecycle_config(), now=lambda: NOW)

    lifecycle.start()
    lifecycle.stop()

    client.get_data_source_details.assert_called_once_with("source-1")
    client.register_data_source.assert_not_called()
    client.update_data_source.assert_not_called()


def test_start_reconciles_configuration_drift():
    client = Mock()
    drifted = data_source(audience="old-audience", status="disabled")
    updated = data_source()
    client.list_all_data_sources.return_value = success({"items": [drifted]})
    client.get_data_source_details.return_value = success(drifted)
    client.update_data_source.return_value = success(updated)
    lifecycle = DataSourceLifecycle(client, lifecycle_config(), now=lambda: NOW)

    lifecycle.start()
    lifecycle.stop()

    update_id, payload = client.update_data_source.call_args.args
    assert update_id == "source-1"
    assert payload["audience"] == "BYOVAGateway"
    assert payload["status"] == "active"
    assert payload["nonce"]
    client.register_data_source.assert_not_called()


def test_start_renews_immediately_when_token_is_inside_lead_time():
    client = Mock()
    expiring = data_source(expires_at=NOW + timedelta(minutes=30))
    renewed = data_source(expires_at=NOW + timedelta(hours=24))
    client.get_data_source_details.return_value = success(expiring)
    client.extend_data_source_token.return_value = success(renewed)
    lifecycle = DataSourceLifecycle(
        client,
        lifecycle_config(id="source-1"),
        now=lambda: NOW,
    )

    result = lifecycle.start()
    lifecycle.stop()

    assert result == renewed
    client.extend_data_source_token.assert_called_once_with(
        "source-1", token_lifetime_minutes=1440
    )


def test_start_renews_immediately_when_expiry_is_missing():
    client = Mock()
    current = data_source()
    current.pop("tokenExpiryTime")
    renewed = data_source(expires_at=NOW + timedelta(hours=24))
    client.get_data_source_details.return_value = success(current)
    client.extend_data_source_token.return_value = success(renewed)
    lifecycle = DataSourceLifecycle(
        client,
        lifecycle_config(id="source-1"),
        now=lambda: NOW,
    )

    lifecycle.start()
    lifecycle.stop()

    client.extend_data_source_token.assert_called_once_with(
        "source-1", token_lifetime_minutes=1440
    )


def test_start_fails_when_configured_data_source_cannot_be_retrieved():
    client = Mock()
    client.get_data_source_details.return_value = {
        "success": False,
        "error": "not found",
        "status_code": 404,
    }
    lifecycle = DataSourceLifecycle(
        client, lifecycle_config(id="missing"), now=lambda: NOW
    )

    with pytest.raises(
        DataSourceLifecycleError, match="retrieve configured data source"
    ):
        lifecycle.start()


def test_renewal_loop_waits_until_deadline_then_renews():
    client = Mock()
    renewed = data_source(expires_at=NOW + timedelta(hours=24))
    client.extend_data_source_token.return_value = success(renewed)
    stop_event = Mock()
    stop_event.wait.side_effect = [False, True]
    lifecycle = DataSourceLifecycle(
        client,
        lifecycle_config(id="source-1"),
        now=lambda: NOW,
        stop_event=stop_event,
    )

    lifecycle._renewal_loop(300)

    client.extend_data_source_token.assert_called_once_with(
        "source-1", token_lifetime_minutes=1440
    )
    assert stop_event.wait.call_args_list == [call(300), call(23 * 60 * 60)]


def test_renewal_loop_retries_after_sdk_failure():
    client = Mock()
    client.extend_data_source_token.return_value = {
        "success": False,
        "error": "temporary failure",
        "status_code": 503,
    }
    stop_event = Mock()
    stop_event.wait.side_effect = [False, True]
    lifecycle = DataSourceLifecycle(
        client,
        lifecycle_config(id="source-1", retry_interval_seconds=10),
        now=lambda: NOW,
        stop_event=stop_event,
        logger=Mock(),
    )

    lifecycle._renewal_loop(300)

    assert stop_event.wait.call_args_list == [call(300), call(10.0)]


@pytest.mark.parametrize(
    ("token_lifetime", "lead_time"),
    [(0, 1), (1441, 1), (60, 0), (60, 60), (60, 61)],
)
def test_invalid_renewal_configuration_is_rejected(token_lifetime, lead_time):
    with pytest.raises(ValueError):
        DataSourceLifecycle(
            Mock(),
            lifecycle_config(
                token_lifetime_minutes=token_lifetime,
                renewal_lead_time_minutes=lead_time,
            ),
        )
