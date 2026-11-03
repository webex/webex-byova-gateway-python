import json
import os
import signal
import socket
import subprocess

import pytest
from byova_e2e.gateway_tunnel import (
    GatewayTunnelError,
    SSMPortForward,
    SSMPortForwardConfig,
    _local_port_available,
    gateway_event_tunnel,
)


def test_local_port_check_rejects_an_active_listener() -> None:
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        assert not _local_port_available(listener.getsockname()[1])


@pytest.mark.skipif(os.name == "nt", reason="POSIX socket reuse behavior")
def test_local_port_check_allows_a_closed_tunnel_in_time_wait() -> None:
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        with socket.create_connection(("127.0.0.1", port)) as client:
            connection, _ = listener.accept()
            connection.close()
            assert client.recv(1) == b""

    assert _local_port_available(port)


def test_ssm_command_preserves_values_as_argv_data() -> None:
    config = SSMPortForwardConfig(
        target="i-0123456789abcdef0",
        remote_host="gateway.internal.example",
        remote_port=8080,
        local_port=18080,
        region="us-east-1",
        profile="example-profile",
    )

    command = config.command()

    assert command[:3] == ("aws", "ssm", "start-session")
    assert command[command.index("--target") + 1] == "i-0123456789abcdef0"
    parameters = json.loads(command[command.index("--parameters") + 1])
    assert parameters == {
        "host": ["gateway.internal.example"],
        "portNumber": ["8080"],
        "localPortNumber": ["18080"],
    }
    assert config.events_url == "http://127.0.0.1:18080"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("target", "instance;whoami", "SSM target"),
        ("target", "i-0123456789", "SSM target"),
        ("remote_host", "10.0.1.1;whoami", "SSM remote host"),
        ("remote_port", 0, "SSM remote port"),
        ("local_port", 65536, "SSM local port"),
        ("profile", "profile;whoami", "AWS profile"),
    ],
)
def test_ssm_config_rejects_command_injection_values(
    field: str, value: object, message: str
) -> None:
    values = {
        "target": "i-0123456789abcdef0",
        "remote_host": "gateway.internal",
        "remote_port": 8080,
        "local_port": 18080,
        "profile": None,
    }
    values[field] = value

    with pytest.raises(GatewayTunnelError, match=message):
        SSMPortForwardConfig(**values)


def test_tunnel_requires_aws_cli_and_session_manager_plugin(monkeypatch) -> None:
    config = SSMPortForwardConfig(
        target="i-0123456789abcdef0",
        remote_host="gateway.internal.example",
    )
    monkeypatch.setattr("byova_e2e.gateway_tunnel.shutil.which", lambda _name: None)

    with pytest.raises(GatewayTunnelError, match="AWS CLI is required"):
        SSMPortForward(config).start()


def test_tunnel_rejects_an_occupied_loopback_port(monkeypatch) -> None:
    config = SSMPortForwardConfig(
        target="i-0123456789abcdef0",
        remote_host="gateway.internal.example",
    )
    monkeypatch.setattr(
        "byova_e2e.gateway_tunnel.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr(
        "byova_e2e.gateway_tunnel._local_port_available", lambda _port: False
    )

    with pytest.raises(GatewayTunnelError, match="already in use"):
        SSMPortForward(config).start()


def test_tunnel_starts_without_a_shell_and_is_stopped(monkeypatch) -> None:
    config = SSMPortForwardConfig(
        target="i-0123456789abcdef0",
        remote_host="gateway.internal.example",
    )
    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 1234

        def poll(self):
            return captured.get("returncode")

        def wait(self, timeout=None):
            captured["wait_timeout"] = timeout
            captured["returncode"] = 0
            return 0

        def kill(self):
            captured["killed"] = True
            captured["returncode"] = -9

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(
        "byova_e2e.gateway_tunnel.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr(
        "byova_e2e.gateway_tunnel._local_port_available", lambda _port: True
    )
    monkeypatch.setattr(
        "byova_e2e.gateway_tunnel._local_port_ready", lambda _port: True
    )
    monkeypatch.setattr("byova_e2e.gateway_tunnel.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "byova_e2e.gateway_tunnel.os.killpg",
        lambda pid, sent_signal: captured.update(
            {"terminated_pid": pid, "terminated_signal": sent_signal}
        ),
    )

    with gateway_event_tunnel(config):
        assert captured["command"] == config.command()

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is not subprocess.PIPE
    assert captured["terminated_pid"] == 1234
    assert captured["terminated_signal"] is not None
    assert captured["wait_timeout"] == 5


def test_tunnel_reports_early_process_output(monkeypatch) -> None:
    config = SSMPortForwardConfig(
        target="i-0123456789abcdef0",
        remote_host="gateway.internal.example",
    )

    class FailedProcess:
        pid = 1234

        def poll(self):
            return 1

    def fake_popen(_command, **kwargs):
        kwargs["stdout"].write(b"Session Manager could not connect\n")
        kwargs["stdout"].flush()
        return FailedProcess()

    monkeypatch.setattr(
        "byova_e2e.gateway_tunnel.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr(
        "byova_e2e.gateway_tunnel._local_port_available", lambda _port: True
    )
    monkeypatch.setattr("byova_e2e.gateway_tunnel.subprocess.Popen", fake_popen)

    with pytest.raises(GatewayTunnelError, match="Session Manager could not connect"):
        SSMPortForward(config).start()


def test_tunnel_timeout_stops_process_and_preserves_cleanup(monkeypatch) -> None:
    config = SSMPortForwardConfig(
        target="i-0123456789abcdef0",
        remote_host="gateway.internal.example",
        startup_timeout_seconds=0.01,
    )
    captured: dict[str, object] = {}

    class HungProcess:
        pid = 1234

        def poll(self):
            return None

        def wait(self, timeout=None):
            captured["wait_timeout"] = timeout
            raise subprocess.TimeoutExpired("aws", timeout)

        def terminate(self):
            captured["terminated"] = True

        def kill(self):
            captured["killed"] = True

    monkeypatch.setattr(
        "byova_e2e.gateway_tunnel.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr(
        "byova_e2e.gateway_tunnel._local_port_available", lambda _port: True
    )
    monkeypatch.setattr(
        "byova_e2e.gateway_tunnel._local_port_ready", lambda _port: False
    )
    monkeypatch.setattr(
        "byova_e2e.gateway_tunnel.subprocess.Popen",
        lambda _command, **_kwargs: HungProcess(),
    )
    monkeypatch.setattr(
        "byova_e2e.gateway_tunnel.os.killpg",
        lambda _pid, sent_signal: captured.setdefault("signals", []).append(
            sent_signal
        ),
    )

    with pytest.raises(GatewayTunnelError, match="did not become ready"):
        SSMPortForward(config).start()

    assert captured["signals"] == [signal.SIGTERM, signal.SIGKILL]
    assert captured["wait_timeout"] == 5
