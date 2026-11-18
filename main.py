#!/usr/bin/env python3
"""
Main entry point for the Webex Contact Center BYOVA Gateway.

This script loads configuration, initializes the virtual agent router,
creates the gRPC server, and starts listening for requests.
"""

import logging
import os
import signal
import sys
import threading
from concurrent import futures
from pathlib import Path
from typing import Optional

import grpc
import yaml

# Add src and src/core to Python path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent / "src" / "core"))

from grpc_health.v1 import health_pb2_grpc

from auth.jwt_interceptor import JWTAuthInterceptor

# Import JWT authentication components (required)
from auth.jwt_validator import JWKSCache, JWTValidator
from core.conversation_registry import ConversationRegistry
from core.datasource_lifecycle import (
    DEFAULT_WEBSOCKET_SCHEMA_ID,
    create_data_source_lifecycle,
)
from core.health_service import HealthCheckService
from core.transport_profiles import (
    enabled_transport_profiles,
    validate_transport_profiles,
)
from core.virtual_agent_router import VirtualAgentRouter
from core.wxcc_gateway_server import WxCCGatewayServer
from monitoring.app import run_web_app
from src.generated.voicevirtualagent_pb2_grpc import (
    add_VoiceVirtualAgentServicer_to_server,
)
from transports.websocket_server import (
    WebSocketGatewayRuntime,
    WebSocketGatewayServer,
)


