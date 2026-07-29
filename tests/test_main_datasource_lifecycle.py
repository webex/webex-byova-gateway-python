"""Integration tests for the BYODS lifecycle in gateway startup."""

from contextlib import ExitStack
from unittest.mock import Mock, patch

import main


def test_datasource_is_ready_before_grpc_starts_and_stops_on_shutdown():
    events = []
    config = {
        "connectors": {},
        "gateway": {"host": "127.0.0.1", "port": 50051},
        "monitoring": {"enabled": False},
        "jwt_validation": {"enabled": False},
        "data_source": {"enabled": True},
    }

    router = Mock()
    router.get_connector_info.return_value = {"loaded_connectors": []}
    router.get_all_available_agents.return_value = []

    gateway_server = Mock()
    grpc_server = Mock()
    grpc_server.start.side_effect = lambda: events.append("grpc")
    lifecycle = Mock()
    lifecycle.start.side_effect = lambda: events.append("datasource")
    lifecycle.data_source_id = "source-1"
    lifecycle.current_data_source = {"tokenExpiryTime": "2026-07-30T12:00:00Z"}

    with ExitStack() as stack:
        stack.enter_context(patch("main.load_config", return_value=config))
        stack.enter_context(patch("main.setup_logging"))
        stack.enter_context(patch("main.VirtualAgentRouter", return_value=router))
        stack.enter_context(
            patch("main.WxCCGatewayServer", return_value=gateway_server)
        )
        stack.enter_context(patch("main.HealthCheckService"))
        stack.enter_context(patch("main.create_jwt_interceptor", return_value=None))
        stack.enter_context(
            patch("main.create_data_source_lifecycle", return_value=lifecycle)
        )
        stack.enter_context(patch("main.grpc.server", return_value=grpc_server))
        stack.enter_context(patch("main.add_VoiceVirtualAgentServicer_to_server"))
        stack.enter_context(patch("main.health_pb2_grpc.add_HealthServicer_to_server"))
        main.main()

    assert events == ["datasource", "grpc"]
    lifecycle.stop.assert_called_once_with()
    gateway_server.shutdown.assert_called_once_with()
    grpc_server.stop.assert_called_once_with(grace=5)
