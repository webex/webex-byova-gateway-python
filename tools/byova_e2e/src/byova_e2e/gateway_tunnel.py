"""Securely forward a private gateway monitoring endpoint through AWS SSM."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import BinaryIO, Iterator

_SSM_TARGET_PATTERN = re.compile(r"^(?:i|mi)-(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{17})$")
_DNS_NAME_PATTERN = re.compile(
    r"^(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$"
)
_AWS_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]{1,128}$")


class GatewayTunnelError(RuntimeError):
    """The private gateway event tunnel could not be started or stopped safely."""


@dataclass(frozen=True)
class SSMPortForwardConfig:
    """Validated inputs for an SSM remote-host port-forwarding session."""

    target: str
    remote_host: str
    remote_port: int = 8080
    local_port: int = 18080
    region: str | None = None
    profile: str | None = None
    startup_timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not _SSM_TARGET_PATTERN.fullmatch(self.target):
            raise GatewayTunnelError("SSM target must be an EC2 or managed-instance ID")
        _validate_remote_host(self.remote_host)
        _validate_port(self.remote_port, "remote port")
        _validate_port(self.local_port, "local port")
        if self.region is not None and not _AWS_NAME_PATTERN.fullmatch(self.region):
            raise GatewayTunnelError("AWS region contains unsupported characters")
        if self.profile is not None and not _AWS_NAME_PATTERN.fullmatch(self.profile):
            raise GatewayTunnelError("AWS profile contains unsupported characters")
        if self.startup_timeout_seconds <= 0:
            raise GatewayTunnelError("Tunnel startup timeout must be greater than zero")

    @property
    def events_url(self) -> str:
        """Return the loopback-only monitoring URL consumed by the observer."""
        return f"http://127.0.0.1:{self.local_port}"

    def command(self) -> tuple[str, ...]:
        """Build the AWS CLI argv without invoking a command shell."""
        parameters = json.dumps(
            {
                "host": [self.remote_host],
                "portNumber": [str(self.remote_port)],
                "localPortNumber": [str(self.local_port)],
            },
            separators=(",", ":"),
        )
        command = [
            "aws",
            "ssm",
            "start-session",
            "--target",
            self.target,
            "--document-name",
            "AWS-StartPortForwardingSessionToRemoteHost",
            "--parameters",
            parameters,
        ]
        if self.region:
            command.extend(("--region", self.region))
        if self.profile:
            command.extend(("--profile", self.profile))
        return tuple(command)


class SSMPortForward:
    """Own one AWS CLI Session Manager port-forward subprocess."""

    def __init__(self, config: SSMPortForwardConfig) -> None:
        self.config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._output: BinaryIO | None = None

    def start(self) -> None:
        """Start the tunnel and wait until its loopback listener is available."""
        if self._process is not None:
            raise GatewayTunnelError("Gateway event tunnel is already running")
        if shutil.which("aws") is None:
            raise GatewayTunnelError("AWS CLI is required for the gateway event tunnel")
        if shutil.which("session-manager-plugin") is None:
            raise GatewayTunnelError(
                "AWS Session Manager plugin is required for the gateway event tunnel"
            )
        if not _local_port_available(self.config.local_port):
            raise GatewayTunnelError(
                f"Local gateway event port {self.config.local_port} is already in use"
            )

        output = tempfile.TemporaryFile(mode="w+b")
        try:
            self._process = subprocess.Popen(
                self.config.command(),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                shell=False,
                start_new_session=os.name != "nt",
            )
        except OSError as error:
            output.close()
            raise GatewayTunnelError(
                f"Unable to start the gateway event tunnel: {error}"
            ) from error
        self._output = output

        deadline = time.monotonic() + self.config.startup_timeout_seconds
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                output = _safe_process_output(self._output)
                self._process = None
                self._close_output()
                suffix = f": {output}" if output else ""
                raise GatewayTunnelError(
                    f"Gateway event tunnel exited before it was ready{suffix}"
                )
            if _local_port_ready(self.config.local_port):
                return
            time.sleep(0.1)

        self.stop()
        raise GatewayTunnelError(
            "Gateway event tunnel did not become ready within "
            f"{self.config.startup_timeout_seconds:g} seconds"
        )

    def stop(self) -> None:
        """Terminate the AWS CLI and Session Manager plugin process group."""
        process = self._process
        self._process = None
        if process is None:
            self._close_output()
            return
        try:
            if process.poll() is None:
                _terminate_process_tree(process, force=False)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _terminate_process_tree(process, force=True)
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            self._close_output()

    def _close_output(self) -> None:
        output = self._output
        self._output = None
        if output is not None:
            output.close()


@contextmanager
def gateway_event_tunnel(
    config: SSMPortForwardConfig | None,
) -> Iterator[None]:
    """Run an optional SSM port-forward for the duration of one E2E call."""
    if config is None:
        yield
        return
    tunnel = SSMPortForward(config)
    tunnel.start()
    try:
        yield
    finally:
        tunnel.stop()


def _validate_remote_host(value: str) -> None:
    if not value or any(character.isspace() for character in value):
        raise GatewayTunnelError("SSM remote host must be an IP address or DNS name")
    try:
        ipaddress.ip_address(value)
        return
    except ValueError:
        pass
    if not _DNS_NAME_PATTERN.fullmatch(value):
        raise GatewayTunnelError("SSM remote host must be an IP address or DNS name")


def _validate_port(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise GatewayTunnelError(f"SSM {name} must be between 1 and 65535")


def _local_port_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            if os.name != "nt":
                # Match the SSM listener so TIME_WAIT does not block the next run.
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", port))
    except OSError:
        return False
    return True


def _local_port_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def _terminate_process_tree(process: subprocess.Popen[bytes], *, force: bool) -> None:
    try:
        if os.name == "nt":
            command = ["taskkill", "/PID", str(process.pid), "/T"]
            if force:
                command.append("/F")
            subprocess.run(
                command,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                shell=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill() if force else process.terminate()
        except OSError:
            pass


def _safe_process_output(output: BinaryIO | None) -> str:
    if output is None or output.closed:
        return ""
    output.flush()
    output.seek(0, os.SEEK_END)
    size = output.tell()
    output.seek(max(0, size - 4096))
    normalized = " ".join(output.read().decode("utf-8", errors="replace").split())
    return normalized[-500:]
