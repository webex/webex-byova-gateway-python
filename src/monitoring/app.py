"""
Webex Contact Center BYOVA Gateway - Monitoring Web Application

This Flask application provides a web-based monitoring interface for the BYOVA Gateway,
allowing administrators to check the status of virtual agents and active sessions.
"""

import logging
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

from flask import Flask, jsonify, render_template

if TYPE_CHECKING:
    from core.virtual_agent_router import VirtualAgentRouter
    from core.wxcc_gateway_server import WxCCGatewayServer

# Global reference to the VirtualAgentRouter instance
router_instance: Optional["VirtualAgentRouter"] = None

# Global reference to the WxCCGatewayServer instance for session tracking
gateway_server_instance: Optional["WxCCGatewayServer"] = None

# Initialize Flask app
app = Flask(__name__)

# Configure logging - web logging is configured in main.py
logger = logging.getLogger(__name__)

# In-memory storage for connection history
connection_history = []
history_lock = threading.Lock()


def set_router(router: "VirtualAgentRouter") -> None:
    """
    Set the global router instance for the monitoring app.

    Args:
        router: The VirtualAgentRouter instance to monitor
    """
    global router_instance
    router_instance = router
    logger.info("Router instance set for monitoring app")


def set_gateway_server(gateway_server: "WxCCGatewayServer") -> None:
    """
    Set the global gateway server instance for session tracking.

    Args:
        gateway_server: The WxCCGatewayServer instance to monitor
    """
    global gateway_server_instance
    gateway_server_instance = gateway_server
    logger.info("Gateway server instance set for monitoring app")


def add_connection_history(connection_data: Dict[str, Any]) -> None:
    """
    Add a connection event to the history.

    Args:
        connection_data: Dictionary containing connection information
    """
    with history_lock:
        connection_data["timestamp"] = datetime.now().isoformat()
        connection_history.append(connection_data)
        # Keep only last 100 entries
        if len(connection_history) > 100:
            connection_history.pop(0)


@app.route("/")
def index():
    """
    Main dashboard page with graphical interface.

    Returns:
        Rendered HTML template with gateway status and monitoring interface
    """
    try:
        # Get gateway status
        status_data = get_status_data()

        # Get configuration data
        config_data = get_configuration_data()

        # Get connection data
        connection_data = get_connection_data()

        return render_template(
            "dashboard.html",
            status=status_data,
            config=config_data,
            connections=connection_data,
        )
    except Exception as e:
        logger.error(f"Error rendering dashboard: {e}")
        return render_template("error.html", error=str(e))


@app.route("/status")
def get_status():
    """
    Get the current status of the BYOVA Gateway.

    Returns:
        JSON response with gateway status, available agents, and active sessions
    """
    try:
        status_data = get_status_data()
        return jsonify(status_data)

    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify(
            {
                "status": "error",
                "message": str(e),
                "available_agents": [],
                "active_sessions": [],
            }
        ), 500


@app.route("/api/status")
def api_status():
    """
    API endpoint for status data (for AJAX calls).

    Returns:
        JSON response with current status
    """
    return get_status()


@app.route("/api/config")
def api_config():
    """
    API endpoint for configuration data.

    Returns:
        JSON response with configuration information
    """
    try:
        config_data = get_configuration_data()
        return jsonify(config_data)
    except Exception as e:
        logger.error(f"Error getting config: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/connections")
def api_connections():
    """
    API endpoint for connection history.

    Returns:
        JSON response with connection history
    """
    try:
        connection_data = get_connection_data()
        return jsonify(connection_data)
    except Exception as e:
        logger.error(f"Error getting connections: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/debug/sessions")
def api_debug_sessions():
    """
    Debug endpoint to check session state.

    Returns:
        JSON response with debug session information
    """
    try:
        debug_info = {
            "gateway_server_exists": gateway_server_instance is not None,
            "has_active_sessions_attr": hasattr(
                gateway_server_instance, "active_sessions"
            )
            if gateway_server_instance
            else False,
            "has_get_active_sessions": hasattr(
                gateway_server_instance, "get_active_sessions"
            )
            if gateway_server_instance
            else False,
            "has_get_connection_events": hasattr(
                gateway_server_instance, "get_connection_events"
            )
            if gateway_server_instance
            else False,
        }

        if gateway_server_instance:
            if hasattr(gateway_server_instance, "active_sessions"):
                debug_info["active_sessions_count"] = len(
                    gateway_server_instance.active_sessions
                )
                debug_info["active_sessions_keys"] = list(
                    gateway_server_instance.active_sessions.keys()
                )

            if hasattr(gateway_server_instance, "get_connection_events"):
                debug_info["connection_events_count"] = len(
                    gateway_server_instance.get_connection_events()
                )

        return jsonify(debug_info)
    except Exception as e:
        logger.error(f"Error in debug endpoint: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/test/create-session")
def api_test_create_session():
    """
    Test endpoint to create a mock active session.

    Returns:
        JSON response with test session information
    """
    try:
        if gateway_server_instance:
            # Create a test session
            test_session_id = "test-session-123"
            test_agent_id = "Local Playback"

            gateway_server_instance.active_sessions[test_session_id] = {
                "agent_id": test_agent_id,
                "conversation_id": test_session_id,
                "customer_org_id": "test-customer-org",
                "welcome_sent": True,
            }

            # Add a connection event
            gateway_server_instance.add_connection_event(
                "start",
                test_session_id,
                test_agent_id,
                customer_org_id="test-customer-org",
            )

            logger.info(f"Created test session: {test_session_id}")
            return jsonify(
                {
                    "status": "success",
                    "message": f"Created test session {test_session_id}",
                    "session_id": test_session_id,
                }
            )
        else:
            return jsonify({"error": "Gateway server not available"}), 500

    except Exception as e:
        logger.error(f"Error creating test session: {e}")
        return jsonify({"error": str(e)}), 500


