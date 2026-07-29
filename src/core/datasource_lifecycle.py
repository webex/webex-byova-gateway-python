"""BYODS data source registration and token-renewal lifecycle."""

from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from webex_byods import (
    AccessTokenProvider,
    OAuthRefreshTokenProvider,
    ServiceAppCredentials,
    StaticAccessTokenProvider,
    WebexDataSourceClient,
    WebexServiceAppTokenProvider,
    decode_jwt_token,
)

DEFAULT_BYOVA_SCHEMA_ID = "5397013b-7920-4ffc-807c-e8a3e0a18f43"


class DataSourceLifecycleError(RuntimeError):
    """Raised when the gateway cannot establish its BYODS data source."""


def _required_environment_value(config: dict[str, Any], key: str) -> str:
    env_name = str(config.get(key, "")).strip()
    if not env_name:
        raise ValueError(f"data_source.auth.{key} must name an environment variable")

    value = os.environ.get(env_name, "")
    if not value:
        raise ValueError(
            f"Required BYODS credential environment variable is not set: {env_name}"
        )
    return value


def create_token_provider(auth_config: dict[str, Any]) -> AccessTokenProvider:
    """Create an SDK token provider from environment-backed configuration."""
    auth_type = str(auth_config.get("type", "oauth_refresh")).strip().lower()

    if auth_type == "static":
        return StaticAccessTokenProvider(
            _required_environment_value(auth_config, "access_token_env")
        )

    if auth_type == "oauth_refresh":
        return OAuthRefreshTokenProvider(
            client_id=_required_environment_value(auth_config, "client_id_env"),
            client_secret=_required_environment_value(auth_config, "client_secret_env"),
            refresh_token=_required_environment_value(auth_config, "refresh_token_env"),
        )

    if auth_type == "service_app":
        personal_auth = auth_config.get("personal_auth")
        if not isinstance(personal_auth, dict):
            raise ValueError(
                "data_source.auth.personal_auth must configure the token provider "
                "used to obtain a service-app token"
            )

        credentials = ServiceAppCredentials(
            app_id=_required_environment_value(auth_config, "app_id_env"),
            client_id=_required_environment_value(auth_config, "client_id_env"),
            client_secret=_required_environment_value(auth_config, "client_secret_env"),
            target_org_id=_required_environment_value(auth_config, "target_org_id_env"),
        )
        return WebexServiceAppTokenProvider(
            credentials=credentials,
            personal_token_provider=create_token_provider(personal_auth),
        )

    raise ValueError(
        "data_source.auth.type must be one of: oauth_refresh, service_app, static"
    )


def create_data_source_lifecycle(
    config: dict[str, Any],
    logger: logging.Logger | None = None,
) -> DataSourceLifecycle | None:
    """Build the configured lifecycle, or return ``None`` when it is disabled."""
    lifecycle_config = config.get("data_source", {})
    if not lifecycle_config.get("enabled", False):
        return None

    lifecycle_config = dict(lifecycle_config)
    jwt_config = config.get("jwt_validation", {})

    configured_url = str(lifecycle_config.get("url", "")).strip()
    jwt_url = str(jwt_config.get("datasource_url", "")).strip()
    data_source_url = configured_url or jwt_url
    if not data_source_url:
        raise ValueError(
            "data_source requires a URL. Configure data_source.url or "
            "jwt_validation.datasource_url."
        )
    if jwt_url and configured_url and jwt_url != configured_url:
        raise ValueError(
            "data_source.url must exactly match jwt_validation.datasource_url"
        )

    configured_schema = str(lifecycle_config.get("schema_id", "")).strip()
    jwt_schema = str(jwt_config.get("datasource_schema_uuid", "")).strip()
    schema_id = configured_schema or jwt_schema or DEFAULT_BYOVA_SCHEMA_ID
    if jwt_schema and configured_schema and jwt_schema != configured_schema:
        raise ValueError(
            "data_source.schema_id must match jwt_validation.datasource_schema_uuid"
        )

    auth_config = lifecycle_config.get("auth")
    if not isinstance(auth_config, dict):
        raise ValueError("data_source.auth must be configured when enabled")

    data_source_id = str(lifecycle_config.get("id", "")).strip()
    data_source_id_env = str(lifecycle_config.get("id_env", "")).strip()
    if not data_source_id and data_source_id_env:
        data_source_id = os.environ.get(data_source_id_env, "").strip()

    lifecycle_config.update(
        {
            "url": data_source_url,
            "schema_id": schema_id,
            "id": data_source_id,
        }
    )
    client = WebexDataSourceClient(token_provider=create_token_provider(auth_config))
    return DataSourceLifecycle(client, lifecycle_config, logger=logger)


