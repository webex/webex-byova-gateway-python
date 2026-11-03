"""Socket-level tests for the BYOVA WebSocket transport."""

import asyncio
import base64
import logging
import socket as socket_module
import threading
import wave
from concurrent.futures import Future
from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest
from aiohttp import WSMsgType, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from src.auth.jwt_validator import AccessTokenException
from src.core.conversation_registry import ConversationRegistry
from src.core.virtual_agent_router import VirtualAgentRouter
from src.transports.websocket_server import (
    WebSocketGatewayRuntime,
    WebSocketGatewayServer,
    WebSocketProtocolError,
)
from tools.websocket_smoke import run as run_smoke


class FakeRouter:
    def __init__(
        self,
        start_message_type: str = "session_start",
        websocket_agents: list[str] | None = None,
    ) -> None:
        self.agent_to_connector_name_map = {"Test Agent": "test_connector"}
        self.start_message_type = start_message_type
        self.websocket_agents = (
            ["Test Agent"] if websocket_agents is None else websocket_agents
        )
        self.end_calls = 0
        self.message_calls = 0
        self.async_sink = None
        self.discovery_transports: list[str | None] = []

    def get_all_available_agents(self, transport=None):
        self.discovery_transports.append(transport)
        return self.websocket_agents if transport == "websocket" else ["Test Agent"]

    def get_connector_for_agent(self, agent_id, transport=None):
        if agent_id != "Test Agent":
            raise ValueError(agent_id)
        if transport == "websocket" and agent_id not in self.websocket_agents:
            raise ValueError(agent_id)
        return self

    def get_websocket_output_mode(self, agent_id):
        return "raw_chunk"

    def route_request(self, agent_id, operation, conversation_id, message_data):
        if operation == "start_conversation":
            return {
                "message_type": self.start_message_type,
                "text": "Connected",
                "audio_content": b"",
                "response_type": "final",
            }
        if operation == "end_conversation":
            self.end_calls += 1
            return None
        if operation in {"send_message", "handle_speech_boundary"}:
            self.message_calls += 1
            return None
        raise AssertionError(operation)

    def set_async_response_sink(self, agent_id, conversation_id, sink):
        self.async_sink = sink

    def clear_async_response_sink(self, *args):
        return None

    def should_observe_speech_boundaries(self, *args):
        return False


def _start(
    seq: int = 1,
    conversation_id: str = "call-1",
    agent_id: str = "Test Agent",
) -> dict[str, Any]:
    return {
        "type": "VOICE_VA_REQUEST",
        "seq": seq,
        "ts": "2026-09-08T12:00:00Z",
        "conversation_id": conversation_id,
        "payload": {
            "conversation_id": conversation_id,
            "customer_org_id": "org-1",
            "virtual_agent_id": agent_id,
            "voice_va_input_type": {"event_input": {"event_type": "SESSION_START"}},
        },
    }


async def _client_for(server: WebSocketGatewayServer) -> TestClient:
    client = TestClient(TestServer(server.create_app()))
    await client.start_server()
    return client


async def _wait_for_cleanup(router: FakeRouter) -> None:
    for _ in range(50):
        if router.end_calls == 1:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("provider cleanup did not complete")


async def _wait_for_release(server: WebSocketGatewayServer) -> None:
    for _ in range(100):
        if not server.registry.snapshot() and not server._processors:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("conversation lease was not released")


def _end_events(server: WebSocketGatewayServer) -> list[dict[str, Any]]:
    return [
        event
        for event in server.get_connection_events()
        if event["event_type"] == "end"
    ]


def _event(seq: int, event_type: str) -> dict[str, Any]:
    value = _start(seq=seq)
    value["payload"]["voice_va_input_type"] = {
        "event_input": {"event_type": event_type}
    }
    return value


def _audio(seq: int) -> dict[str, Any]:
    value = _start(seq=seq)
    value["payload"]["voice_va_input_type"] = {
        "audio_input": {
            "caller_audio_b64": base64.b64encode(b"\xff" * 160).decode("ascii"),
            "encoding": "MULAW_FORMAT",
            "sample_rate_hertz": 8000,
        }
    }
    return value


async def _receive_response_stream(socket) -> list[dict[str, Any]]:
    """Collect one ordered response stream through its FINAL frame."""
    frames = []
    while True:
        frame = await socket.receive_json()
        frames.append(frame)
        if frame["payload"]["response_type"] == "FINAL":
            return frames


def _write_wav(path, audio: bytes = bytes(range(256)) * 4) -> None:
    """Write deterministic PCM audio for Local Audio transport tests."""
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(1)
        wav_file.setframerate(8000)
        wav_file.writeframes(audio)