def setup_logging(config: dict) -> None:
    """
    Set up logging configuration.

    Args:
        config: Configuration dictionary containing logging settings
    """
    logging_config = config.get("logging", {})

    # Configure gateway logging
    gateway_config = logging_config.get("gateway", {})
    gateway_log_level = getattr(logging, gateway_config.get("level", "INFO").upper())
    gateway_log_format = gateway_config.get(
        "format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    stdout_only = os.environ.get("BYOVA_STDOUT_ONLY_LOGGING", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    gateway_log_file = (
        "" if stdout_only else gateway_config.get("file", "logs/gateway.log")
    )

    # Create logs directory if it doesn't exist
    if gateway_log_file:
        log_path = Path(gateway_log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Gateway log file path: {log_path.absolute()}")

    # Clear any existing handlers
    logging.getLogger().handlers.clear()

    # Configure gateway logging handlers
    handlers = [logging.StreamHandler(sys.stdout)]

    # Add file handler for gateway logging
    if gateway_log_file:
        try:
            file_handler = logging.FileHandler(gateway_log_file)
            file_handler.setFormatter(logging.Formatter(gateway_log_format))
            handlers.append(file_handler)
            print(f"Gateway logging enabled: {gateway_log_file}")
        except Exception as e:
            print(f"Warning: Could not create gateway log file {gateway_log_file}: {e}")

    # Configure gateway logging
    logging.basicConfig(
        level=gateway_log_level,
        format=gateway_log_format,
        handlers=handlers,
        force=True,  # Force reconfiguration
    )

    # Test logging
    logging.info("Gateway logging system initialized")
    print(
        f"Gateway logging level set to: {logging.getLevelName(logging.getLogger().level)}"
    )

    # Configure web logging separately
    web_config = logging_config.get("web", {})
    web_log_level = getattr(logging, web_config.get("level", "WARNING").upper())
    web_log_format = web_config.get(
        "format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    web_log_file = "" if stdout_only else web_config.get("file", "logs/web.log")

    # Create web log file if specified
    if web_log_file:
        web_log_path = Path(web_log_file)
        web_log_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Web log file path: {web_log_path.absolute()}")

        try:
            # Configure web-specific loggers
            web_logger = logging.getLogger("werkzeug")
            web_logger.setLevel(web_log_level)

            # Add file handler for web logging
            web_file_handler = logging.FileHandler(web_log_file)
            web_file_handler.setFormatter(logging.Formatter(web_log_format))
            web_logger.addHandler(web_file_handler)

            # Also configure Flask logger
            flask_logger = logging.getLogger("flask")
            flask_logger.setLevel(web_log_level)
            flask_logger.addHandler(web_file_handler)

            print(f"Web logging enabled: {web_log_file}")
        except Exception as e:
            print(f"Warning: Could not create web log file {web_log_file}: {e}")


def load_config(config_path: str = "config/config.yaml") -> dict:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to the configuration file

    Returns:
        Configuration dictionary

    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If config file is invalid
    """
    try:
        with open(config_path) as file:
            config = yaml.safe_load(file)

        logging.info(f"Configuration loaded from {config_path}")
        return config

    except FileNotFoundError:
        logging.error(f"Configuration file not found: {config_path}")
        raise
    except yaml.YAMLError as e:
        logging.error(f"Invalid YAML in configuration file: {e}")
        raise


def create_router_config(config: dict) -> dict:
    """
    Extract router configuration from the main config.

    Args:
        config: Main configuration dictionary

    Returns:
        Router configuration dictionary
    """
    # The connectors config is already in the correct dictionary format
    connectors_config = config.get("connectors", {})

    # Ensure each connector has the required fields
    for connector_id, connector_config in connectors_config.items():
        if not isinstance(connector_config, dict):
            raise ValueError(
                f"Connector {connector_id} configuration must be a dictionary"
            )

        # Ensure required fields exist
        if "class" not in connector_config:
            raise ValueError(f"Connector {connector_id} missing required 'class' field")
        if "module" not in connector_config:
            raise ValueError(
                f"Connector {connector_id} missing required 'module' field"
            )
        if "config" not in connector_config:
            connectors_config[connector_id]["config"] = {}

    return {"connectors": connectors_config}


def create_jwt_interceptor(
    config: dict,
    logger: logging.Logger,
    shared_jwks_cache: Optional[JWKSCache] = None,
) -> Optional[JWTAuthInterceptor]:
    """
    Create JWT authentication interceptor if configured.

    Args:
        config: Configuration dictionary containing JWT settings
        logger: Logger instance

    Returns:
        JWTAuthInterceptor instance or None if not configured

    Raises:
        ValueError: If JWT validation is enabled but datasource_url is not configured
    """
    jwt_config = config.get("jwt_validation", {})

    if not jwt_config.get("enabled", False):
        logger.info("JWT validation is disabled in configuration")
        return None

    # Validate required configuration
    datasource_url = jwt_config.get("datasource_url", "")
    if not datasource_url:
        error_msg = (
            "JWT validation is enabled but datasource_url is not configured. "
            "Please set jwt_validation.datasource_url in config.yaml or disable JWT validation."
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Get configuration values
    datasource_schema_uuid = jwt_config.get(
        "datasource_schema_uuid", "5397013b-7920-4ffc-807c-e8a3e0a18f43"
    )
    cache_duration_minutes = jwt_config.get("cache_duration_minutes", 60)
    enforce_validation = jwt_config.get("enforce_validation", True)

    try:
        # Create JWT validator
        validator_arguments = {
            "datasource_url": datasource_url,
            "datasource_schema_uuid": datasource_schema_uuid,
            "cache_duration_minutes": cache_duration_minutes,
        }
        if shared_jwks_cache is not None:
            validator_arguments["jwks_cache"] = shared_jwks_cache
        validator = JWTValidator(**validator_arguments)

        # Create interceptor
        interceptor = JWTAuthInterceptor(
            jwt_validator=validator,
            enabled=True,
            enforce=enforce_validation,
        )

        logger.info("JWT authentication interceptor created successfully")
        logger.info(f"Datasource URL: {datasource_url}")
        logger.info(
            f"Enforcement: {'ENABLED' if enforce_validation else 'DISABLED (logging only)'}"
        )

        return interceptor

    except Exception as e:
        logger.error(f"Failed to create JWT interceptor: {e}")

        # If JWT validation is enabled, this is a fatal error
        jwt_config = config.get("jwt_validation", {})
        if jwt_config.get("enabled", True):
            error_msg = (
                "Failed to create JWT interceptor but JWT validation is enabled. "
                "This is a fatal configuration error. Please check your configuration and dependencies."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
        else:
            logger.warning(
                "JWT validation is disabled, continuing without JWT interceptor"
            )
            return None


def enabled_transports(config: dict) -> tuple[bool, bool]:
    """Return enabled listeners, preserving grpc-only legacy configuration."""
    names = {profile.name for profile in enabled_transport_profiles(config)}
    return "grpc" in names, "websocket" in names


def create_websocket_jwt_validator(
    config: dict,
    logger: logging.Logger,
    shared_jwks_cache: Optional[JWKSCache] = None,
) -> Optional[JWTValidator]:
    """Create the independently datasource-bound WebSocket JWT profile."""
    jwt_config = config.get("websocket_jwt_validation", {})
    if not jwt_config.get("enabled", False):
        return None
    datasource_url = str(jwt_config.get("datasource_url", "")).strip()
    if not datasource_url:
        raise ValueError(
            "WebSocket JWT validation is enabled but datasource_url is not "
            "configured. Set websocket_jwt_validation.datasource_url."
        )
    arguments = {
        "datasource_url": datasource_url,
        "datasource_schema_uuid": jwt_config.get(
            "datasource_schema_uuid", DEFAULT_WEBSOCKET_SCHEMA_ID
        ),
        "cache_duration_minutes": jwt_config.get("cache_duration_minutes", 60),
    }
    if shared_jwks_cache is not None:
        arguments["jwks_cache"] = shared_jwks_cache
    validator = JWTValidator(**arguments)
    logger.info("WebSocket JWT validator created for %s", datasource_url)
    return validator


class CombinedMonitoringGateway:
    """Present both listener states through the existing monitoring interface."""

    def __init__(self, *gateways) -> None:
        self.gateways = [gateway for gateway in gateways if gateway is not None]

    def get_active_conversations(self) -> dict:
        active = {}
        for gateway in self.gateways:
            active.update(gateway.get_active_conversations())
        return active

    def get_connection_events(self) -> list:
        events = []
        for gateway in self.gateways:
            events.extend(gateway.get_connection_events())
        return events[-100:]

    def get_health_status(self) -> dict:
        for gateway in self.gateways:
            health = getattr(gateway, "get_health_status", None)
            if health:
                return health()
        return {"status": "healthy"}


def create_streaming_executor(servicer, max_workers: int):
    """Create and attach a dedicated executor for caller streaming RPCs."""
    executor = futures.ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="byova-stream",
    )
    servicer.ProcessCallerInput.__func__.experimental_thread_pool = executor
    return executor


def install_shutdown_signal_handlers(
    shutdown_event: threading.Event,
) -> dict[int, object]:
    """Make SIGINT and SIGTERM request the same orderly shutdown path."""
    if threading.current_thread() is not threading.main_thread():
        return {}

    previous_handlers: dict[int, object] = {}

    def request_shutdown(_signum, _frame) -> None:
        shutdown_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, request_shutdown)
    return previous_handlers


def restore_signal_handlers(previous_handlers: dict[int, object]) -> None:
    """Restore handlers installed by :func:`install_shutdown_signal_handlers`."""
    if threading.current_thread() is not threading.main_thread():
        return
    for signum, handler in previous_handlers.items():
        signal.signal(signum, handler)


def wait_for_shutdown(
    shutdown_event: threading.Event,
    grpc_server=None,
) -> None:
    """Wait for a process signal or an unexpected gRPC server termination."""
    while not shutdown_event.wait(timeout=1.0):
        if grpc_server is not None and not grpc_server.wait_for_termination(timeout=0):
            return


def main():
    """Compose and run the configured gRPC and WebSocket listeners."""
    logger = None
    server = None
    grpc_server = None
    websocket_server = None
    websocket_runtime = None
    data_source_lifecycles = []
    streaming_executor = None
    shutdown_event = threading.Event()
    previous_signal_handlers = install_shutdown_signal_handlers(shutdown_event)
    try:
        config_path = os.environ.get("GATEWAY_CONFIG", "config/config.yaml")
        config = load_config(config_path)
        setup_logging(config)
        logger = logging.getLogger(__name__)
        logger.info("Starting Webex Contact Center BYOVA Gateway")

        transport_profiles = enabled_transport_profiles(config)
        validate_transport_profiles(config, transport_profiles)

        router = VirtualAgentRouter()
        router_config = create_router_config(config)
        router.load_connectors(router_config)
        logger.info("Connectors loaded successfully")

        transport_names = {profile.name for profile in transport_profiles}
        grpc_enabled = "grpc" in transport_names
        websocket_enabled = "websocket" in transport_names
        dual_transport_requested = grpc_enabled and websocket_enabled
        transport_config = config.get("transports", {})
        websocket_config = transport_config.get("websocket", {})
        allow_partial = dual_transport_requested and bool(
            transport_config.get("allow_partial_transport_startup", False)
        )
        gateway_config = config.get("gateway", {})
        vad_config = config.get("voice_activity_detection", {})
        registry = ConversationRegistry()
        shared_jwks_cache = JWKSCache()

        if grpc_enabled:
            server = WxCCGatewayServer(
                router,
                vad_config,
                max_terminal_playback_seconds=float(
                    gateway_config.get("max_terminal_playback_seconds", 30.0)
                ),
                request_queue_maxsize=int(
                    gateway_config.get("request_queue_maxsize", 100)
                ),
                response_queue_maxsize=int(
                    gateway_config.get("response_queue_maxsize", 100)
                ),
                conversation_registry=registry,
            )
            logger.info("WxCCGatewayServer created")

        health_service = HealthCheckService(router)
        host = gateway_config.get("host", "0.0.0.0")
        port = int(os.environ.get("PORT", gateway_config.get("port", 50051)))
        server_address = f"{host}:{port}"

        jwt_interceptor = (
            create_jwt_interceptor(config, logger, shared_jwks_cache)
            if grpc_enabled
            else None
        )
        interceptors = []
        if jwt_interceptor:
            interceptors.append(jwt_interceptor)

        websocket_jwt_validator = None
        if websocket_enabled:
            websocket_jwt_validator = create_websocket_jwt_validator(
                config, logger, shared_jwks_cache
            )
            websocket_server = WebSocketGatewayServer(
                router,
                registry=registry,
                jwt_validator=websocket_jwt_validator,
                allow_unauthenticated_local_dev=bool(
                    websocket_config.get("allow_unauthenticated_local_dev", False)
                ),
                vad_config=vad_config,
                first_message_timeout_seconds=float(
                    websocket_config.get("first_message_timeout_seconds", 10.0)
                ),
                discovery_idle_timeout_seconds=float(
                    websocket_config.get("discovery_idle_timeout_seconds", 5.0)
                ),
                terminal_flush_timeout_seconds=float(
                    websocket_config.get("terminal_flush_timeout_seconds", 2.0)
                ),
                terminal_peer_close_timeout_seconds=float(
                    websocket_config.get(
                        "terminal_peer_close_timeout_seconds", 30.0
                    )
                ),
                queue_maxsize=int(websocket_config.get("queue_maxsize", 100)),
                queue_put_timeout_seconds=float(
                    websocket_config.get("queue_put_timeout_seconds", 1.0)
                ),
                max_message_bytes=int(
                    websocket_config.get("max_message_bytes", 128 * 1024)
                ),
                connector_max_workers=int(
                    websocket_config.get("connector_max_workers", 20)
                ),
                connector_max_pending=int(
                    websocket_config.get("connector_max_pending", 20)
                ),
                output_chunk_bytes=int(
                    websocket_config.get("output_chunk_bytes", 3_200)
                ),
            )
            websocket_runtime = WebSocketGatewayRuntime(
                websocket_server,
                host=websocket_config.get("host", "0.0.0.0"),
                port=int(
                    os.environ.get("WEBSOCKET_PORT", websocket_config.get("port", 8765))
                ),
            )

        lifecycle_specs = []
        for profile in transport_profiles:
            lifecycle_arguments = {
                "section_name": profile.datasource_section,
                "jwt_section_name": profile.jwt_section,
                "default_schema_id": profile.default_schema_id,
            }
            if profile.name == "grpc":
                # Preserve the existing call shape for tests and integrations that
                # patch the legacy gRPC factory invocation.
                lifecycle_arguments = {}
            lifecycle_specs.append(
                (
                    profile.name,
                    create_data_source_lifecycle(
                        config,
                        logger,
                        **lifecycle_arguments,
                    ),
                    config.get(profile.datasource_section, {}),
                )
            )

        for transport_name, lifecycle, lifecycle_config in lifecycle_specs:
            if lifecycle is None:
                continue
            try:
                lifecycle.start()
                data_source_lifecycles.append(lifecycle)
            except Exception:
                lifecycle.stop()
                if not allow_partial and (
                    dual_transport_requested
                    or lifecycle_config.get("fail_startup_on_error", True)
                ):
                    raise
                if not allow_partial:
                    logger.exception(
                        "%s datasource failed; continuing because its legacy "
                        "fail_startup_on_error setting is false",
                        transport_name,
                    )
                    continue
                logger.exception(
                    "%s datasource failed; listener disabled by explicit "
                    "partial-startup development override",
                    transport_name,
                )
                if transport_name == "grpc":
                    grpc_enabled = False
                    server = None
                else:
                    websocket_enabled = False
                    websocket_server = None
                    websocket_runtime = None

        if grpc_enabled:
            grpc_options = [
                ("grpc.max_send_message_length", 50 * 1024 * 1024),
                ("grpc.max_receive_message_length", 50 * 1024 * 1024),
                ("grpc.max_concurrent_streams", 100),
            ]
            grpc_kwargs = {"options": grpc_options}
            if interceptors:
                grpc_kwargs["interceptors"] = interceptors
            grpc_server = grpc.server(
                futures.ThreadPoolExecutor(max_workers=10), **grpc_kwargs
            )
            streaming_executor = create_streaming_executor(
                server, int(gateway_config.get("streaming_max_workers", 100))
            )
            add_VoiceVirtualAgentServicer_to_server(server, grpc_server)
            health_pb2_grpc.add_HealthServicer_to_server(health_service, grpc_server)
            if grpc_server.add_insecure_port(server_address) == 0:
                raise RuntimeError(f"gRPC listener could not bind to {server_address}")

        # All enabled datasource profiles are ready before either listener
        # accepts traffic. Roll back the first listener if the second fails.
        if websocket_enabled:
            websocket_runtime.start()
        if grpc_enabled:
            grpc_server.start()

        monitoring_config = config.get("monitoring", {})
        if monitoring_config.get("enabled", True):
            monitoring_host = monitoring_config.get("host", "0.0.0.0")
            monitoring_port = monitoring_config.get("port", 8080)
            monitoring_gateway = CombinedMonitoringGateway(server, websocket_server)
            flask_thread = threading.Thread(
                target=run_web_app,
                args=(router, monitoring_gateway),
                kwargs={
                    "host": monitoring_host,
                    "port": monitoring_port,
                    "debug": monitoring_config.get("debug", False),
                },
                daemon=True,
            )
            flask_thread.start()
            logger.info(
                f"Flask monitoring app started on {monitoring_host}:{monitoring_port}"
            )

        print("\n" + "=" * 60)
        print("🚀 Webex Contact Center BYOVA Gateway")
        print("=" * 60)
        if grpc_enabled:
            print(f"📡 gRPC Server: {server_address}")
        if websocket_enabled:
            websocket_host = websocket_config.get("host", "0.0.0.0")
            websocket_port = int(
                os.environ.get("WEBSOCKET_PORT", websocket_config.get("port", 8765))
            )
            print(f"🔁 WebSocket Server: ws://{websocket_host}:{websocket_port}")
        print(f"📁 Configuration: {config_path}")
        print(f"🔧 Gateway Version: {gateway_config.get('version', '1.1.0')}")
        print()

        print("🔌 Loaded Connectors:")
        router_info = router.get_connector_info()
        for connector_name in router_info["loaded_connectors"]:
            print(f"   • {connector_name}")

        print()
        print("🎯 Available Agents:")
        available_agents = router.get_all_available_agents()
        for agent in available_agents:
            print(f"   • {agent}")

        print()
        print("📊 Monitoring Interface:")
        if monitoring_config.get("enabled", True):
            print(f"   • Web UI: http://{monitoring_host}:{monitoring_port}")
            print(f"   • Status: http://{monitoring_host}:{monitoring_port}/status")
            print(f"   • Health: http://{monitoring_host}:{monitoring_port}/health")
        else:
            print("   • Disabled")

        print()
        print("✅ Gateway is running! Press Ctrl+C to stop.")
        print("=" * 60)

        try:
            wait_for_shutdown(shutdown_event, grpc_server)
        except KeyboardInterrupt:
            shutdown_event.set()
        finally:
            logger.info("Received shutdown signal")
            logger.info("Shutting down gateway...")
            if server:
                server.shutdown()
            if grpc_server:
                grpc_server.stop(grace=5)
            if websocket_runtime:
                websocket_runtime.stop()
            for lifecycle in reversed(data_source_lifecycles):
                lifecycle.stop()
            if streaming_executor:
                streaming_executor.shutdown(wait=False, cancel_futures=True)
            logger.info("Gateway shutdown complete")

    except Exception as e:
        if grpc_server:
            grpc_server.stop(grace=0)
        if server:
            server.shutdown()
        if websocket_runtime:
            websocket_runtime.stop()
        for lifecycle in reversed(data_source_lifecycles):
            lifecycle.stop()
        if streaming_executor:
            streaming_executor.shutdown(wait=False, cancel_futures=True)
        if logger:
            logger.error(f"Failed to start gateway: {e}")
        else:
            print(f"Failed to start gateway: {e}")
        sys.exit(1)
    finally:
        restore_signal_handlers(previous_signal_handlers)


if __name__ == "__main__":
    main()
