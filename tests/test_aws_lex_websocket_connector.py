"""Exercise the Lex WebSocket adapter against a fake AWS SDK boundary."""

import asyncio
import base64
import gzip
import io
import json
from unittest.mock import MagicMock

import boto3
import pytest
from aiohttp.test_utils import TestClient, TestServer
from botocore.stub import Stubber

from src.connectors.aws_lex_connector import AWSLexConnector
from src.connectors.aws_lex_websocket_connector import AWSLexWebSocketConnector
from src.core.virtual_agent_router import VirtualAgentRouter
from src.transports.websocket_server import WebSocketGatewayServer
from src.utils.silero_speech_boundary import SpeechBoundarySignal


@pytest.fixture
def aws_clients(monkeypatch):
    models = MagicMock()
    models.list_bots.return_value = {
        "botSummaries": [{"botId": "test-bot", "botName": "Booking"}]
    }
    models.list_bot_aliases.return_value = {
        "botAliasSummaries": [{"botAliasId": "test-alias", "lastUpdatedDateTime": 1}]
    }
    runtime = MagicMock()

    def response(**kwargs):
        return {
            "messages": base64.b64encode(
                gzip.compress(json.dumps([{"content": "Test reply"}]).encode())
            ).decode(),
            "audioStream": io.BytesIO(b"\x00\x00" * 1600),
        }

    runtime.recognize_utterance.side_effect = response
    session = MagicMock()
    session.client.side_effect = {"lexv2-models": models, "lexv2-runtime": runtime}.get
    monkeypatch.setattr("boto3.Session", MagicMock(return_value=session))
    return models, runtime


def _router():
    router = VirtualAgentRouter()
    router.load_connectors(
        {
            "connectors": {
                name: {
                    "class": connector_class,
                    "module": f"connectors.{name}",
                    "config": {"region_name": "us-east-1"},
                }
                for name, connector_class in (
                    ("aws_lex_connector", "AWSLexConnector"),
                    ("aws_lex_websocket_connector", "AWSLexWebSocketConnector"),
                )
            }
        }
    )
    return router


def test_lex_adapters_have_separate_catalogs_and_sessions(aws_clients):
    router = _router()
    grpc_id = "aws_lex_connector: Booking"
    websocket_id = "aws_lex_websocket_connector: Booking"
    assert router.get_all_available_agents("grpc") == [grpc_id]
    assert router.get_all_available_agents("websocket") == [websocket_id]
    with pytest.raises(ValueError):
        router.get_connector_for_agent(grpc_id, transport="websocket")
    with pytest.raises(ValueError):
        router.get_connector_for_agent(websocket_id, transport="grpc")
    grpc = router.get_connector_for_agent(grpc_id)
    websocket = router.get_connector_for_agent(websocket_id)
    assert isinstance(grpc, AWSLexConnector)
    assert isinstance(websocket, AWSLexWebSocketConnector)
    grpc.start_conversation("grpc-call", {"virtual_agent_id": grpc_id})
    websocket.start_conversation("ws-call", {"virtual_agent_id": websocket_id})
    assert not grpc.session_manager.has_session("ws-call")
    websocket.end_conversation("ws-call")
    assert grpc.session_manager.has_session("grpc-call")
    grpc.end_conversation("grpc-call")