def test_health_is_available_without_websocket_authentication():
    async def scenario():
        class RejectingValidator:
            def validate_token(self, token):
                raise AssertionError("health must not invoke JWT validation")

        server = WebSocketGatewayServer(
            FakeRouter(), jwt_validator=RejectingValidator()
        )
        client = await _client_for(server)
        try:
            response = await client.get("/health")
            assert response.status == 200
            assert await response.json() == {
                "status": "healthy",
                "transport": "websocket",
            }
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())


def test_discovery_uses_shared_router_catalog():
    async def scenario():
        router = FakeRouter()
        server = WebSocketGatewayServer(
            router,
            allow_unauthenticated_local_dev=True,
            discovery_idle_timeout_seconds=0.25,
        )
        client = await _client_for(server)
        try:
            socket = await client.ws_connect("/v1/listVirtualAgents")
            await socket.send_json({"customer_org_id": "org-1"})
            response = await socket.receive_json()
            assert response == {
                "virtual_agents": [
                    {
                        "id": "Test Agent",
                        "name": "Test Agent",
                        "description": "test_connector",
                    }
                ]
            }
            assert router.discovery_transports == ["websocket"]
            assert not socket.closed
            await socket.close()
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())


def test_local_audio_is_discoverable_and_streams_raw_audio_over_websocket(
    tmp_path, capsys
):
    """Exercise Local Audio through the real router and WebSocket adapter."""
    welcome_path = tmp_path / "welcome.wav"
    _write_wav(welcome_path)

    router = VirtualAgentRouter()
    router.load_connectors(
        {
            "connectors": {
                "local_audio_connector": {
                    "class": "LocalAudioConnector",
                    "module": "connectors.local_audio_connector",
                    "config": {
                        "agent_id": "Local Playback",
                        "audio_base_path": str(tmp_path),
                        "audio_files": {"welcome": welcome_path.name},
                    },
                }
            }
        }
    )

    async def scenario():
        server = WebSocketGatewayServer(
            router,
            allow_unauthenticated_local_dev=True,
            discovery_idle_timeout_seconds=0.25,
        )
        client = await _client_for(server)
        try:
            discovery = await client.ws_connect("/v1/listVirtualAgents")
            await discovery.send_json({"customer_org_id": "org-1"})
            catalog = await discovery.receive_json()
            assert [agent["id"] for agent in catalog["virtual_agents"]] == [
                "Local Audio: Local Playback"
            ]
            await discovery.close()

            socket = await client.ws_connect("/v1/va")
            await socket.send_json(
                _start(
                    conversation_id="local-audio-call",
                    agent_id="Local Audio: Local Playback",
                )
            )
            responses = await _receive_response_stream(socket)
            assert all(item["type"] == "VOICE_VA_RESPONSE" for item in responses)
            assert len(responses) > 1
            assert responses[0]["payload"]["response_type"] == "CHUNK"
            assert responses[-1]["payload"]["response_type"] == "FINAL"
            assert responses[0]["payload"]["prompts"][0]["is_barge_in_enabled"] is True
            audio = b"".join(
                base64.b64decode(
                    item["payload"]["prompts"][0]["audio_content_b64"],
                    validate=True,
                )
                for item in responses[:-1]
            )
            assert audio == bytes(range(256)) * 4
            await socket.close()
            await _wait_for_release(server)

            await run_smoke(
                SimpleNamespace(
                    url=str(client.make_url("/"))
                    .rstrip("/")
                    .replace("http://", "ws://"),
                    mode="session",
                    org_id="org-1",
                    agent_id="Local Audio: Local Playback",
                    conversation_id=None,
                    timeout=5,
                    sessions=4,
                    hold_seconds=0.05,
                    expect_shutdown=False,
                    include_audio=False,
                )
            )
            await _wait_for_release(server)
            assert not server.registry.snapshot()
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())
    assert '"sessions": 4' in capsys.readouterr().out


