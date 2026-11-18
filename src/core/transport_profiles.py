"""Transport selection and datasource-binding validation.

Each enabled transport is independently deployable. Dual-protocol mode composes
the two profiles; it does not merge their Webex Service App or datasource
identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

GRPC_SCHEMA_ID = "5397013b-7920-4ffc-807c-e8a3e0a18f43"
WEBSOCKET_SCHEMA_ID = "a38a10b7-43e4-4676-a076-a7d6dce9387d"


@dataclass(frozen=True)
class TransportProfile:
    """Configuration bindings owned by one externally visible transport."""

    name: str
    datasource_section: str
    jwt_section: str
    default_schema_id: str


GRPC_PROFILE = TransportProfile(
    name="grpc",
    datasource_section="data_source",
    jwt_section="jwt_validation",
    default_schema_id=GRPC_SCHEMA_ID,
)
WEBSOCKET_PROFILE = TransportProfile(
    name="websocket",
    datasource_section="websocket_data_source",
    jwt_section="websocket_jwt_validation",
    default_schema_id=WEBSOCKET_SCHEMA_ID,
)


def enabled_transport_profiles(config: dict[str, Any]) -> tuple[TransportProfile, ...]:
    """Return enabled transport profiles, preserving the legacy gRPC default."""
    transport_config = config.get("transports")
    if transport_config is None:
        return (GRPC_PROFILE,)
    if not isinstance(transport_config, dict):
        raise ValueError("transports configuration must be a dictionary")

    mode = str(transport_config.get("mode", "grpc")).strip().lower()
    if mode == "grpc":
        return (GRPC_PROFILE,)
    if mode == "websocket":
        return (WEBSOCKET_PROFILE,)
    if mode == "both":
        return (GRPC_PROFILE, WEBSOCKET_PROFILE)
    raise ValueError("transports.mode must be one of: grpc, websocket, both")


def validate_transport_profiles(
    config: dict[str, Any], profiles: tuple[TransportProfile, ...]
) -> None:
    """Validate only enabled transports and enforce dual identity isolation."""
    for profile in profiles:
        _validate_external_url(config, profile)
        _validate_websocket_schema(config, profile)

    if len(profiles) < 2:
        return

    grpc_config = config.get(GRPC_PROFILE.datasource_section, {})
    websocket_config = config.get(WEBSOCKET_PROFILE.datasource_section, {})
    if not (
        isinstance(grpc_config, dict)
        and isinstance(websocket_config, dict)
        and grpc_config.get("enabled", False)
        and websocket_config.get("enabled", False)
    ):
        return

    grpc_auth = grpc_config.get("auth")
    websocket_auth = websocket_config.get("auth")
    if isinstance(grpc_auth, dict) and grpc_auth == websocket_auth:
        raise ValueError(
            "gRPC and WebSocket datasource management must use distinct Service "
            "App credential mappings"
        )

    grpc_id = str(grpc_config.get("id", "")).strip()
    websocket_id = str(websocket_config.get("id", "")).strip()
    if grpc_id and grpc_id == websocket_id:
        raise ValueError(
            "gRPC and WebSocket datasource management must use distinct datasource IDs"
        )

    grpc_id_env = str(grpc_config.get("id_env", "")).strip()
    websocket_id_env = str(websocket_config.get("id_env", "")).strip()
    if grpc_id_env and grpc_id_env == websocket_id_env:
        raise ValueError(
            "gRPC and WebSocket datasource management must use distinct datasource "
            "ID environment variables"
        )


def _validate_external_url(config: dict[str, Any], profile: TransportProfile) -> None:
    datasource_config = config.get(profile.datasource_section, {})
    jwt_config = config.get(profile.jwt_section, {})
    if not isinstance(datasource_config, dict) or not isinstance(jwt_config, dict):
        raise ValueError(f"{profile.name} transport profiles must be dictionaries")

    if not (
        datasource_config.get("enabled", False)
        or jwt_config.get("enabled", False)
    ):
        return

    configured_url = str(datasource_config.get("url", "")).strip()
    jwt_url = str(jwt_config.get("datasource_url", "")).strip()
    url = configured_url or jwt_url
    if not url:
        return

    parsed = urlsplit(url)
    expected_scheme = "wss" if profile.name == "websocket" else "https"
    if (
        parsed.scheme.lower() != expected_scheme
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"{profile.name} datasource URL must be an absolute "
            f"{expected_scheme} URL without credentials, query, or fragment"
        )
    if profile.name == "websocket" and parsed.path not in ("", "/"):
        raise ValueError(
            "WebSocket datasource URL must be the wss origin without /v1/va "
            "or another path"
        )


def _validate_websocket_schema(
    config: dict[str, Any], profile: TransportProfile
) -> None:
    if profile.name != "websocket":
        return
    datasource_config = config.get(profile.datasource_section, {})
    jwt_config = config.get(profile.jwt_section, {})
    if not isinstance(datasource_config, dict) or not isinstance(jwt_config, dict):
        return

    for field_name, value in (
        (
            f"{profile.datasource_section}.schema_id",
            datasource_config.get("schema_id"),
        ),
        (
            f"{profile.jwt_section}.datasource_schema_uuid",
            jwt_config.get("datasource_schema_uuid"),
        ),
    ):
        configured_schema = str(value or "").strip()
        if configured_schema and configured_schema != WEBSOCKET_SCHEMA_ID:
            raise ValueError(
                f"{field_name} must use the official WebSocket schema "
                f"{WEBSOCKET_SCHEMA_ID}"
            )
