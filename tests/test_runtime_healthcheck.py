"""Tests for transport-aware ECS container health checks."""

import yaml

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