@pytest.mark.parametrize(
    ("wire_digit", "audio_name", "expected_event", "expected_text"),
    [
        (
            "DTMF_DIGIT_FIVE",
            "transfer.wav",
            "TRANSFER_TO_AGENT",
            "Transferring you to an agent. Please wait.",
        ),
        (
            "DTMF_DIGIT_SIX",
            "goodbye.wav",
            "SESSION_END",
            "Thank you for calling. Goodbye!",
        ),
    ],
)
def test_local_audio_dtmf_works_over_websocket(
    tmp_path,
    wire_digit,
    audio_name,
    expected_event,
    expected_text,
):
    """Route schema-valid DTMF through the socket into Local Audio."""
    welcome_path = tmp_path / "welcome.wav"
    action_path = tmp_path / audio_name
    _write_wav(welcome_path)
    _write_wav(action_path, bytes(reversed(range(256))) * 4)

    router = VirtualAgentRouter()
    router.load_connectors(
        {
            "connectors": {
                "local_audio_connector": {
                    "class": "LocalAudioConnector",
                    "module": "connectors.local_audio_connector",
                    "config": {
                        "agent_id": "Local Playback",
                        "audio_base_path": str(tmp_path),
                        "audio_files": {
                            "welcome": welcome_path.name,
                            "transfer": "transfer.wav",
                            "goodbye": "goodbye.wav",
                        },
                    },
                }
            }
        }
    )

    async def scenario():
        server = WebSocketGatewayServer(
            router,
            allow_unauthenticated_local_dev=True,
            terminal_peer_close_timeout_seconds=0.5,
        )
        client = await _client_for(server)
        try:
            socket = await client.ws_connect("/v1/va")
            await socket.send_json(
                _start(
                    conversation_id="local-audio-dtmf",
                    agent_id="Local Audio: Local Playback",
                )
            )
            welcome_frames = await _receive_response_stream(socket)
            welcome = welcome_frames[0]
            assert all(item["type"] == "VOICE_VA_RESPONSE" for item in welcome_frames)
            assert welcome["payload"]["response_type"] == "CHUNK"
            assert welcome["payload"]["input_mode"] == "INPUT_VOICE_DTMF"
            assert welcome["payload"]["input_handling_config"]["dtmf_config"] == {
                "inter_digit_timeout_msec": 5000,
                "termchar": "DTMF_DIGIT_POUND",
                "dtmf_input_length": 1,
            }
            assert welcome["payload"]["input_handling_config"]["speech_timers"] == {
                "no_input_timeout_msec": 30000
            }

            await socket.send_json(
                {
                    "type": "VOICE_VA_REQUEST",
                    "seq": 2,
                    "ts": "2026-09-08T12:00:01Z",
                    "conversation_id": "local-audio-dtmf",
                    "payload": {
                        "conversation_id": "local-audio-dtmf",
                        "customer_org_id": "org-1",
                        "virtual_agent_id": "Local Audio: Local Playback",
                        "voice_va_input_type": {
                            "dtmf_input": {"dtmf_events": [wire_digit]}
                        },
                    },
                }
            )
            responses = await _receive_response_stream(socket)
            assert all(item["type"] == "VOICE_VA_RESPONSE" for item in responses)
            assert [item["seq"] for item in responses] == list(
                range(responses[0]["seq"], responses[0]["seq"] + len(responses))
            )
            assert responses[-1]["payload"]["response_type"] == "FINAL"
            assert responses[0]["payload"]["prompts"][0]["text"] == expected_text
            assert (
                responses[-1]["payload"]["output_events"][0]["event_type"]
                == expected_event
            )
            assert len(responses) > 1
            audio = b"".join(
                base64.b64decode(
                    item["payload"]["prompts"][0]["audio_content_b64"],
                    validate=True,
                )
                for item in responses[:-1]
            )
            assert audio == bytes(reversed(range(256))) * 4
            await socket.close()
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())


def test_discovery_accepts_unknown_fields_and_returns_only_websocket_agents():
    async def scenario():
        router = FakeRouter(websocket_agents=[])
        server = WebSocketGatewayServer(
            router,
            allow_unauthenticated_local_dev=True,
            discovery_idle_timeout_seconds=0.25,
        )
        client = await _client_for(server)
        try:
            socket = await client.ws_connect("/v1/listVirtualAgents")
            await socket.send_json(
                {
                    "customer_org_id": "org-1",
                    "future_control_plane_field": True,
                }
            )
            assert await socket.receive_json() == {"virtual_agents": []}
            assert not socket.closed
            await socket.close()
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())


def test_websocket_runtime_rejects_agent_not_enabled_for_websocket():
    async def scenario():
        server = WebSocketGatewayServer(
            FakeRouter(websocket_agents=[]),
            allow_unauthenticated_local_dev=True,
        )
        client = await _client_for(server)
        try:
            socket = await client.ws_connect("/v1/va")
            await socket.send_json(_start())
            response = await socket.receive_json()
            assert response["type"] == "ERROR"
            assert response["status"] == 404
            assert response["detail"] == "virtual agent was not found"
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())


def test_jwt_failure_is_rejected_before_websocket_upgrade():
    class RejectingValidator:
        def validate_token(self, token):
            raise AccessTokenException("invalid")

    async def scenario():
        server = WebSocketGatewayServer(
            FakeRouter(), jwt_validator=RejectingValidator()
        )
        client = await _client_for(server)
        try:
            try:
                await client.ws_connect(
                    "/v1/va", headers={"Authorization": "Bearer redacted"}
                )
                raise AssertionError("upgrade unexpectedly succeeded")
            except WSServerHandshakeError as error:
                assert error.status == 401
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("message_type", "event_type"),
    [
        ("session_end", "SESSION_END"),
        ("transfer", "TRANSFER_TO_AGENT"),
    ],
)
def test_terminal_response_waits_for_peer_close_and_cleans_provider_once(
    message_type, event_type
):
    async def scenario():
        router = FakeRouter(start_message_type=message_type)
        server = WebSocketGatewayServer(router, allow_unauthenticated_local_dev=True)
        client = await _client_for(server)
        try:
            socket = await client.ws_connect("/v1/va")
            await socket.send_json(_start())
            response = await socket.receive_json()
            assert response["type"] == "VOICE_VA_RESPONSE"
            assert response["payload"]["output_events"][0]["event_type"] == event_type
            await asyncio.sleep(0.05)
            assert not socket.closed
            await socket.close()
            await _wait_for_cleanup(router)
            assert socket.closed
            assert router.end_calls == 1
            terminal_events = [
                event
                for event in server.get_connection_events()
                if event["event_type"] == "terminal"
            ]
            assert len(terminal_events) == 1
            assert terminal_events[0]["outcome"] == event_type
            assert terminal_events[0]["transport"] == "websocket"
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())


