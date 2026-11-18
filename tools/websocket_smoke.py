#!/usr/bin/env python3
"""Check discovery, complete response streams and bounded WebSocket sessions."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from aiohttp import ClientSession, ClientTimeout, ClientWebSocketResponse, WSMsgType


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _headers() -> dict[str, str]:
    token = os.environ.get("BYOVA_WEBSOCKET_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _receive_json(socket: ClientWebSocketResponse) -> dict[str, Any]:
    message = await socket.receive()
    if message.type != WSMsgType.TEXT:
        raise RuntimeError("WebSocket closed or failed before a complete response")
    try:
        value = json.loads(message.data)
    except ValueError as error:
        raise RuntimeError("WebSocket returned invalid JSON") from error
    if not isinstance(value, dict):
        raise RuntimeError("WebSocket response must be a JSON object")
    return value


async def _response(
    socket: ClientWebSocketResponse, args: argparse.Namespace, conversation_id: str
) -> dict[str, Any]:
    frames = 0
    audio_bytes = 0
    sequence = 0
    streamed_audio = False
    while True:
        value = await _receive_json(socket)
        if value.get("type") != "VOICE_VA_RESPONSE":
            raise RuntimeError(
                "Expected VOICE_VA_RESPONSE; received an error or invalid frame"
            )
        seq = value.get("seq")
        if type(seq) is not int or seq <= sequence:
            raise RuntimeError("Response sequence must strictly increase")
        if value.get("conversation_id") != conversation_id:
            raise RuntimeError("Response belongs to a different conversation")
        sequence = seq
        payload = value.get("payload")
        if not isinstance(payload, dict) or payload.get("response_type") not in {
            "CHUNK",
            "FINAL",
            "SILENCE",
        }:
            raise RuntimeError("Invalid voice response payload")
        frames += 1
        prompts = payload.get("prompts", [])
        if not isinstance(prompts, list) or not all(
            isinstance(prompt, dict) for prompt in prompts
        ):
            raise RuntimeError("Invalid response prompts")
        for prompt in prompts:
            try:
                audio_bytes += len(
                    base64.b64decode(prompt.get("audio_content_b64", ""), validate=True)
                )
            except (ValueError, TypeError) as error:
                raise RuntimeError("Invalid response audio encoding") from error
        if args.include_audio:
            print(json.dumps(value))
        if payload["response_type"] == "CHUNK":
            streamed_audio = streamed_audio or any(
                prompt.get("audio_content_b64") for prompt in prompts
            )
        if payload["response_type"] == "FINAL":
            if streamed_audio and not any(
                prompt.get("audio_content_b64") == "" for prompt in prompts
            ):
                raise RuntimeError(
                    "Streamed audio FINAL is missing its explicit empty-audio terminator"
                )
            return {
                "conversation_id": conversation_id,
                "frames": frames,
                "audio_bytes": audio_bytes,
            }


async def _hold(
    socket: ClientWebSocketResponse, args: argparse.Namespace
) -> int | None:
    deadline = asyncio.get_running_loop().time() + args.hold_seconds
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        try:
            message = await asyncio.wait_for(socket.receive(), remaining)
        except asyncio.TimeoutError:
            break
        if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
            if args.expect_shutdown and socket.close_code == 1001:
                return 1001
            raise RuntimeError(
                "WebSocket closed unexpectedly while holding the session"
            )
        if message.type == WSMsgType.TEXT:
            try:
                value = json.loads(message.data)
            except ValueError as error:
                raise RuntimeError("Invalid JSON while holding the session") from error
            if not isinstance(value, dict) or value.get("type") != "VOICE_VA_RESPONSE":
                raise RuntimeError(
                    "Gateway error or invalid frame while holding the session"
                )
    if args.expect_shutdown:
        raise RuntimeError(
            "Gateway did not close the session with 1001 before the hold deadline"
        )
    return None


async def _probe(session: ClientSession, args: argparse.Namespace) -> dict[str, Any]:
    async def exchange() -> dict[str, Any]:
        path = "/v1/listVirtualAgents" if args.mode == "list" else "/v1/va"
        async with session.ws_connect(args.url.rstrip("/") + path) as socket:
            if args.mode == "list":
                await socket.send_json({"customer_org_id": args.org_id})
                value = await _receive_json(socket)
                agents = value.get("virtual_agents")
                if not isinstance(agents, list) or not all(
                    isinstance(agent, dict)
                    and isinstance(agent.get("id"), str)
                    and agent["id"]
                    for agent in agents
                ):
                    raise RuntimeError("Invalid virtual-agent discovery response")
                return value
            else:
                conversation_id = args.conversation_id or str(uuid.uuid4())
                payload = {
                    "conversation_id": conversation_id,
                    "customer_org_id": args.org_id,
                    "voice_va_input_type": {
                        "event_input": {"event_type": "SESSION_START"}
                    },
                }
                if args.agent_id:
                    payload["virtual_agent_id"] = args.agent_id
                await socket.send_json(
                    {
                        "type": "VOICE_VA_REQUEST",
                        "seq": 1,
                        "ts": _timestamp(),
                        "conversation_id": conversation_id,
                        "payload": payload,
                    }
                )
            result = await asyncio.wait_for(
                _response(socket, args, conversation_id), args.timeout
            )
            if args.hold_seconds:
                print(
                    json.dumps({"event": "session_ready", **result}),
                    file=sys.stderr,
                    flush=True,
                )
                result["close_code"] = await _hold(socket, args)
            return result

    return await asyncio.wait_for(exchange(), args.timeout + args.hold_seconds)


async def run(args: argparse.Namespace) -> None:
    if type(args.sessions) is not int or not 1 <= args.sessions <= 100:
        raise ValueError("--sessions must be between 1 and 100")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError("--timeout must be a finite positive number")
    if not math.isfinite(args.hold_seconds) or not 0 <= args.hold_seconds <= 300:
        raise ValueError("--hold-seconds must be between 0 and 300")
    if args.conversation_id and args.sessions != 1:
        raise ValueError("--conversation-id requires --sessions 1")
    if args.hold_seconds and args.mode != "session":
        raise ValueError("--hold-seconds requires --mode session")
    if args.expect_shutdown and not args.hold_seconds:
        raise ValueError("--expect-shutdown requires a positive --hold-seconds")
    async with ClientSession(
        headers=_headers(), timeout=ClientTimeout(total=args.timeout)
    ) as session:
        tasks = [
            asyncio.create_task(_probe(session, args)) for _ in range(args.sessions)
        ]
        try:
            results = await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    print(
        json.dumps(
            {"mode": args.mode, "sessions": len(results), "results": results}, indent=2
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    parser.add_argument("--mode", choices=("list", "session"), default="list")
    parser.add_argument("--org-id", default="local-test")
    parser.add_argument("--agent-id")
    parser.add_argument("--conversation-id")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--sessions", type=int, default=1, help="concurrent probes (1-100)"
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=0,
        help="hold completed sessions open (0-300 seconds)",
    )
    parser.add_argument(
        "--expect-shutdown",
        action="store_true",
        help="require a 1001 gateway shutdown during the hold",
    )
    parser.add_argument(
        "--include-audio",
        action="store_true",
        help="also print complete response frames, including audio and call content",
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