@pytest.mark.parametrize("connector_class", [AWSLexConnector, AWSLexWebSocketConnector])
def test_lex_adapter_uses_valid_aws_sdk_requests(monkeypatch, connector_class):
    session = boto3.Session(
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    models = session.client("lexv2-models")
    runtime = session.client("lexv2-runtime")
    model_stub, runtime_stub = Stubber(models), Stubber(runtime)
    model_stub.add_response(
        "list_bots",
        {"botSummaries": [{"botId": "ABCDEFGHIJ", "botName": "Booking"}]},
        {},
    )
    model_stub.add_response(
        "list_bot_aliases",
        {"botAliasSummaries": [{"botAliasId": "TSTALIASID", "botAliasName": "Test"}]},
        {"botId": "ABCDEFGHIJ"},
    )
    runtime_stub.add_response(
        "recognize_utterance",
        {"contentType": "audio/pcm"},
        {
            "botId": "ABCDEFGHIJ",
            "botAliasId": "TSTALIASID",
            "localeId": "en_US",
            "sessionId": "session_sdk-call",
            "requestContentType": "text/plain; charset=utf-8",
            "responseContentType": "audio/pcm",
            "inputStream": b"hello",
        },
    )
    fake_session = MagicMock()
    fake_session.client.side_effect = {
        "lexv2-models": models,
        "lexv2-runtime": runtime,
    }.get
    monkeypatch.setattr("boto3.Session", MagicMock(return_value=fake_session))
    try:
        with model_stub, runtime_stub:
            connector = connector_class({"region_name": "us-east-1"})
            (agent_id,) = connector.get_available_agents()
            response = connector.start_conversation(
                "sdk-call", {"virtual_agent_id": agent_id}
            )
            assert response["message_type"] == "welcome"
            model_stub.assert_no_pending_responses()
            runtime_stub.assert_no_pending_responses()
            connector.end_conversation("sdk-call")
    finally:
        models.close()
        runtime.close()


@pytest.mark.parametrize("connector_class", [AWSLexConnector, AWSLexWebSocketConnector])
def test_lex_preserves_all_dtmf_symbols(aws_clients, connector_class):
    connector = connector_class({"region_name": "us-east-1"})
    connector._send_text_to_lex = MagicMock(return_value={"message_type": "response"})
    connector._handle_dtmf_input(
        "call",
        {"dtmf_data": {"dtmf_events": list(range(1, 17))}},
        "bot",
        "session",
        "Booking",
    )
    connector._send_text_to_lex.assert_called_once_with("call", "1234567890ABCD*#")


@pytest.mark.parametrize("invalid_digit", [0, 17, -1, True, "1"])
def test_lex_rejects_unknown_dtmf_without_submitting_text(aws_clients, invalid_digit):
    connector = AWSLexWebSocketConnector({"region_name": "us-east-1"})
    with pytest.raises(ValueError, match="Unsupported DTMF"):
        connector._handle_dtmf_input(
            "call",
            {"dtmf_data": {"dtmf_events": [invalid_digit]}},
            "bot",
            "session",
            "Booking",
        )
    aws_clients[1].recognize_utterance.assert_not_called()


def _request(seq, input_value):
    return {
        "type": "VOICE_VA_REQUEST",
        "seq": seq,
        "ts": "2026-10-18T12:00:00Z",
        "conversation_id": "ws-call",
        "payload": {
            "conversation_id": "ws-call",
            "customer_org_id": "org-test",
            "virtual_agent_id": "aws_lex_websocket_connector: Booking",
            "voice_va_input_type": input_value,
        },
    }


def test_lex_socket_discovery_voice_dtmf_and_cleanup(aws_clients, monkeypatch):
    # Keep boundary detection deterministic; exercise real buffering/conversion.
    observer = MagicMock()
    observer.observe.return_value = [
        SpeechBoundarySignal("speech_ended", "ws-call", 8000)
    ]
    monkeypatch.setattr(
        "src.core.wxcc_gateway_server.SileroSpeechBoundaryObserver",
        MagicMock(return_value=observer),
    )
    router = _router()
    connector = router.get_connector_for_agent("aws_lex_websocket_connector: Booking")
    runtime = aws_clients[1]

    async def scenario():
        server = WebSocketGatewayServer(router, allow_unauthenticated_local_dev=True)
        client = TestClient(TestServer(server.create_app()))
        await client.start_server()
        try:
            discovery = await client.ws_connect("/v1/listVirtualAgents")
            await discovery.send_json({"customer_org_id": "org-test"})
            catalog = await discovery.receive_json(timeout=5)
            assert [agent["id"] for agent in catalog["virtual_agents"]] == [
                "aws_lex_websocket_connector: Booking"
            ]
            await discovery.close()

            socket = await client.ws_connect("/v1/va")
            await socket.send_json(
                _request(1, {"event_input": {"event_type": "SESSION_START"}})
            )

            async def receive_audio():
                for _ in range(5):
                    frame = await socket.receive_json(timeout=5)
                    assert frame["type"] == "VOICE_VA_RESPONSE"
                    payload = frame["payload"]
                    assert payload["response_type"] == "FINAL"
                    for prompt in payload.get("prompts", []):
                        if prompt.get("audio_content_b64"):
                            audio = base64.b64decode(prompt["audio_content_b64"])
                            assert audio[:4] == b"RIFF"
                            assert audio[8:12] == b"WAVE"
                            assert payload["input_mode"] == "INPUT_VOICE_DTMF"
                            assert payload["input_handling_config"]["dtmf_config"] == {
                                "dtmf_input_length": 10,
                                "inter_digit_timeout_msec": 5000,
                                "termchar": "DTMF_DIGIT_POUND",
                            }
                            return frame
                raise AssertionError("Lex returned no WAV response")

            welcome = await receive_audio()
            assert (
                runtime.recognize_utterance.call_args.kwargs["inputStream"] == b"hello"
            )
            await socket.send_json(
                _request(
                    2,
                    {
                        "audio_input": {
                            "caller_audio_b64": base64.b64encode(
                                b"\xff" * 1600
                            ).decode(),
                            "encoding": "MULAW_FORMAT",
                            "sample_rate_hertz": 8000,
                        }
                    },
                )
            )
            voice = await receive_audio()
            voice_request = runtime.recognize_utterance.call_args.kwargs
            assert (
                voice_request["requestContentType"]
                == "audio/l16; rate=16000; channels=1"
            )
            assert isinstance(voice_request["inputStream"], bytes)
            assert voice_request["inputStream"]
            await socket.send_json(
                _request(
                    3,
                    {
                        "dtmf_input": {
                            "dtmf_events": [
                                "DTMF_DIGIT_ZERO",
                                "DTMF_DIGIT_STAR",
                                "DTMF_DIGIT_POUND",
                            ]
                        }
                    },
                )
            )
            digits = await receive_audio()
            assert runtime.recognize_utterance.call_args.kwargs["inputStream"] == b"0*#"
            assert welcome["seq"] < voice["seq"] < digits["seq"]
            await socket.close()
        finally:
            await client.close()
        assert not connector.session_manager.has_session("ws-call")
        assert not connector.audio_processor.has_audio_buffer("ws-call")
        assert not server.registry.snapshot()

    asyncio.run(scenario())