def test_terminal_response_peer_close_wait_is_bounded():
    async def scenario():
        router = FakeRouter(start_message_type="session_end")
        server = WebSocketGatewayServer(
            router,
            allow_unauthenticated_local_dev=True,
            terminal_peer_close_timeout_seconds=0.05,
        )
        client = await _client_for(server)
        try:
            socket = await client.ws_connect("/v1/va")
            await socket.send_json(_start())
            response = await socket.receive_json()
            assert response["type"] == "VOICE_VA_RESPONSE"
            assert (
                response["payload"]["output_events"][0]["event_type"] == "SESSION_END"
            )
            await socket.receive()
            await _wait_for_cleanup(router)
            assert socket.closed
            assert router.end_calls == 1
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())


def test_first_application_message_must_be_session_start():
    async def scenario():
        server = WebSocketGatewayServer(
            FakeRouter(), allow_unauthenticated_local_dev=True
        )
        client = await _client_for(server)
        try:
            socket = await client.ws_connect("/v1/va")
            value = _start()
            value["payload"]["voice_va_input_type"]["event_input"]["event_type"] = (
                "CUSTOM_EVENT"
            )
            await socket.send_json(value)
            response = await socket.receive_json()
            assert response["type"] == "ERROR"
            assert response["status"] == 400
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())


def test_handshake_validation_logs_field_paths_without_peer_values(caplog):
    async def scenario():
        server = WebSocketGatewayServer(
            FakeRouter(), allow_unauthenticated_local_dev=True
        )
        client = await _client_for(server)
        try:
            with caplog.at_level(
                logging.INFO, logger="src.transports.websocket_server"
            ):
                socket = await client.ws_connect("/v1/va")
                value = _start()
                value["api_token\nforged"] = "do-not-log-this-peer-value"
                await socket.send_json(value)
                response = await socket.receive_json()
            assert response["type"] == "ERROR"
            assert response["status"] == 400
            messages = "\n".join(record.getMessage() for record in caplog.records)
            assert "websocket_voice_connection_opened" in messages
            assert "category=schema_validation_failed" in messages
            assert "api_token_forged:extra_forbidden" in messages
            assert "api_token\nforged" not in messages
            assert "do-not-log-this-peer-value" not in messages
            assert "org-1" not in messages
            assert "call-1" not in messages
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())


def test_post_handshake_validation_returns_error_and_logs_safely(caplog):
    async def scenario():
        router = FakeRouter()
        server = WebSocketGatewayServer(router, allow_unauthenticated_local_dev=True)
        client = await _client_for(server)
        try:
            with caplog.at_level(
                logging.INFO, logger="src.transports.websocket_server"
            ):
                socket = await client.ws_connect("/v1/va")
                await socket.send_json(_start())
                assert (await socket.receive_json())["type"] == "VOICE_VA_RESPONSE"
                invalid = _start(seq=2)
                invalid["payload"]["voice_va_input_type"] = {
                    "audio_input": {
                        "caller_audio_b64": "do-not-log-this-peer-value",
                        "encoding": "MULAW_FORMAT",
                    }
                }
                await socket.send_json(invalid)
                response = await socket.receive_json()
            assert response["type"] == "ERROR"
            assert response["status"] == 400
            messages = "\n".join(
                record.getMessage()
                for record in caplog.records
                if "websocket_voice_frame_rejected" in record.getMessage()
            )
            assert "websocket_voice_frame_rejected" in messages
            assert "message_index=2" in messages
            assert "category=schema_validation_failed" in messages
            assert "sample_rate_hertz:missing" in messages
            assert "do-not-log-this-peer-value" not in messages
            assert "org-1" not in messages
            assert "call-1" not in messages
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())


def test_duplicate_sequence_is_fatal_and_disconnect_cleans_provider_once():
    async def scenario():
        router = FakeRouter()
        server = WebSocketGatewayServer(router, allow_unauthenticated_local_dev=True)
        client = await _client_for(server)
        try:
            socket = await client.ws_connect("/v1/va")
            await socket.send_json(_start())
            assert (await socket.receive_json())["type"] == "VOICE_VA_RESPONSE"
            duplicate = _start()
            duplicate["payload"]["voice_va_input_type"] = {
                "event_input": {"event_type": "CUSTOM_EVENT"}
            }
            await socket.send_json(duplicate)
            response = await socket.receive_json()
            assert response["type"] == "ERROR"
            assert "seq must increase" in response["detail"]
            await socket.receive()
            await _wait_for_cleanup(router)
            assert socket.close_code == 1002
            assert router.end_calls == 1
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())


