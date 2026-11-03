#!/usr/bin/env python3
"""Transport-aware health probe for container runtimes."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, Mapping
from urllib.request import ProxyHandler, build_opener

import grpc
import yaml
from grpc_health.v1 import health_pb2, health_pb2_grpc

# Docker and ECS invoke this file by path, which otherwise places only
# ``src/runtime`` on ``sys.path`` rather than the application root.
APPLICATION_ROOT = Path(__file__).resolve().parents[2]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

Probe = Callable[[int], bool]


def _configured_port(environment: Mapping[str, str], name: str, default: int) -> int:
    try:
        port = int(environment.get(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be a valid port") from error
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return port


def probe_grpc(port: int) -> bool:
    """Check the exact unauthenticated gRPC health method used by the ALB."""
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            response = health_pb2_grpc.HealthStub(channel).Check(
                health_pb2.HealthCheckRequest(), timeout=3
            )
        return response.status == health_pb2.HealthCheckResponse.SERVING
    except grpc.RpcError:
        return False


def probe_websocket(port: int) -> bool:
    """Check the WebSocket listener's dedicated HTTP process-health route."""
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/health", timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def gateway_is_healthy(
    *,
    environment: Mapping[str, str] | None = None,
    grpc_probe: Probe = probe_grpc,
    websocket_probe: Probe = probe_websocket,
) -> bool:
    """Probe only selected transports, honoring dual partial-startup semantics."""
    from src.core.transport_profiles import enabled_transport_profiles

    values = environment if environment is not None else os.environ
    config_path = Path(values.get("GATEWAY_CONFIG", "config/config.yaml"))
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            return False
        profiles = enabled_transport_profiles(config)
        results = []
        for profile in profiles:
            if profile.name == "grpc":
                port = _configured_port(
                    values,
                    "PORT",
                    int(config.get("gateway", {}).get("port", 50051)),
                )
                results.append(grpc_probe(port))
            else:
                websocket_config = config.get("transports", {}).get("websocket", {})
                port = _configured_port(
                    values,
                    "WEBSOCKET_PORT",
                    int(websocket_config.get("port", 8765)),
                )
                results.append(websocket_probe(port))

        allow_partial = len(results) > 1 and bool(
            config.get("transports", {}).get(
                "allow_partial_transport_startup", False
            )
        )
        return any(results) if allow_partial else all(results)
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        return False


def main() -> None:
    raise SystemExit(0 if gateway_is_healthy() else 1)


if __name__ == "__main__":
    main()
