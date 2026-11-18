"""Tests for transport-aware ECS container health checks."""

import io

import pytest
import yaml

from src.runtime import container_bootstrap
from src.runtime.healthcheck import gateway_is_healthy


def write_config(tmp_path, config):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def test_grpc_only_probes_only_grpc(tmp_path):
    config_path = write_config(tmp_path, {"transports": {"mode": "grpc"}})
    calls = []

    healthy = gateway_is_healthy(
        environment={"GATEWAY_CONFIG": str(config_path), "PORT": "55051"},
        grpc_probe=lambda port: calls.append(("grpc", port)) or True,
        websocket_probe=lambda port: calls.append(("websocket", port)) or False,
    )

    assert healthy is True
    assert calls == [("grpc", 55051)]


def test_websocket_only_probes_only_websocket(tmp_path):
    config_path = write_config(
        tmp_path,
        {
            "transports": {
                "mode": "websocket",
                "websocket": {"port": 58765},
            }
        },
    )
    calls = []

    healthy = gateway_is_healthy(
        environment={"GATEWAY_CONFIG": str(config_path)},
        grpc_probe=lambda port: calls.append(("grpc", port)) or False,
        websocket_probe=lambda port: calls.append(("websocket", port)) or True,
    )

    assert healthy is True
    assert calls == [("websocket", 58765)]


def test_dual_atomic_health_requires_both_transports(tmp_path):
    config_path = write_config(
        tmp_path,
        {
            "transports": {
                "mode": "both",
                "allow_partial_transport_startup": False,
            }
        },
    )

    assert (
        gateway_is_healthy(
            environment={"GATEWAY_CONFIG": str(config_path)},
            grpc_probe=lambda _port: True,
            websocket_probe=lambda _port: False,
        )
        is False
    )


def test_dual_partial_health_accepts_one_ready_transport(tmp_path):
    config_path = write_config(
        tmp_path,
        {
            "transports": {
                "mode": "both",
                "allow_partial_transport_startup": True,
            }
        },
    )

    assert (
        gateway_is_healthy(
            environment={"GATEWAY_CONFIG": str(config_path)},
            grpc_probe=lambda _port: True,
            websocket_probe=lambda _port: False,
        )
        is True
    )


def test_invalid_selected_port_fails_healthcheck(tmp_path):
    config_path = write_config(tmp_path, {"transports": {"mode": "websocket"}})

    assert (
        gateway_is_healthy(
            environment={
                "GATEWAY_CONFIG": str(config_path),
                "WEBSOCKET_PORT": "not-a-port",
            }
        )
        is False
    )


@pytest.mark.parametrize("mode", ["grpc", "websocket", "both"])
def test_healthcheck_uses_downloaded_config_with_original_container_environment(
    tmp_path, monkeypatch, mode
):
    bundled_config = write_config(tmp_path, {"transports": {"mode": "grpc"}})
    runtime_directory = tmp_path / "runtime"
    monkeypatch.setattr(container_bootstrap, "RUNTIME_DIRECTORY", runtime_directory)
    payload = yaml.safe_dump({"transports": {"mode": mode}}).encode()

    class FakeS3:
        def get_object(self, **_kwargs):
            return {"Body": io.BytesIO(payload)}

    container_environment = {
        "GATEWAY_CONFIG": str(bundled_config),
        "GATEWAY_CONFIG_S3_URI": "s3://example-bucket/config.yaml",
    }
    gateway_environment = dict(container_environment)
    container_bootstrap.prepare_runtime_files(
        environ=gateway_environment,
        runtime_directory=runtime_directory,
        s3_client=FakeS3(),
    )
    calls = []
    healthy = gateway_is_healthy(
        environment=container_environment,
        grpc_probe=lambda port: calls.append(("grpc", port)) or True,
        websocket_probe=lambda port: calls.append(("websocket", port)) or True,
    )

    assert (
        gateway_environment["GATEWAY_CONFIG"] != container_environment["GATEWAY_CONFIG"]
    )
    assert healthy is True
    assert (
        calls
        == {
            "grpc": [("grpc", 50051)],
            "websocket": [("websocket", 8765)],
            "both": [("grpc", 50051), ("websocket", 8765)],
        }[mode]
    )


def test_missing_downloaded_config_fails_healthcheck(tmp_path, monkeypatch):
    bundled_config = write_config(tmp_path, {"transports": {"mode": "grpc"}})
    monkeypatch.setattr(container_bootstrap, "RUNTIME_DIRECTORY", tmp_path / "missing")

    assert not gateway_is_healthy(
        environment={
            "GATEWAY_CONFIG": str(bundled_config),
            "GATEWAY_CONFIG_S3_URI": "s3://example-bucket/config.yaml",
        },
        grpc_probe=lambda _port: True,
    )