def test_second_session_start_is_fatal_even_with_increasing_sequence():
    async def scenario():
        router = FakeRouter()
        server = WebSocketGatewayServer(router, allow_unauthenticated_local_dev=True)
        client = await _client_for(server)
        try:
            socket = await client.ws_connect("/v1/va")
            await socket.send_json(_start())
            assert (await socket.receive_json())["type"] == "VOICE_VA_RESPONSE"
            await socket.send_json(_start(seq=2))
            response = await socket.receive_json()
            assert response["type"] == "ERROR"
            assert (
                "SESSION_START may only be sent as the first message"
                in response["detail"]
            )
            await socket.receive()
            await _wait_for_cleanup(router)
            assert router.end_calls == 1
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())


def test_existing_grpc_ownership_blocks_websocket_conversation():
    async def scenario():
        registry = ConversationRegistry()
        registry.acquire(
            customer_org_id="org-1",
            conversation_id="call-1",
            transport="grpc",
            agent_id="Test Agent",
            connection_id="grpc-1",
        )
        server = WebSocketGatewayServer(
            FakeRouter(),
            registry=registry,
            allow_unauthenticated_local_dev=True,
        )
        client = await _client_for(server)
        try:
            socket = await client.ws_connect("/v1/va")
            await socket.send_json(_start())
            response = await socket.receive_json()
            assert response["type"] == "ERROR"
            assert response["status"] == 409
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(scenario())


def test_server_initiated_close_releases_lease_and_cleans_provider_once():
    """A gateway-side protocol close must not leak the conversation lease."""

    async def scenario():
        router = FakeRouter()
        server = WebSocketGatewayServer(router, allow_unauthenticated_local_dev=True)
        client = await _client_for(server)
        try:
            socket = await client.ws_connect("/v1/va")
            await socket.send_json(_start())
            assert (await socket.receive_json())["type"] == "VOICE_VA_RESPONSE"
            await socket.send_json(_event(1, "CUSTOM_EVENT"))
            assert (await socket.receive_json())["type"] == "ERROR"
            await socket.receive()
            await _wait_for_release(server)
            assert router.end_calls == 1
            assert [event["reason"] for event in _end_events(server)] == [
                "websocket_disconnect"
            ]

            reconnect = await client.ws_connect("/v1/va")
            await reconnect.send_json(_start())
            assert (await reconnect.receive_json())["type"] == "VOICE_VA_RESPONSE"
            await reconnect.close()
            await _wait_for_release(server)
            assert router.end_calls == 2
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(asyncio.wait_for(scenario(), timeout=20))


@pytest.mark.parametrize("barge_in_enabled", [False, True])
@pytest.mark.parametrize("boundary", [None, "START_OF_INPUT", "END_OF_INPUT"])
@pytest.mark.parametrize("final_kind", ["silence", "transfer", "session_end"])
def test_streamed_audio_final_contains_explicit_empty_audio(
    boundary, final_kind, barge_in_enabled
):
    """A streamed connector's prompt-less FINAL must finish WxCC playback."""

    async def scenario():
        router = FakeRouter()
        router.get_dtmf_input_config = lambda *args: {
            "dtmf_input_length": 7,
            "inter_digit_timeout_msec": 7300,
            "termchar": "DTMF_DIGIT_STAR",
        }
        server = WebSocketGatewayServer(router, allow_unauthenticated_local_dev=True)
        client = await _client_for(server)
        try:
            socket = await client.ws_connect("/v1/va")
            await socket.send_json(_start())
            await socket.receive_json()
            assert await asyncio.to_thread(
                router.async_sink,
                {
                    "message_type": "agent_response",
                    "text": "",
                    "audio_content": b"a" * 320,
                    "barge_in_enabled": barge_in_enabled,
                    "response_type": "chunk",
                },
            )
            assert (await socket.receive_json())["payload"]["response_type"] == "CHUNK"
            if boundary:
                assert await asyncio.to_thread(
                    router.async_sink,
                    {
                        "message_type": "silence",
                        "response_type": "final",
                        "output_events": [{"event_type": boundary}],
                    },
                )
                if boundary == "START_OF_INPUT":
                    interrupted = await socket.receive_json()
                    assert interrupted["payload"] == {
                        "response_type": "FINAL",
                        "prompts": [{"audio_content_b64": "", "is_barge_in_enabled": barge_in_enabled}],
                        "input_mode": "INPUT_VOICE_DTMF",
                        "input_handling_config": {
                            "dtmf_config": {"dtmf_input_length": 7,
                                            "inter_digit_timeout_msec": 7300,
                                            "termchar": "DTMF_DIGIT_STAR"},
                            "speech_timers": {"no_input_timeout_msec": 30000},
                        },
                    }
                    input_event = await socket.receive_json()
                    assert input_event["seq"] == interrupted["seq"] + 1
                    assert "prompts" not in input_event["payload"]
                else:
                    assert "prompts" not in (await socket.receive_json())["payload"]
            for index in range(2 if final_kind == "silence" else 1):
                assert await asyncio.to_thread(
                    router.async_sink,
                    {
                        "message_type": final_kind,
                        "response_type": "final",
                    },
                )
                final = (await socket.receive_json())["payload"]
                if index == 0 and boundary != "START_OF_INPUT":
                    assert final["prompts"] == [
                        {
                            "audio_content_b64": "",
                            "is_barge_in_enabled": barge_in_enabled and final_kind == "silence",
                        }
                    ]
                else:
                    assert "prompts" not in final
            if boundary == "START_OF_INPUT" and final_kind == "silence":
                assert await asyncio.to_thread(
                    router.async_sink,
                    {"message_type": "agent_response", "text": "", "audio_content": b"next" * 80,
                     "response_type": "chunk"},
                )
                next_chunk = await socket.receive_json()
                assert next_chunk["payload"]["response_type"] == "CHUNK"
                assert await asyncio.to_thread(
                    router.async_sink,
                    {"message_type": "silence", "response_type": "final"},
                )
                next_final = await socket.receive_json()
                assert next_final["seq"] == next_chunk["seq"] + 1
                assert next_final["payload"]["prompts"][0]["audio_content_b64"] == ""
            await socket.close()
            await _wait_for_release(server)
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(asyncio.wait_for(scenario(), timeout=20))