class DataSourceLifecycle:
    """Ensure a BYODS data source exists and renew its JWS before expiry."""

    def __init__(
        self,
        client: WebexDataSourceClient,
        config: dict[str, Any],
        *,
        logger: logging.Logger | None = None,
        now: Callable[[], datetime] | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.client = client
        self.logger = logger or logging.getLogger(__name__)
        self.url = str(config.get("url", "")).strip()
        self.schema_id = str(config.get("schema_id", "")).strip()
        self.audience = str(config.get("audience", "BYOVAGateway")).strip()
        self.subject = str(config.get("subject", "callAudioData")).strip()
        self.data_source_id = str(config.get("id", "")).strip() or None
        self.token_lifetime_minutes = int(config.get("token_lifetime_minutes", 1440))
        self.renewal_lead_time_minutes = int(
            config.get("renewal_lead_time_minutes", 60)
        )
        self.retry_interval_seconds = int(config.get("retry_interval_seconds", 60))

        self._now = now or (lambda: datetime.now(timezone.utc))
        self._stop_event = stop_event or threading.Event()
        self._renewal_thread: threading.Thread | None = None
        self._current_data_source: dict[str, Any] | None = None

        self._validate_config()

    @property
    def current_data_source(self) -> dict[str, Any] | None:
        """Return the latest datasource representation received from Webex."""
        return self._current_data_source

    def _validate_config(self) -> None:
        missing = [
            name
            for name, value in (
                ("url", self.url),
                ("schema_id", self.schema_id),
                ("audience", self.audience),
                ("subject", self.subject),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"Missing required data_source configuration: {', '.join(missing)}"
            )
        if not 1 <= self.token_lifetime_minutes <= 1440:
            raise ValueError(
                "data_source.token_lifetime_minutes must be between 1 and 1440"
            )
        if not 0 < self.renewal_lead_time_minutes < self.token_lifetime_minutes:
            raise ValueError(
                "data_source.renewal_lead_time_minutes must be greater than zero "
                "and less than token_lifetime_minutes"
            )
        if self.retry_interval_seconds <= 0:
            raise ValueError(
                "data_source.retry_interval_seconds must be greater than zero"
            )

    def start(self) -> dict[str, Any]:
        """Register or reconcile the data source and start token renewal."""
        if self._renewal_thread and self._renewal_thread.is_alive():
            raise RuntimeError("BYODS data source lifecycle is already running")

        self._stop_event.clear()
        data_source = self._ensure_data_source()
        expires_at = self._token_expiry(data_source)
        delay = (
            self._seconds_until_renewal(data_source) if expires_at is not None else 0.0
        )

        if delay <= 0:
            if expires_at is None:
                self.logger.warning(
                    "BYODS response did not include a parseable token expiry; "
                    "renewing immediately to establish a fresh token"
                )
            data_source = self._renew_token()
            delay = self._seconds_until_renewal(data_source)

        self._renewal_thread = threading.Thread(
            target=self._renewal_loop,
            args=(delay,),
            name="byods-token-renewal",
            daemon=True,
        )
        self._renewal_thread.start()
        return data_source

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the renewal worker without waiting for its scheduled deadline."""
        self._stop_event.set()
        thread = self._renewal_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        self._renewal_thread = None

    def _ensure_data_source(self) -> dict[str, Any]:
        if self.data_source_id:
            details = self._require_success(
                self.client.get_data_source_details(self.data_source_id),
                f"retrieve configured data source {self.data_source_id}",
            )
        else:
            details = self._discover_data_source()

        if details is None:
            details = self._register_data_source()
        elif self._requires_update(details):
            details = self._update_data_source(details)

        self.data_source_id = str(details.get("id", "")).strip() or None
        if not self.data_source_id:
            raise DataSourceLifecycleError(
                "Webex BYODS response did not include a data source ID"
            )

        self._current_data_source = details
        self.logger.info(
            "BYODS data source ready: id=%s url=%s",
            self.data_source_id,
            self.url,
        )
        return details

    def _discover_data_source(self) -> dict[str, Any] | None:
        result = self._require_success(
            self.client.list_all_data_sources(), "list data sources"
        )
        items = result.get("items", [])
        if not isinstance(items, list):
            raise DataSourceLifecycleError(
                "Webex BYODS list response did not contain an items list"
            )

        exact_matches = [
            item for item in items if self._matches_expected_configuration(item)
        ]
        if len(exact_matches) == 1:
            return self._get_details_for_item(exact_matches[0])
        if len(exact_matches) > 1:
            raise DataSourceLifecycleError(
                "Multiple BYODS data sources match this gateway. Configure "
                "data_source.id (or id_env) to select one."
            )

        endpoint_matches = [
            item for item in items if self._matches_endpoint_and_schema(item)
        ]
        if len(endpoint_matches) == 1:
            return self._get_details_for_item(endpoint_matches[0])
        if len(endpoint_matches) > 1:
            raise DataSourceLifecycleError(
                "Multiple BYODS data sources use this gateway URL and schema. "
                "Configure data_source.id (or id_env) to select one."
            )
        return None

    def _get_details_for_item(self, item: dict[str, Any]) -> dict[str, Any]:
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            raise DataSourceLifecycleError(
                "Discovered BYODS data source did not include an ID"
            )
        return self._require_success(
            self.client.get_data_source_details(item_id),
            f"retrieve discovered data source {item_id}",
        )

    def _register_data_source(self) -> dict[str, Any]:
        payload = self._desired_payload()
        self.logger.info("Registering BYODS data source for %s", self.url)
        return self._require_success(
            self.client.register_data_source(payload), "register data source"
        )

    def _update_data_source(self, current: dict[str, Any]) -> dict[str, Any]:
        data_source_id = str(current.get("id", "")).strip()
        if not data_source_id:
            raise DataSourceLifecycleError(
                "Cannot update BYODS data source without an ID"
            )

        self.logger.info(
            "Reconciling BYODS data source configuration: id=%s", data_source_id
        )
        payload = self._desired_payload(status="active")
        return self._require_success(
            self.client.update_data_source(data_source_id, payload),
            f"update data source {data_source_id}",
        )

    def _renew_token(self) -> dict[str, Any]:
        if not self.data_source_id:
            raise DataSourceLifecycleError(
                "Cannot renew BYODS token before a data source is established"
            )

        self.logger.info("Renewing BYODS data source token: id=%s", self.data_source_id)
        result = self._require_success(
            self.client.extend_data_source_token(
                self.data_source_id,
                token_lifetime_minutes=self.token_lifetime_minutes,
            ),
            f"renew data source token {self.data_source_id}",
        )
        self._current_data_source = result
        self.logger.info(
            "BYODS data source token renewed: id=%s expires=%s",
            self.data_source_id,
            result.get("tokenExpiryTime", "unknown"),
        )
        return result

    def _renewal_loop(self, delay: float) -> None:
        next_delay = delay
        while not self._stop_event.wait(max(0.0, next_delay)):
            try:
                data_source = self._renew_token()
                next_delay = self._seconds_until_renewal(data_source)
            except Exception:
                self.logger.exception(
                    "BYODS token renewal failed; retrying in %s seconds",
                    self.retry_interval_seconds,
                )
                next_delay = float(self.retry_interval_seconds)

    def _seconds_until_renewal(self, data_source: dict[str, Any]) -> float:
        expires_at = self._token_expiry(data_source)
        if expires_at is None:
            fallback = (
                self.token_lifetime_minutes - self.renewal_lead_time_minutes
            ) * 60
            self.logger.warning(
                "BYODS response did not include a parseable token expiry; "
                "using a %s-second renewal interval",
                fallback,
            )
            return float(fallback)

        renew_at = expires_at - timedelta(minutes=self.renewal_lead_time_minutes)
        return max(0.0, (renew_at - self._now()).total_seconds())

    @staticmethod
    def _token_expiry(data_source: dict[str, Any]) -> datetime | None:
        expiry_value = data_source.get("tokenExpiryTime")
        if isinstance(expiry_value, str) and expiry_value:
            try:
                parsed = datetime.fromisoformat(expiry_value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                pass

        token = data_source.get("jwsToken") or data_source.get("jwtToken")
        if not token:
            return None
        claims = decode_jwt_token(token)
        expires_at = claims.get("exp")
        if isinstance(expires_at, (int, float)):
            return datetime.fromtimestamp(expires_at, tz=timezone.utc)
        return None

    def _desired_payload(self, *, status: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schemaId": self.schema_id,
            "url": self.url,
            "audience": self.audience,
            "subject": self.subject,
            "nonce": str(uuid.uuid4()),
            "tokenLifetimeMinutes": self.token_lifetime_minutes,
        }
        if status:
            payload["status"] = status
        return payload

    def _matches_endpoint_and_schema(self, data_source: dict[str, Any]) -> bool:
        claims = self._claims(data_source)
        schema_id = data_source.get("schemaId") or claims.get(
            "com.cisco.datasource.schema.uuid"
        )
        return data_source.get("url") == self.url and schema_id == self.schema_id

    def _matches_expected_configuration(self, data_source: dict[str, Any]) -> bool:
        claims = self._claims(data_source)
        return (
            self._matches_endpoint_and_schema(data_source)
            and (data_source.get("audience") or claims.get("aud")) == self.audience
            and (data_source.get("subject") or claims.get("sub")) == self.subject
        )

    def _requires_update(self, data_source: dict[str, Any]) -> bool:
        return (
            not self._matches_expected_configuration(data_source)
            or data_source.get("status", "active") != "active"
        )

    @staticmethod
    def _claims(data_source: dict[str, Any]) -> dict[str, Any]:
        token = data_source.get("jwsToken") or data_source.get("jwtToken")
        return decode_jwt_token(token) if token else {}

    @staticmethod
    def _require_success(result: dict[str, Any], operation: str) -> dict[str, Any]:
        if not result.get("success"):
            status_code = result.get("status_code")
            status_suffix = f" (HTTP {status_code})" if status_code else ""
            raise DataSourceLifecycleError(
                f"Failed to {operation}{status_suffix}: "
                f"{result.get('error', 'unknown error')}"
            )

        data = result.get("data")
        if not isinstance(data, dict):
            raise DataSourceLifecycleError(
                f"Failed to {operation}: response data was not an object"
            )
        return data