def get_status_data() -> Dict[str, Any]:
    """
    Get current status data.

    Returns:
        Dictionary with status information
    """
    if router_instance is None:
        return {
            "status": "error",
            "message": "Router not initialized",
            "available_agents": [],
            "active_sessions": [],
            "total_agents": 0,
            "total_sessions": 0,
        }

    # Get available agents from router
    available_agents = router_instance.get_all_available_agents()

    # Get active sessions from gateway server
    active_sessions = []
    if gateway_server_instance and hasattr(gateway_server_instance, "active_sessions"):
        active_sessions = list(gateway_server_instance.active_sessions.keys())

    return {
        "status": "running",
        "available_agents": available_agents,
        "active_sessions": active_sessions,
        "total_agents": len(available_agents),
        "total_sessions": len(active_sessions),
        "uptime": get_uptime(),
        "last_updated": datetime.now().isoformat(),
    }


def get_configuration_data() -> Dict[str, Any]:
    """
    Get configuration data.

    Returns:
        Dictionary with configuration information
    """
    config = {
        "gateway": {
            "name": "BYOVA Gateway",
            "version": "1.0.0",
            "host": "0.0.0.0",
            "grpc_port": 50051,
            "web_port": 8080,
        },
        "connectors": [],
        "monitoring": {"enabled": True, "host": "0.0.0.0", "port": 8080},
    }

    if router_instance:
        try:
            router_info = router_instance.get_connector_info()
            config["connectors"] = [
                {
                    "name": connector_name,
                    "agents": list(router_info["agent_mappings"].keys()),
                }
                for connector_name in router_info["loaded_connectors"]
            ]
        except Exception as e:
            logger.error(f"Error getting router info: {e}")

    return config


def get_connection_data() -> Dict[str, Any]:
    """
    Get connection history and current connections.

    Returns:
        Dictionary with connection information
    """
    with history_lock:
        recent_history = connection_history[-20:]  # Last 20 entries

    active_sessions = []
    connection_events = []

    if gateway_server_instance:
        try:
            # Get active sessions from gateway server using the new method
            if hasattr(gateway_server_instance, "get_active_sessions"):
                active_sessions_data = gateway_server_instance.get_active_sessions()
                for session_id, session_data in active_sessions_data.items():
                    active_sessions.append(
                        {
                            "session_id": session_id,
                            "agent_id": session_data.get("agent_id", "Unknown"),
                            "customer_org_id": session_data.get(
                                "customer_org_id", "Unknown"
                            ),
                            "conversation_id": session_data.get(
                                "conversation_id", session_id
                            ),
                            "welcome_sent": session_data.get("welcome_sent", False),
                            "status": "Active",
                        }
                    )
            # Fallback to direct access if method doesn't exist
            elif hasattr(gateway_server_instance, "active_sessions"):
                for (
                    session_id,
                    session_data,
                ) in gateway_server_instance.active_sessions.items():
                    active_sessions.append(
                        {
                            "session_id": session_id,
                            "agent_id": session_data.get("agent_id", "Unknown"),
                            "customer_org_id": session_data.get(
                                "customer_org_id", "Unknown"
                            ),
                            "conversation_id": session_data.get(
                                "conversation_id", session_id
                            ),
                            "welcome_sent": session_data.get("welcome_sent", False),
                            "status": "Active",
                        }
                    )

            # Get connection events from gateway server
            if hasattr(gateway_server_instance, "get_connection_events"):
                connection_events = gateway_server_instance.get_connection_events()

        except Exception as e:
            logger.error(f"Error getting connection data: {e}")

    return {
        "active_sessions": active_sessions,
        "history": recent_history,
        "connection_events": connection_events,
        "total_active": len(active_sessions),
        "total_history": len(connection_history),
    }


def get_uptime() -> str:
    """
    Get uptime information.

    Returns:
        String representation of uptime
    """
    # This is a simplified uptime - in a real implementation,
    # you'd track the actual start time
    return "Running"


@app.route("/health")
def health_check():
    """
    Simple health check endpoint.

    Returns:
        JSON response indicating the service is healthy
    """
    return jsonify(
        {
            "status": "healthy",
            "service": "BYOVA Gateway Monitoring",
            "timestamp": datetime.now().isoformat(),
        }
    )


def run_web_app(
    router_instance_param: "VirtualAgentRouter",
    gateway_server_param: Optional["WxCCGatewayServer"] = None,
    host: str = "0.0.0.0",
    port: int = 8080,
    debug: bool = False,
) -> None:
    """
    Start the Flask web application for monitoring.

    Args:
        router_instance_param: The VirtualAgentRouter instance to monitor
        gateway_server_param: The WxCCGatewayServer instance to monitor (optional)
        host: Host address to bind to (default: 0.0.0.0)
        port: Port to bind to (default: 8080)
        debug: Enable Flask debug mode (default: False)
    """
    # Set the router instance
    set_router(router_instance_param)

    # Set the gateway server instance if provided
    if gateway_server_param:
        set_gateway_server(gateway_server_param)

    logger.info(f"Starting BYOVA Gateway monitoring web app on {host}:{port}")

    # Start the Flask development server
    app.run(
        host=host,
        port=port,
        debug=debug,
        use_reloader=False,  # Disable reloader to avoid conflicts with gRPC server
    )


if __name__ == "__main__":
    # This allows running the monitoring app independently for testing
    print("BYOVA Gateway Monitoring Web App")
    print("Note: This should typically be run from the main gateway application.")
    print("For testing, you can run this directly, but router will be None.")

    # Run with default settings
    run_web_app(None, debug=True)
