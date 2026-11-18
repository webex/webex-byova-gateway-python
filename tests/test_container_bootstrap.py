"""Tests for the ECS container's private runtime-file bootstrap."""

import io
import json
import stat

import pytest

from src.runtime.container_bootstrap import (
    download_runtime_object,
    download_runtime_secret,
    parse_s3_uri,
    prepare_runtime_files,
    validate_gateway_config,
    validate_google_external_account,
    validate_google_service_account,
)


class FakeS3Client:
    def __init__(self, objects: dict[tuple[str, str], bytes]) -> None:
        self.objects = objects
        self.requests: list[tuple[str, str]] = []

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        self.requests.append((Bucket, Key))
        payload = self.objects[(Bucket, Key)]
        return {"ContentLength": len(payload), "Body": io.BytesIO(payload)}


class FakeSecretsClient:
    def __init__(self, secrets: dict[str, str]) -> None:
        self.secrets = secrets
        self.requests: list[str] = []

    def get_secret_value(self, *, SecretId: str) -> dict:
        self.requests.append(SecretId)
        return {"SecretString": self.secrets[SecretId]}


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.com/config.yaml",
        "s3://",
        "s3://bucket",
        "s3:///config.yaml",
        "s3://bucket/config.yaml?versionId=unexpected",
        "s3://bucket/config.yaml#fragment",
    ],
)
def test_parse_s3_uri_rejects_ambiguous_or_non_s3_locations(uri: str) -> None:
    with pytest.raises(ValueError, match="S3 URI"):
        parse_s3_uri(uri)


def test_download_runtime_object_validates_before_atomic_write(tmp_path) -> None:
    destination = tmp_path / "config.yaml"
    client = FakeS3Client({("private-bucket", "dev/config.yaml"): b"[]"})

    with pytest.raises(ValueError, match="mapping"):
        download_runtime_object(
            "s3://private-bucket/dev/config.yaml",
            destination,
            max_bytes=1024,
            validator=validate_gateway_config,
            s3_client=client,
        )

    assert not destination.exists()


def test_download_runtime_object_rejects_oversize_payload(tmp_path) -> None:
    destination = tmp_path / "config.yaml"
    client = FakeS3Client({("private-bucket", "dev/config.yaml"): b"x" * 33})

    with pytest.raises(ValueError, match="exceeds"):
        download_runtime_object(
            "s3://private-bucket/dev/config.yaml",
            destination,
            max_bytes=32,
            validator=validate_gateway_config,
            s3_client=client,
        )

    assert not destination.exists()


def test_google_credentials_must_use_external_account_workload_identity() -> None:
    service_account = json.dumps(
        {"type": "service_account", "private_key": "do-not-write-this"}
    ).encode()

    with pytest.raises(ValueError, match="external_account"):
        validate_google_external_account(service_account)


def test_google_service_account_requires_complete_key_profile() -> None:
    with pytest.raises(ValueError, match="missing required fields"):
        validate_google_service_account(
            json.dumps(
                {"type": "service_account", "client_email": "agent@example.com"}
            ).encode()
        )


def test_download_runtime_secret_installs_validated_private_file(tmp_path) -> None:
    destination = tmp_path / "google-service-account.json"
    secret_arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:example"
    service_account = json.dumps(
        {
            "type": "service_account",
            "project_id": "example-project",
            "private_key_id": "key-id",
            "private_key": "-----BEGIN PRIVATE KEY-----\nexample\n",
            "client_email": "agent@example.iam.gserviceaccount.com",
            "client_id": "client-id",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
    client = FakeSecretsClient({secret_arn: service_account})

    download_runtime_secret(
        secret_arn,
        destination,
        max_bytes=1024,
        validator=validate_google_service_account,
        secrets_client=client,
    )

    assert destination.read_text(encoding="utf-8") == service_account
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert client.requests == [secret_arn]


def test_prepare_runtime_files_rejects_multiple_google_credential_sources(
    tmp_path,
) -> None:
    environment = {
        "GOOGLE_EXTERNAL_ACCOUNT_S3_URI": "s3://private-bucket/dev/google-wif.json",
        "GOOGLE_SERVICE_ACCOUNT_SECRET_ARN": (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:example"
        ),
    }

    with pytest.raises(ValueError, match="not both"):
        prepare_runtime_files(environ=environment, runtime_directory=tmp_path)


def test_prepare_runtime_files_sets_service_account_from_secret(tmp_path) -> None:
    secret_arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:example"
    service_account = json.dumps(
        {
            "type": "service_account",
            "project_id": "example-project",
            "private_key_id": "key-id",
            "private_key": "-----BEGIN PRIVATE KEY-----\nexample\n",
            "client_email": "agent@example.iam.gserviceaccount.com",
            "client_id": "client-id",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
    client = FakeSecretsClient({secret_arn: service_account})
    environment = {"GOOGLE_SERVICE_ACCOUNT_SECRET_ARN": secret_arn}

    prepare_runtime_files(
        environ=environment,
        runtime_directory=tmp_path,
        secrets_client=client,
    )

    google_path = tmp_path / "google-service-account.json"
    assert environment["GOOGLE_APPLICATION_CREDENTIALS"] == str(google_path)
    assert google_path.read_text(encoding="utf-8") == service_account
    assert stat.S_IMODE(google_path.stat().st_mode) == 0o600
    assert client.requests == [secret_arn]


def test_prepare_runtime_files_sets_private_paths(tmp_path) -> None:
    gateway_config = b"gateway:\n  port: 50051\n"
    google_config = json.dumps(
        {
            "type": "external_account",
            "audience": "example-audience",
            "subject_token_type": "urn:ietf:params:aws:token-type:aws4_request",
            "token_url": "https://sts.googleapis.com/v1/token",
            "credential_source": {"environment_id": "aws1"},
        }
    ).encode()
    client = FakeS3Client(
        {
            ("private-bucket", "dev/config.yaml"): gateway_config,
            ("private-bucket", "dev/google-wif.json"): google_config,
        }
    )
    environment = {
        "GATEWAY_CONFIG_S3_URI": "s3://private-bucket/dev/config.yaml",
        "GOOGLE_EXTERNAL_ACCOUNT_S3_URI": ("s3://private-bucket/dev/google-wif.json"),
    }

    prepare_runtime_files(
        environ=environment,
        runtime_directory=tmp_path,
        s3_client=client,
    )

    config_path = tmp_path / "config.yaml"
    google_path = tmp_path / "google-external-account.json"
    assert environment["GATEWAY_CONFIG"] == str(config_path)
    assert environment["GOOGLE_APPLICATION_CREDENTIALS"] == str(google_path)
    assert config_path.read_bytes() == gateway_config
    assert google_path.read_bytes() == google_config
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(google_path.stat().st_mode) == 0o600
    assert client.requests == [
        ("private-bucket", "dev/config.yaml"),
        ("private-bucket", "dev/google-wif.json"),
    ]
