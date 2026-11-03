"""Tests for the native CES WebSocket provider connector."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from unittest.mock import MagicMock, patch

import pytest
import websocket
from aiohttp import web
from google.cloud import ces_v1

from src.connectors.gecx_connector import GECXTerminalReason
from src.connectors.gecx_websocket_connector import (
    GECXWebSocketConnector,
    GECXWebSocketStreamingSession,
)
from src.core.virtual_agent_router import VirtualAgentRouter


@pytest.fixture
def websocket_config():
    return {
        "project_id": "test-project",
        "location": "us",
        "application_id": "test-app",
        "deployment_id": "test-deployment",
        "initial_message": None,
        "input_sample_rate_hertz": 8000,
        "input_audio_encoding": "MULAW",
        "output_sample_rate_hertz": 8000,
        "output_audio_encoding": "MULAW",
        "agents": ["GECX WebSocket - Test"],
    }


@pytest.fixture
def credentials():
    credentials = MagicMock()
    credentials.valid = True
    credentials.token = "test-access-token"
    return credentials


@pytest.fixture
def connector(websocket_config, credentials):
    with patch(
        "src.connectors.gecx_websocket_connector.google.auth.default",
        return_value=(credentials, "test-project"),
    ):
        return GECXWebSocketConnector(websocket_config)


@pytest.fixture
def fake_ces_websocket_server():
    ready: queue.Queue[tuple[asyncio.AbstractEventLoop, web.AppRunner, int]] = (
        queue.Queue(maxsize=1)
    )
    received: queue.Queue[dict] = queue.Queue()

    async def handle(request: web.Request) -> web.WebSocketResponse:
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        first_message = await socket.receive(timeout=5)
        received.put(
            {
                "authorization": request.headers.get("Authorization"),
                "content_type": request.headers.get("Content-Type"),
                "payload": json.loads(first_message.data),
            }
        )
        await socket.send_json({"sessionOutput": {"audio": "YWdlbnQgYXVkaW8="}})
        await socket.send_json({"endSession": {}})
        await socket.close()
        return socket

    def run_server() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = web.Application()
        app.router.add_get(
            "/ws/google.cloud.ces.v1.SessionService/BidiRunSession/locations/us",
            handle,
        )
        runner = web.AppRunner(app)

        async def start() -> None:
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            ready.put((loop, runner, port))

        loop.run_until_complete(start())
        loop.run_forever()
        loop.close()

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    loop, runner, port = ready.get(timeout=5)
    try:
        yield port, received
    finally:
        cleanup = asyncio.run_coroutine_threadsafe(runner.cleanup(), loop)
        cleanup.result(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


class TestGECXWebSocketConnector:
    def test_uses_documented_ces_endpoint_without_creating_grpc_client(
        self, websocket_config, credentials
    ):
        with patch(
            "src.connectors.gecx_websocket_connector.google.auth.default",
            return_value=(credentials, "test-project"),
        ), patch(
            "src.connectors.gecx_connector.ces_v1.SessionServiceClient"
        ) as grpc_client:
            connector = GECXWebSocketConnector(websocket_config)

        assert connector.websocket_url == (
            "wss://ces.googleapis.com/ws/google.cloud.ces.v1.SessionService/"
            "BidiRunSession/locations/us"
        )
        assert connector.get_provider_transport() == "websocket"
        assert connector.get_supported_transports() == frozenset({"grpc", "websocket"})
        grpc_client.assert_not_called()

    @pytest.mark.parametrize(
        "endpoint",
        [
            "wss://example.com/ws/google.cloud.ces.v1.SessionService/"
            "BidiRunSession/locations/us",
            "ws://ces.googleapis.com/ws/google.cloud.ces.v1.SessionService/"
            "BidiRunSession/locations/us",
            "wss://user:password@ces.googleapis.com/ws/"
            "google.cloud.ces.v1.SessionService/BidiRunSession/locations/us",
            "wss://ces.googleapis.com/ws/google.cloud.ces.v1.SessionService/"
            "BidiRunSession/locations/eu",
        ],
    )
    def test_rejects_untrusted_or_mismatched_endpoint(
        self, websocket_config, credentials, endpoint
    ):
        websocket_config["websocket_endpoint"] = endpoint
        with patch(
            "src.connectors.gecx_websocket_connector.google.auth.default",
            return_value=(credentials, "test-project"),
        ):
            with pytest.raises(ValueError, match="GECX WebSocket|public GECX"):
                GECXWebSocketConnector(websocket_config)

    def test_local_endpoint_requires_explicit_test_switch(
        self, websocket_config, credentials
    ):
        websocket_config["websocket_endpoint"] = (
            "ws://127.0.0.1:8766/ws/google.cloud.ces.v1.SessionService/"
            "BidiRunSession/locations/us"
        )
        with patch(
            "src.connectors.gecx_websocket_connector.google.auth.default",
            return_value=(credentials, "test-project"),
        ):
            with pytest.raises(ValueError, match="allow_insecure_local_websocket"):
                GECXWebSocketConnector(websocket_config)

        websocket_config["allow_insecure_local_websocket"] = True
        with patch(
            "src.connectors.gecx_websocket_connector.google.auth.default",
            return_value=(credentials, "test-project"),
        ):
            connector = GECXWebSocketConnector(websocket_config)

        assert connector.websocket_url.startswith("ws://127.0.0.1:8766/")

    def test_connection_disables_redirects_and_does_not_log_token(
        self, connector, credentials, caplog
    ):
        connection = MagicMock()
        with patch(
            "src.connectors.gecx_websocket_connector.websocket.create_connection",
            return_value=connection,
        ) as create_connection:
            assert connector.create_websocket_connection() is connection

        _, kwargs = create_connection.call_args
        assert kwargs["header"]["Authorization"] == "Bearer test-access-token"
        assert kwargs["header"]["Content-Type"] == "application/json"
        assert kwargs["redirect_limit"] == 0
        assert kwargs["enable_multithread"] is True
        assert "test-access-token" not in caplog.text
        credentials.refresh.assert_not_called()

    def test_refreshes_credentials_once_after_unauthorized(
        self, connector, credentials
    ):
        unauthorized = websocket.WebSocketBadStatusException(
            "unauthorized",
            status_code=401,
        )
        connection = MagicMock()
        with patch(
            "src.connectors.gecx_websocket_connector.websocket.create_connection",
            side_effect=[unauthorized, connection],
        ) as create_connection:
            assert connector.create_websocket_connection() is connection

        assert create_connection.call_count == 2
        credentials.refresh.assert_called_once()

    def test_creates_websocket_session_variant(self, connector):
        session = connector._create_streaming_session(
            conversation_id="conv-1",
            session_path=f"{connector.app_path}/sessions/session-1",
            async_response_sink=None,
            input_acknowledgement_sink=None,
        )

        assert isinstance(session, GECXWebSocketStreamingSession)

    def test_router_keeps_grpc_and_websocket_provider_agents_separate(
        self, websocket_config, credentials
    ):
        grpc_config = dict(websocket_config)
        grpc_config["agents"] = ["GECX gRPC Agent"]
        native_websocket_config = dict(websocket_config)
        native_websocket_config["agents"] = ["GECX WebSocket Agent"]
        config = {
            "connectors": {
                "gecx_grpc": {
                    "class": "GECXConnector",
                    "module": "connectors.gecx_connector",
                    "supported_transports": ["grpc"],
                    "config": grpc_config,
                },
                "gecx_websocket": {
                    "class": "GECXWebSocketConnector",
                    "module": "connectors.gecx_websocket_connector",
                    "supported_transports": ["websocket"],
                    "config": native_websocket_config,
                },
            }
        }

        with patch("src.connectors.gecx_connector.ces_v1.SessionServiceClient"), patch(
            "src.connectors.gecx_websocket_connector.google.auth.default",
            return_value=(credentials, "test-project"),
        ):
            router = VirtualAgentRouter()
            router.load_connectors(config)

        assert router.get_all_available_agents(transport="grpc") == ["GECX gRPC Agent"]
        assert router.get_all_available_agents(transport="websocket") == [
            "GECX WebSocket Agent"
        ]
        assert (
            router.get_connector_for_agent(
                "GECX WebSocket Agent", transport="websocket"
            ).get_provider_transport()
            == "websocket"
        )


class TestGECXWebSocketProtocol:
    def _session(self, connector):
        return GECXWebSocketStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path=f"{connector.app_path}/sessions/session-1",
            deployment_path=connector.deployment_path,
            initial_message=None,
        )

    def test_serializes_audio_as_protobuf_json_base64(self, connector):
        request = ces_v1.BidiSessionClientMessage(
            realtime_input=ces_v1.SessionInput(audio=b"caller audio")
        )

        payload = json.loads(
            GECXWebSocketStreamingSession._serialize_client_message(request)
        )

        assert payload == {"realtimeInput": {"audio": "Y2FsbGVyIGF1ZGlv"}}

    def test_parses_forward_compatible_server_message(self, connector):
        session = self._session(connector)

        message = session._parse_server_message(
            json.dumps(
                {
                    "sessionOutput": {
                        "audio": "YWdlbnQgYXVkaW8=",
                        "turnCompleted": True,
                    },
                    "futureField": {"ignored": True},
                }
            )
        )

        assert message.session_output.audio == b"agent audio"
        assert message.session_output.turn_completed is True

    def test_rejects_oversized_server_message(self, connector):
        connector.websocket_max_response_bytes = 64 * 1024
        session = self._session(connector)

        with pytest.raises(ValueError, match="frame-size limit"):
            session._parse_server_message("x" * (64 * 1024 + 1))

    def test_stream_sends_config_and_maps_audio_then_end_session(self, connector):
        connection = MagicMock()
        connection.recv.side_effect = [
            json.dumps(
                {
                    "sessionOutput": {
                        "audio": "YWdlbnQgYXVkaW8=",
                        "turnCompleted": False,
                    }
                }
            ),
            json.dumps({"endSession": {}}),
        ]
        connector.create_websocket_connection = MagicMock(return_value=connection)
        session = self._session(connector)

        session._run_stream()

        sent_payloads = [
            json.loads(call.args[0]) for call in connection.send.call_args_list
        ]
        assert sent_payloads[0]["config"]["session"].endswith("/sessions/session-1")
        assert sent_payloads[0]["config"]["deployment"] == connector.deployment_path
        responses = session.drain_responses()
        assert [response["message_type"] for response in responses] == [
            "audio",
            "session_end",
        ]
        assert responses[0]["audio_content"] == b"agent audio"
        assert session.terminal_decision.reason == GECXTerminalReason.NORMAL_END
        connection.close.assert_called()

    def test_invalid_json_terminates_session_without_echoing_payload(
        self, connector, caplog
    ):
        connection = MagicMock()
        connection.recv.return_value = "not-json-and-not-a-secret"
        connector.create_websocket_connection = MagicMock(return_value=connection)
        session = self._session(connector)

        session._run_stream()

        assert session.terminal_decision.reason == GECXTerminalReason.STREAM_ERROR
        assert "not-json-and-not-a-secret" not in caplog.text

    def test_remote_close_unblocks_sender_before_join(self, connector, caplog):
        connection = MagicMock()
        connection.recv.return_value = ""
        connector.create_websocket_connection = MagicMock(return_value=connection)
        session = self._session(connector)

        session._run_stream()

        assert session.terminal_decision.reason == GECXTerminalReason.STREAM_ERROR
        assert "gecx_websocket_sender_join_timeout" not in caplog.text

    def test_real_local_socket_exchanges_config_audio_and_end_session(
        self,
        websocket_config,
        credentials,
        fake_ces_websocket_server,
        monkeypatch,
    ):
        port, received = fake_ces_websocket_server
        websocket_config.update(
            {
                "websocket_endpoint": (
                    f"ws://127.0.0.1:{port}/ws/"
                    "google.cloud.ces.v1.SessionService/"
                    "BidiRunSession/locations/us"
                ),
                "allow_insecure_local_websocket": True,
            }
        )
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
        with patch(
            "src.connectors.gecx_websocket_connector.google.auth.default",
            return_value=(credentials, "test-project"),
        ):
            live_connector = GECXWebSocketConnector(websocket_config)
        session = self._session(live_connector)

        session._run_stream()

        request = received.get(timeout=5)
        assert request["authorization"] == "Bearer test-access-token"
        assert request["content_type"] == "application/json"
        assert request["payload"]["config"]["session"].endswith("/sessions/session-1")
        responses = session.drain_responses()
        assert [response["message_type"] for response in responses] == [
            "audio",
            "session_end",
        ]
        assert session.terminal_decision.reason == GECXTerminalReason.NORMAL_END
