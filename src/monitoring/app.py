"""
Webex Contact Center BYOVA Gateway - Monitoring Web Application

This Flask application provides a web-based monitoring interface for the BYOVA Gateway,
allowing administrators to check the status of virtual agents and active sessions.
"""

import logging
import threading
import time
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


@app.route("/api/test/create-conversation")
def api_test_create_conversation():
    """
    Test endpoint to create a mock active conversation.

    Returns:
        JSON response with test conversation information
    """
    try:
        if gateway_server_instance:
            # Create a test conversation
            test_conversation_id = "test-conversation-123"
            test_agent_id = "Local Playback"

            gateway_server_instance.active_conversations[test_conversation_id] = {
                "agent_id": test_agent_id,
                "conversation_id": test_conversation_id,
                "customer_org_id": "test-customer-org",
                "welcome_sent": True,
                "rpc_sessions": ["test-rpc-session-123"],
            }

            # Add a connection event
            gateway_server_instance.add_connection_event(
                "start",
                test_conversation_id,
                test_agent_id,
                customer_org_id="test-customer-org",
                rpc_session_id="test-rpc-session-123",
            )

            logger.info(f"Created test conversation: {test_conversation_id}")
            return jsonify(
                {
                    "status": "success",
                    "message": f"Created test conversation {test_conversation_id}",
                    "conversation_id": test_conversation_id,
                }
            )
        else:
            return jsonify({"error": "Gateway server not available"}), 500

    except Exception as e:
        logger.error(f"Error creating test conversation: {e}")
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

    # Get health status if available
    health_data = {"overall_healthy": True, "grpc_status": "SERVING"}
    if gateway_server_instance and hasattr(gateway_server_instance, "health_service"):
        try:
            # Get health from the gRPC health service
            health_summary = gateway_server_instance.health_service.get_overall_health()
            
            # Get individual service statuses
            from grpc_health.v1 import health_pb2
            services = {}
            
            # Check overall health (empty service name)
            overall_response = gateway_server_instance.health_service.Check(
                health_pb2.HealthCheckRequest(service=""), None
            )
            services[""] = health_pb2.HealthCheckResponse.ServingStatus.Name(overall_response.status)
            
            # Check gateway service
            gateway_response = gateway_server_instance.health_service.Check(
                health_pb2.HealthCheckRequest(service="byova.gateway"), None
            )
            services["byova.gateway"] = health_pb2.HealthCheckResponse.ServingStatus.Name(gateway_response.status)
            
            health_data = {
                "overall_healthy": health_summary.get("overall_healthy", True),
                "grpc_status": "SERVING" if health_summary.get("overall_healthy", True) else "NOT_SERVING",
                "services": services,
                "serving_services": health_summary.get("serving_services", 0),
                "total_services": health_summary.get("total_services", 0),
                "last_check_time": health_summary.get("last_check_time", time.time())
            }
        except Exception as e:
            health_data = {"overall_healthy": False, "grpc_status": "UNKNOWN", "error": str(e), "services": {}, "serving_services": 0, "total_services": 0}
    
    # Get connector info for total count
    total_connectors = 0
    if router_instance:
        try:
            connector_info = router_instance.get_connector_info()
            total_connectors = connector_info.get("total_connectors", 0)
        except Exception as e:
            logger.error(f"Error getting connector count: {e}")
    
    return {
        "status": "running",
        "available_agents": available_agents,
        "active_sessions": active_sessions,
        "total_agents": len(available_agents),
        "total_sessions": len(active_sessions),
        "total_connectors": total_connectors,
        "uptime": get_uptime(),
        "last_updated": datetime.now().isoformat(),
        "health": health_data
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
            config["connectors"] = []
            for connector_name in router_info["loaded_connectors"]:
                # Get agents for this specific connector
                connector_agents = [
                    agent_id for agent_id, mapped_connector in router_info["agent_mappings"].items()
                    if mapped_connector == connector_name
                ]
                config["connectors"].append({
                    "name": connector_name,
                    "agents": connector_agents,
                })
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

    active_conversations = []
    connection_events = []

    if gateway_server_instance:
        try:
            # Get active conversations from gateway server using the new method
            if hasattr(gateway_server_instance, "get_active_conversations"):
                active_conversations_data = gateway_server_instance.get_active_conversations()
                for conversation_id, conversation_data in active_conversations_data.items():
                    active_conversations.append(
                        {
                            "conversation_id": conversation_id,
                            "agent_id": conversation_data.get("agent_id", "Unknown"),
                            "customer_org_id": conversation_data.get(
                                "customer_org_id", "Unknown"
                            ),
                            "rpc_sessions": conversation_data.get("rpc_sessions", []),
                            "welcome_sent": conversation_data.get("welcome_sent", False),
                            "status": "Active",
                        }
                    )
            # Fallback to direct access if method doesn't exist
            elif hasattr(gateway_server_instance, "active_conversations"):
                for (
                    conversation_id,
                    conversation_data,
                ) in gateway_server_instance.active_conversations.items():
                    active_conversations.append(
                        {
                            "conversation_id": conversation_id,
                            "agent_id": conversation_data.get("agent_id", "Unknown"),
                            "customer_org_id": conversation_data.get(
                                "customer_org_id", "Unknown"
                            ),
                            "rpc_sessions": conversation_data.get("rpc_sessions", []),
                            "welcome_sent": conversation_data.get("welcome_sent", False),
                            "status": "Active",
                        }
                    )

            # Get connection events from gateway server
            if hasattr(gateway_server_instance, "get_connection_events"):
                connection_events = gateway_server_instance.get_connection_events()

        except Exception as e:
            logger.error(f"Error getting connection data: {e}")

    return {
        "active_conversations": active_conversations,
        "history": recent_history,
        "connection_events": connection_events,
        "total_active": len(active_conversations),
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