def test_async_connector_transfer_enters_terminal_state():
    """A transfer delivered through the async sink ends the agent leg."""

    async def scenario():
        router = FakeRouter()
        server = WebSocketGatewayServer(router, allow_unauthenticated_local_dev=True)
        client = await _client_for(server)
        try:
            socket = await client.ws_connect("/v1/va")
            await socket.send_json(_start())
            assert (await socket.receive_json())["type"] == "VOICE_VA_RESPONSE"
            assert router.async_sink is not None

            accepted = await asyncio.to_thread(
                router.async_sink,
                {
                    "message_type": "transfer",
                    "text": "Connecting you to an agent",
                    "audio_content": b"",
                    "response_type": "final",
                },
            )
            assert accepted is True
            transfer = await socket.receive_json()
            assert transfer["type"] == "VOICE_VA_RESPONSE"
            assert [
                event["event_type"] for event in transfer["payload"]["output_events"]
            ] == ["TRANSFER_TO_AGENT"]

            # In-flight caller media after the terminal output is ignored and
            # the gateway waits for WxCC to end and close the socket.
            await socket.send_json(_audio(2))
            await socket.send_json(_event(3, "SESSION_END"))
            close = await socket.receive()
            assert close.type == WSMsgType.CLOSE
            assert socket.close_code == 1000
            await _wait_for_release(server)
            assert router.message_calls == 0
            assert router.end_calls == 1
            assert [event["reason"] for event in _end_events(server)] == ["completed"]
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(asyncio.wait_for(scenario(), timeout=20))


def test_async_terminal_peer_close_wait_is_bounded():
    async def scenario():
        router = FakeRouter()
        server = WebSocketGatewayServer(
            router,
            allow_unauthenticated_local_dev=True,
            terminal_peer_close_timeout_seconds=0.05,
        )
        client = await _client_for(server)
        try:
            socket = await client.ws_connect("/v1/va")
            await socket.send_json(_start())
            assert (await socket.receive_json())["type"] == "VOICE_VA_RESPONSE"
            await asyncio.to_thread(
                router.async_sink,
                {"message_type": "session_end", "audio_content": b""},
            )
            assert (await socket.receive_json())["type"] == "VOICE_VA_RESPONSE"
            assert (await socket.receive()).type == WSMsgType.CLOSE
            assert socket.close_code == 1000
            await _wait_for_release(server)
            assert router.end_calls == 1
            assert [event["reason"] for event in _end_events(server)] == [
                "terminal_peer_close_timeout"
            ]
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(asyncio.wait_for(scenario(), timeout=20))


def test_new_connections_are_rejected_while_shutting_down():
    async def scenario():
        server = WebSocketGatewayServer(
            FakeRouter(), allow_unauthenticated_local_dev=True
        )
        client = await _client_for(server)
        try:
            await server.close_active_connections(timeout=0.1)
            with pytest.raises(WSServerHandshakeError) as error:
                await client.ws_connect("/v1/va")
            assert error.value.status == 503
        finally:
            await client.close()
            server.shutdown()

    asyncio.run(asyncio.wait_for(scenario(), timeout=20))


