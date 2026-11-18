"""Tests for dual-transport configuration and WebSocket auth composition."""

import logging
from unittest.mock import Mock, patch

import pytest

from main import (
    create_websocket_jwt_validator,
    enabled_transports,
)
from src.auth.jwt_validator import JWKSCache
from src.core.datasource_lifecycle import DEFAULT_WEBSOCKET_SCHEMA_ID
from src.core.transport_profiles import (
    enabled_transport_profiles,
    validate_transport_profiles,
)


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, (True, False)),
        ({"transports": {"mode": "grpc"}}, (True, False)),
        ({"transports": {"mode": "websocket"}}, (False, True)),
        ({"transports": {"mode": "both"}}, (True, True)),
    ],
)
def test_enabled_transports(config, expected):
    assert enabled_transports(config) == expected


def test_unknown_transport_mode_is_rejected():
    with pytest.raises(ValueError, match="grpc, websocket, both"):
        enabled_transports({"transports": {"mode": "other"}})


def test_websocket_validator_uses_independent_schema_and_shared_cache():
    cache = JWKSCache()
    config = {
        "websocket_jwt_validation": {
            "enabled": True,
            "datasource_url": "https://gateway.example.com/ws",
        }
    }
    with patch("main.JWTValidator") as validator_class:
        expected = Mock()
        validator_class.return_value = expected
        result = create_websocket_jwt_validator(
            config, logging.getLogger("test"), cache
        )
    assert result is expected
    validator_class.assert_called_once_with(
        datasource_url="https://gateway.example.com/ws",
        datasource_schema_uuid=DEFAULT_WEBSOCKET_SCHEMA_ID,
        cache_duration_minutes=60,
        jwks_cache=cache,
    )


def test_websocket_validator_requires_datasource_url_when_enabled():
    with pytest.raises(ValueError, match="websocket_jwt_validation.datasource_url"):
        create_websocket_jwt_validator(
            {"websocket_jwt_validation": {"enabled": True}},
            logging.getLogger("test"),
        )


def test_identical_dual_datasource_auth_is_rejected():
    auth = {
        "type": "service_app",
        "client_id_env": "CLIENT_ID",
        "client_secret_env": "CLIENT_SECRET",
    }
    config = {
        "data_source": {"enabled": True, "auth": auth},
        "websocket_data_source": {"enabled": True, "auth": dict(auth)},
    }

    with pytest.raises(ValueError, match="distinct Service App"):
        validate_transport_profiles(
            config,
            enabled_transport_profiles({"transports": {"mode": "both"}}),
        )


def test_distinct_dual_datasource_auth_is_accepted():
    config = {
        "transports": {"mode": "both"},
        "data_source": {
            "enabled": True,
            "id_env": "GRPC_DATASOURCE_ID",
            "auth": {
                "type": "service_app",
                "client_id_env": "GRPC_CLIENT_ID",
            },
        },
        "websocket_data_source": {
            "enabled": True,
            "id_env": "WEBSOCKET_DATASOURCE_ID",
            "auth": {
                "type": "service_app",
                "client_id_env": "WEBSOCKET_CLIENT_ID",
            },
        },
    }

    validate_transport_profiles(config, enabled_transport_profiles(config))


def test_single_transport_does_not_validate_unused_profile():
    config = {
        "transports": {"mode": "grpc"},
        "websocket_jwt_validation": {
            "enabled": True,
            "datasource_url": "https://wrong-for-websocket.example.com/v1/va",
        },
    }

    validate_transport_profiles(config, enabled_transport_profiles(config))


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("https://gateway.example.com", "absolute wss URL"),
        ("wss://gateway.example.com/v1/va", "without /v1/va"),
        ("wss://user@gateway.example.com", "without credentials"),
    ],
)
def test_websocket_profile_rejects_invalid_datasource_origin(url, message):
    config = {
        "transports": {"mode": "websocket"},
        "websocket_jwt_validation": {
            "enabled": True,
            "datasource_url": url,
        },
    }

    with pytest.raises(ValueError, match=message):
        validate_transport_profiles(config, enabled_transport_profiles(config))


def test_websocket_profile_rejects_wrong_schema():
    config = {
        "transports": {"mode": "websocket"},
        "websocket_jwt_validation": {
            "enabled": True,
            "datasource_url": "wss://gateway.example.com",
            "datasource_schema_uuid": "5397013b-7920-4ffc-807c-e8a3e0a18f43",
        },
    }

    with pytest.raises(ValueError, match="official WebSocket schema"):
        validate_transport_profiles(config, enabled_transport_profiles(config))
