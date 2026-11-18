#!/usr/bin/env python3
"""Prepare private runtime files, then replace this process with the gateway."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import boto3
import yaml

RUNTIME_DIRECTORY = Path("/tmp/byova")
MAX_GATEWAY_CONFIG_BYTES = 1024 * 1024
MAX_GOOGLE_EXTERNAL_ACCOUNT_BYTES = 256 * 1024
MAX_GOOGLE_SERVICE_ACCOUNT_BYTES = 256 * 1024
S3_BUCKET_PATTERN = re.compile(
    r"^(?=.{3,63}$)(?!xn--)(?!sthree-)(?!amzn_s3_demo_)[a-z0-9]"
    r"(?:[a-z0-9.-]*[a-z0-9])$"
)


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """Return an unambiguous bucket/key pair for an ``s3://`` URI."""
    parsed = urlsplit(uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if (
        parsed.scheme != "s3"
        or not bucket
        or not key
        or parsed.query
        or parsed.fragment
        or not S3_BUCKET_PATTERN.fullmatch(bucket)
    ):
        raise ValueError("runtime object location must be an unambiguous S3 URI")
    return bucket, key


def validate_gateway_config(payload: bytes) -> None:
    """Reject malformed or non-mapping gateway configuration."""
    config = yaml.safe_load(payload)
    if not isinstance(config, dict):
        raise ValueError("gateway configuration must be a YAML mapping")


def validate_google_external_account(payload: bytes) -> None:
    """Allow workload identity configuration, never a private service key."""
    try:
        config = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(
            "Google external_account configuration is invalid JSON"
        ) from error
    if not isinstance(config, dict) or config.get("type") != "external_account":
        raise ValueError(
            "Google credentials must use an external_account workload identity"
        )
    if any(key in config for key in ("private_key", "private_key_id")):
        raise ValueError(
            "Google external_account configuration cannot contain a private key"
        )
    credential_source = config.get("credential_source")
    if not isinstance(credential_source, dict):
        raise ValueError("Google external_account credential_source is required")


def validate_google_service_account(payload: bytes) -> None:
    """Validate the explicitly configured dev service-account fallback."""
    try:
        config = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Google service-account credentials are invalid JSON") from error
    if not isinstance(config, dict) or config.get("type") != "service_account":
        raise ValueError("Google credentials must use a service_account profile")
    required = (
        "project_id",
        "private_key_id",
        "private_key",
        "client_email",
        "client_id",
        "token_uri",
    )
    missing = [
        key for key in required if not isinstance(config.get(key), str) or not config[key]
    ]
    if missing:
        raise ValueError(
            "Google service-account credentials are missing required fields: "
            + ", ".join(missing)
        )
    if not config["private_key"].startswith("-----BEGIN PRIVATE KEY-----"):
        raise ValueError("Google service-account private_key is malformed")


def _install_private_file(payload: bytes, destination: Path) -> None:
    """Atomically install validated private data with owner-only permissions."""
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_path, destination)
        destination.chmod(0o600)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise


def download_runtime_object(
    uri: str,
    destination: Path,
    *,
    max_bytes: int,
    validator: Callable[[bytes], None],
    s3_client: Any | None = None,
) -> None:
    """Download, validate, and atomically install one private runtime object."""
    bucket, key = parse_s3_uri(uri)
    client = s3_client or boto3.client("s3")
    response = client.get_object(Bucket=bucket, Key=key)
    declared_size = response.get("ContentLength")
    if isinstance(declared_size, int) and declared_size > max_bytes:
        raise ValueError(f"runtime object exceeds the {max_bytes}-byte limit")

    body = response["Body"]
    try:
        payload = body.read(max_bytes + 1)
    finally:
        close = getattr(body, "close", None)
        if close:
            close()
    if len(payload) > max_bytes:
        raise ValueError(f"runtime object exceeds the {max_bytes}-byte limit")
    validator(payload)

    _install_private_file(payload, destination)


def download_runtime_secret(
    secret_arn: str,
    destination: Path,
    *,
    max_bytes: int,
    validator: Callable[[bytes], None],
    secrets_client: Any | None = None,
) -> None:
    """Fetch, validate, and atomically install one Secrets Manager value."""
    client = secrets_client or boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)
    secret_string = response.get("SecretString")
    if not isinstance(secret_string, str):
        raise ValueError("runtime secret must contain a SecretString")
    payload = secret_string.encode("utf-8")
    if len(payload) > max_bytes:
        raise ValueError(f"runtime secret exceeds the {max_bytes}-byte limit")
    validator(payload)
    _install_private_file(payload, destination)


def prepare_runtime_files(
    *,
    environ: MutableMapping[str, str] | None = None,
    runtime_directory: Path = RUNTIME_DIRECTORY,
    s3_client: Any | None = None,
    secrets_client: Any | None = None,
) -> None:
    """Materialize private configuration and Google credential files."""
    environment = environ if environ is not None else os.environ
    gateway_config_uri = environment.get("GATEWAY_CONFIG_S3_URI", "").strip()
    if gateway_config_uri:
        gateway_config_path = runtime_directory / "config.yaml"
        download_runtime_object(
            gateway_config_uri,
            gateway_config_path,
            max_bytes=MAX_GATEWAY_CONFIG_BYTES,
            validator=validate_gateway_config,
            s3_client=s3_client,
        )
        environment["GATEWAY_CONFIG"] = str(gateway_config_path)

    google_external_account_uri = environment.get(
        "GOOGLE_EXTERNAL_ACCOUNT_S3_URI", ""
    ).strip()
    google_service_account_secret_arn = environment.get(
        "GOOGLE_SERVICE_ACCOUNT_SECRET_ARN", ""
    ).strip()
    if google_external_account_uri and google_service_account_secret_arn:
        raise ValueError(
            "configure either Google workload identity or the dev service-account "
            "fallback, not both"
        )
    if google_external_account_uri:
        google_config_path = runtime_directory / "google-external-account.json"
        download_runtime_object(
            google_external_account_uri,
            google_config_path,
            max_bytes=MAX_GOOGLE_EXTERNAL_ACCOUNT_BYTES,
            validator=validate_google_external_account,
            s3_client=s3_client,
        )
        environment["GOOGLE_APPLICATION_CREDENTIALS"] = str(google_config_path)
    elif google_service_account_secret_arn:
        google_config_path = runtime_directory / "google-service-account.json"
        download_runtime_secret(
            google_service_account_secret_arn,
            google_config_path,
            max_bytes=MAX_GOOGLE_SERVICE_ACCOUNT_BYTES,
            validator=validate_google_service_account,
            secrets_client=secrets_client,
        )
        environment["GOOGLE_APPLICATION_CREDENTIALS"] = str(google_config_path)


def main() -> None:
    """Prepare runtime files and exec the gateway as PID 1's child."""
    prepare_runtime_files()
    repository_root = Path(__file__).resolve().parents[2]
    gateway = repository_root / "main.py"
    os.execv(sys.executable, [sys.executable, str(gateway)])


if __name__ == "__main__":
    main()