def _free_port() -> int:
    with socket_module.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.parametrize("sessions", [1, 8])
def test_runtime_stop_closes_active_calls_and_cleans_provider(sessions):
    """Gateway shutdown sends 1001 and ends the provider session once."""

    async def scenario():
        router = FakeRouter()
        server = WebSocketGatewayServer(router, allow_unauthenticated_local_dev=True)
        port = _free_port()
        runtime = WebSocketGatewayRuntime(server, host="127.0.0.1", port=port)
        runtime.start()
        try:
            async with aiohttp.ClientSession() as session:
                voices = [
                    await session.ws_connect(f"ws://127.0.0.1:{port}/v1/va")
                    for _ in range(sessions)
                ]
                discovery = await session.ws_connect(
                    f"ws://127.0.0.1:{port}/v1/listVirtualAgents"
                )
                for index, voice in enumerate(voices):
                    await voice.send_json(_start(conversation_id=f"shutdown-{index}"))
                    assert (await voice.receive_json())["type"] == "VOICE_VA_RESPONSE"
                assert len(server.registry.snapshot()) == sessions

                stopping = asyncio.create_task(asyncio.to_thread(runtime.stop))
                for voice in voices:
                    close = await asyncio.wait_for(voice.receive(), timeout=5)
                    assert close.type == WSMsgType.CLOSE
                    assert voice.close_code == 1001
                await asyncio.wait_for(discovery.receive(), timeout=5)
                await asyncio.wait_for(stopping, timeout=15)
        finally:
            runtime.stop()

        assert router.end_calls == sessions
        assert not server.registry.snapshot()
        assert [event["reason"] for event in _end_events(server)] == [
            "gateway_shutdown"
        ] * sessions

    asyncio.run(asyncio.wait_for(scenario(), timeout=20))


@pytest.mark.parametrize("pending", [0, 1])
def test_cancelled_connector_work_keeps_capacity_until_worker_finishes(pending):
    async def scenario():
        server = WebSocketGatewayServer(
            FakeRouter(),
            allow_unauthenticated_local_dev=True,
            connector_max_workers=1,
            connector_max_pending=pending,
        )
        entered = threading.Event()
        release = threading.Event()

        def blocked():
            entered.set()
            assert release.wait(5)

        first = asyncio.create_task(server._run_bounded(blocked))
        queued = None
        queued_effects = []
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            if pending:
                queued = asyncio.create_task(
                    server._run_bounded(lambda: queued_effects.append("ran"))
                )
                # Let the second coroutine submit its work behind the blocked job.
                await asyncio.sleep(0)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            if queued is not None:
                queued.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await queued
            with pytest.raises(WebSocketProtocolError, match="capacity is exhausted"):
                await server._run_bounded(lambda: "excess", wait_seconds=0)
            release.set()
            assert await server._run_bounded(lambda: "recovered") == "recovered"
            assert queued_effects == []
        finally:
            release.set()
            await asyncio.gather(
                first, *([queued] if queued else []), return_exceptions=True
            )
            server.shutdown()

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


def test_cleanup_stays_responsive_when_connector_workers_are_full():
    async def scenario():
        processing = threading.Event()
        release_processing = threading.Event()
        cleaning = threading.Event()
        release_cleanup = threading.Event()

        class SlowCleanupRouter(FakeRouter):
            def route_request(self, agent_id, operation, conversation_id, message_data):
                if operation == "end_conversation":
                    cleaning.set()
                    assert release_cleanup.wait(5)
                return super().route_request(
                    agent_id, operation, conversation_id, message_data
                )

        router = SlowCleanupRouter()
        server = WebSocketGatewayServer(
            router,
            allow_unauthenticated_local_dev=True,
            connector_max_workers=1,
            connector_max_pending=0,
        )
        client = await _client_for(server)
        work = None

        def blocked():
            processing.set()
            assert release_processing.wait(5)

        try:
            voice = await client.ws_connect("/v1/va")
            await voice.send_json(_start())
            await voice.receive_json()
            work = asyncio.create_task(server._run_bounded(blocked))
            assert await asyncio.to_thread(processing.wait, 2)
            await voice.close()
            assert await asyncio.to_thread(cleaning.wait, 2)
            # Cleanup is blocked in a provider, but the listener must still serve peers.
            response = await asyncio.wait_for(client.get("/health"), timeout=0.5)
            assert response.status == 200
            assert server.registry.snapshot()
            release_cleanup.set()
            await _wait_for_release(server)
            assert router.end_calls == 1
        finally:
            release_processing.set()
            release_cleanup.set()
            if work is not None:
                await work
            await client.close()
            server.shutdown()

    asyncio.run(asyncio.wait_for(scenario(), timeout=15))


