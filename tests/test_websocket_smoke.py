"""Real-socket checks that keep the smoke client from reporting false success."""

import argparse
import asyncio
import base64
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from tools.websocket_smoke import run


def _args(server, **overrides):
    values = {
        "url": str(server.make_url("/")).rstrip("/").replace("http://", "ws://"),
        "mode": "session",
        "org_id": "test-org",
        "agent_id": "Test Agent",
        "conversation_id": None,
        "timeout": 1,
        "include_audio": False,
        "sessions": 1,
        "hold_seconds": 0,
        "expect_shutdown": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _frame(conversation_id, seq=1, response_type="FINAL", **payload):
    return {
        "type": "VOICE_VA_RESPONSE",
        "seq": seq,
        "conversation_id": conversation_id,
        "payload": {"response_type": response_type, **payload},
    }


async def _server(handler):
    app = web.Application()
    app.router.add_get("/v1/va", handler)
    app.router.add_get("/v1/listVirtualAgents", handler)
    server = TestServer(app)
    await server.start_server()
    return server


def test_concurrent_probes_wait_for_all_chunks_and_redact_content(capsys):
    async def scenario():
        started = set()
        all_started = asyncio.Event()

        async def handler(request):
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            start = await socket.receive_json()
            conversation_id = start["conversation_id"]
            started.add(conversation_id)
            if len(started) == 4:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), 1)
            await socket.send_json(
                _frame(
                    conversation_id,
                    response_type="CHUNK",
                    prompts=[
                        {
                            "audio_content_b64": base64.b64encode(b"x" * 160).decode(),
                            "text": "private utterance",
                        }
                    ],
                )
            )
            await socket.send_json(
                _frame(conversation_id, seq=2, prompts=[{"audio_content_b64": ""}])
            )
            await socket.receive()
            return socket

        server = await _server(handler)
        try:
            await run(_args(server, sessions=4))
        finally:
            await server.close()

    asyncio.run(asyncio.wait_for(scenario(), 5))
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["sessions"] == 4
    assert all(
        item["frames"] == 2 and item["audio_bytes"] == 160 for item in result["results"]
    )
    assert len({item["conversation_id"] for item in result["results"]}) == 4
    assert "private utterance" not in output
    assert "eHh4" not in output


@pytest.mark.parametrize(
    "failure",
    [
        "early-close",
        "missing-terminator",
        "wrong-conversation",
        "duplicate-sequence",
        "error",
        "invalid-json",
        "invalid-audio",
        "drip-without-final",
    ],
)
def test_incomplete_or_invalid_stream_fails(failure, capsys):
    async def scenario():
        async def handler(request):
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            start = await socket.receive_json()
            conversation_id = start["conversation_id"]
            if failure == "invalid-json":
                await socket.send_str("[]")
            elif failure == "error":
                await socket.send_json(
                    {"type": "ERROR", "payload": {"message": "private error"}}
                )
            else:
                await socket.send_json(
                    _frame(
                        conversation_id,
                        response_type="CHUNK",
                        prompts=[
                            {
                                "audio_content_b64": "!"
                                if failure == "invalid-audio"
                                else "eA==",
                            }
                        ],
                    )
                )
                if failure == "early-close":
                    await socket.close()
                elif failure == "drip-without-final":
                    for seq in range(2, 100):
                        await asyncio.sleep(0.01)
                        if (
                            socket.closed
                            or request.transport is None
                            or request.transport.is_closing()
                        ):
                            break
                        try:
                            await socket.send_json(
                                _frame(conversation_id, seq, "SILENCE")
                            )
                        except ConnectionResetError:
                            break
                else:
                    final = _frame(
                        "other-call"
                        if failure == "wrong-conversation"
                        else conversation_id,
                        seq=1 if failure == "duplicate-sequence" else 2,
                        prompts=[]
                        if failure == "missing-terminator"
                        else [{"audio_content_b64": ""}],
                    )
                    await socket.send_json(final)
            await socket.close()
            return socket

        server = await _server(handler)
        try:
            expected_error = (
                asyncio.TimeoutError
                if failure == "drip-without-final"
                else RuntimeError
            )
            with pytest.raises(expected_error):
                await run(
                    _args(
                        server, timeout=0.08 if failure == "drip-without-final" else 1
                    )
                )
        finally:
            await server.close()

    asyncio.run(asyncio.wait_for(scenario(), 5))
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "close_code,expect_shutdown,passes",
    [
        (1001, True, True),
        (1000, True, False),
        (1001, False, False),
        (None, False, True),
        (None, True, False),
    ],
)
def test_shutdown_requires_complete_response_and_expected_1001(
    close_code, expect_shutdown, passes, capsys
):
    async def scenario():
        async def handler(request):
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            start = await socket.receive_json()
            await socket.send_json(_frame(start["conversation_id"]))
            if close_code is not None:
                await socket.close(code=close_code)
            else:
                await socket.receive()
            return socket

        server = await _server(handler)
        try:
            args = _args(server, hold_seconds=0.02, expect_shutdown=expect_shutdown)
            if passes:
                await run(args)
            else:
                with pytest.raises(RuntimeError):
                    await run(args)
        finally:
            await server.close()

    asyncio.run(asyncio.wait_for(scenario(), 5))
    output = capsys.readouterr().out
    if passes:
        assert json.loads(output)["results"][0]["close_code"] == close_code
    else:
        assert output == ""


def test_discovery_cannot_succeed_on_an_error_frame():
    async def scenario():
        async def handler(request):
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            await socket.receive_json()
            await socket.send_json({"type": "ERROR"})
            await socket.close()
            return socket

        server = await _server(handler)
        try:
            with pytest.raises(RuntimeError, match="discovery"):
                await run(_args(server, mode="list"))
        finally:
            await server.close()

    asyncio.run(asyncio.wait_for(scenario(), 5))


@pytest.mark.parametrize(
    "overrides",
    [
        {"sessions": 0},
        {"sessions": 101},
        {"timeout": float("nan")},
        {"hold_seconds": float("inf")},
        {"hold_seconds": -1},
        {"conversation_id": "same-call", "sessions": 2},
        {"expect_shutdown": True},
        {"mode": "list", "hold_seconds": 1},
    ],
)
def test_invalid_probe_settings_fail_before_connecting(overrides):
    args = argparse.Namespace(
        sessions=1,
        timeout=1,
        hold_seconds=0,
        conversation_id=None,
        mode="session",
        expect_shutdown=False,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    with pytest.raises(ValueError):
        asyncio.run(run(args))


def test_failed_probe_cancels_peer_and_closes_its_socket(capsys):
    async def scenario():
        peer_ready = asyncio.Event()
        peer_closed = asyncio.Event()
        count = 0

        async def handler(request):
            nonlocal count
            count += 1
            index = count
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            start = await socket.receive_json()
            if index == 1:
                await socket.send_json(_frame(start["conversation_id"]))
                peer_ready.set()
                await socket.receive()
                peer_closed.set()
            else:
                await peer_ready.wait()
                await socket.send_json({"type": "ERROR"})
            await socket.close()
            return socket

        server = await _server(handler)
        try:
            with pytest.raises(RuntimeError, match="invalid frame"):
                await run(_args(server, sessions=2, hold_seconds=30))
            await asyncio.wait_for(peer_closed.wait(), 1)
        finally:
            await server.close()

    asyncio.run(asyncio.wait_for(scenario(), 5))
    assert capsys.readouterr().out == ""