def test_shutdown_preserves_cleanup_already_waiting_for_reserved_worker():
    async def scenario():
        entered = threading.Event()
        release = threading.Event()
        cleanup_started = []

        class SlowCleanupRouter(FakeRouter):
            def route_request(self, agent_id, operation, conversation_id, message_data):
                if operation == "end_conversation":
                    cleanup_started.append(conversation_id)
                    entered.set()
                    assert release.wait(5)
                return super().route_request(
                    agent_id, operation, conversation_id, message_data
                )

        router = SlowCleanupRouter()
        server = WebSocketGatewayServer(router, allow_unauthenticated_local_dev=True)
        client = await _client_for(server)
        try:
            voices = [await client.ws_connect("/v1/va") for _ in range(2)]
            for index, voice in enumerate(voices):
                await voice.send_json(_start(conversation_id=f"call-{index}"))
                await voice.receive_json()
            await voices[0].close()
            assert await asyncio.to_thread(entered.wait, 2)
            await voices[1].close()
            # Ensure the second handler has entered finalization before shutdown.
            for _ in range(100):
                if len(server._cleanup_tasks) == 2:
                    break
                await asyncio.sleep(0.01)
            assert len(server._cleanup_tasks) == 2
            assert len(cleanup_started) == 1
            server.shutdown()
            release.set()
            await _wait_for_release(server)
            assert router.end_calls == 2
            assert set(cleanup_started) == {"call-0", "call-1"}
        finally:
            release.set()
            await client.close()
            server.shutdown()

    asyncio.run(asyncio.wait_for(scenario(), timeout=15))


def test_failed_connector_work_and_submission_release_capacity():
    async def scenario():
        server = WebSocketGatewayServer(
            FakeRouter(),
            allow_unauthenticated_local_dev=True,
            connector_max_workers=1,
            connector_max_pending=0,
        )

        def fail():
            raise ValueError("provider failed")

        try:
            with pytest.raises(ValueError, match="provider failed"):
                await server._run_bounded(fail)
            assert await server._run_bounded(lambda: "recovered") == "recovered"
            server.shutdown()
            for _ in range(2):
                with pytest.raises(RuntimeError, match="cannot schedule"):
                    await server._run_bounded(lambda: None, wait_seconds=0)
        finally:
            server.shutdown()

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


def test_disconnect_waits_for_late_provider_registration_without_delaying_other_cleanup():
    async def scenario():
        starting = threading.Event()
        release_start = threading.Event()
        other_ended = threading.Event()
        provider_sessions = set()

        class DelayedStartRouter(FakeRouter):
            def route_request(self, agent_id, operation, conversation_id, message_data):
                if operation == "start_conversation":
                    if conversation_id == "slow-start":
                        starting.set()
                        assert release_start.wait(5)
                    provider_sessions.add(conversation_id)
                elif operation == "end_conversation":
                    provider_sessions.discard(conversation_id)
                result = super().route_request(
                    agent_id, operation, conversation_id, message_data
                )
                if operation == "end_conversation" and conversation_id == "other":
                    other_ended.set()
                return result

        router = DelayedStartRouter()
        server = WebSocketGatewayServer(router, allow_unauthenticated_local_dev=True)
        client = await _client_for(server)
        try:
            slow = await client.ws_connect("/v1/va")
            await slow.send_json(_start(conversation_id="slow-start"))
            assert await asyncio.to_thread(starting.wait, 2)
            other = await client.ws_connect("/v1/va")
            await other.send_json(_start(conversation_id="other"))
            await other.receive_json()
            await slow.close()
            await other.close()
            assert await asyncio.to_thread(other_ended.wait, 2)
            assert router.end_calls == 1
            assert server.registry.get(("org-1", "slow-start")) is not None
            release_start.set()
            await _wait_for_release(server)
            assert router.end_calls == 2
            assert not provider_sessions
        finally:
            release_start.set()
            await client.close()
            server.shutdown()

    asyncio.run(asyncio.wait_for(scenario(), timeout=15))


@pytest.mark.parametrize("work_state", ["cancelled", "failed"])
def test_finalizer_ends_existing_provider_after_work_cancellation_or_failure(
    work_state,
):
    async def scenario():
        server = WebSocketGatewayServer(
            FakeRouter(), allow_unauthenticated_local_dev=True
        )
        lease = server.registry.acquire(
            customer_org_id="org-1",
            conversation_id="call-1",
            transport="websocket",
            agent_id="Test Agent",
            connection_id="socket-1",
        )
        provider_sessions = {"call-1"}
        cleanup_calls = []

        def cleanup(reason):
            provider_sessions.remove("call-1")
            cleanup_calls.append(reason)

        work = Future()
        if work_state == "cancelled":
            work.cancel()
        else:
            work.set_exception(RuntimeError("provider work failed"))
        try:
            await server._finalize_conversation(
                SimpleNamespace(cleanup=cleanup), None, lease, "gateway_shutdown", work
            )
            assert cleanup_calls == ["gateway_shutdown"]
            assert not provider_sessions
            assert not server.registry.snapshot()
        finally:
            server.shutdown()

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))
