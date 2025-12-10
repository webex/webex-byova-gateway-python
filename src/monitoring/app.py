"""
Webex Contact Center BYOVA Gateway - Monitoring Web Application

This Flask application provides a web-based monitoring interface for the BYOVA Gateway,
allowing administrators to check the status of virtual agents and active sessions.
"""

import logging
import os
import threading
from datetime import datetime, timedelta
from functools import wraps
from typing import TYPE_CHECKING, Any, Dict, Optional

import jwt
import requests
import yaml
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

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

# Load authentication configuration
def load_auth_config() -> Dict[str, Any]:
    """
    Load authentication configuration from config.yaml.

    Returns:
        Dictionary containing authentication configuration
    """
    try:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config",
            "config.yaml"
        )
        with open(config_path) as f:
            config = yaml.safe_load(f)
            return config.get("authentication", {})
    except Exception as e:
        logger.error(f"Error loading authentication config: {e}")
        return {}

# Load auth config
auth_config = load_auth_config()

# Configure Flask secret key from environment variable
if auth_config.get("enabled", False):
    secret_key_env = auth_config.get("session", {}).get("secret_key_env", "FLASK_SECRET_KEY")
    app.secret_key = os.getenv(secret_key_env, os.urandom(24))

    # Configure session timeout
    timeout_hours = auth_config.get("session", {}).get("timeout_hours", 24)
    app.permanent_session_lifetime = timedelta(hours=timeout_hours)
else:
    app.secret_key = os.urandom(24)

# In-memory storage for connection history
connection_history = []
history_lock = threading.Lock()


# Authentication Helper Functions
def get_authorized_org_ids() -> list:
    """
    Get the list of authorized organization IDs from environment variable.

    Returns:
        List of authorized organization IDs
    """
    if not auth_config.get("enabled", False):
        return []

    orgs_env_var = auth_config.get("authorized_orgs_env", "AUTHORIZED_WEBEX_ORG_IDS")
    orgs_str = os.getenv(orgs_env_var, "")

    if not orgs_str:
        logger.warning(f"No authorized org IDs found in environment variable: {orgs_env_var}")
        return []

    # Split by comma and strip whitespace
    orgs = [org.strip() for org in orgs_str.split(",") if org.strip()]
    logger.info(f"Loaded {len(orgs)} authorized organization IDs")
    return orgs


def parse_jwt_token(token: str) -> Dict[str, Any]:
    """
    Parse JWT token without signature verification.

    Args:
        token: JWT token string

    Returns:
        Dictionary containing token claims
    """
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception as e:
        logger.error(f"Error parsing JWT token: {e}")
        return {}


def validate_org_id(org_id: str) -> bool:
    """
    Validate if the organization ID is authorized.

    Args:
        org_id: Organization ID to validate

    Returns:
        True if authorized, False otherwise
    """
    authorized_orgs = get_authorized_org_ids()

    if not authorized_orgs:
        logger.warning("No authorized organizations configured - denying access")
        return False

    is_valid = org_id in authorized_orgs

    if is_valid:
        logger.info(f"Organization ID validated: {org_id}")
    else:
        logger.warning(f"Unauthorized organization ID: {org_id}")

    return is_valid


def get_webex_user_info(access_token: str) -> Dict[str, Any]:
    """
    Get user information from Webex API.

    Args:
        access_token: Webex access token

    Returns:
        Dictionary containing user information
    """
    try:
        url = "https://webexapis.com/v1/userinfo"
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        response = requests.get(url=url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching user info from Webex: {e}")
        return {}


def exchange_code_for_tokens(code: str) -> Dict[str, Any]:
    """
    Exchange authorization code for access and ID tokens.

    Args:
        code: Authorization code from OAuth callback

    Returns:
        Dictionary containing tokens and user information
    """
    try:
        # Read OAuth credentials directly from environment variables
        client_id = os.getenv("WEBEX_CLIENT_ID")
        client_secret = os.getenv("WEBEX_CLIENT_SECRET")
        redirect_uri = os.getenv("WEBEX_REDIRECT_URI")

        # Check which credentials are missing
        missing = []
        if not client_id:
            missing.append("client_id")
        if not client_secret:
            missing.append("client_secret")
        if not redirect_uri:
            missing.append("redirect_uri")

        if missing:
            logger.error(f"Missing Webex OAuth configuration: {', '.join(missing)}")
            return {}

        logger.info(f"Token exchange: client_id={'set' if client_id else 'MISSING'}, "
                   f"client_secret={'set' if client_secret else 'MISSING'}, "
                   f"redirect_uri={redirect_uri}")

        url = "https://webexapis.com/v1/access_token"
        headers = {
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded"
        }
        payload = (
            f"grant_type=authorization_code&client_id={client_id}&"
            f"client_secret={client_secret}&code={code}&redirect_uri={redirect_uri}"
        )

        response = requests.post(url=url, data=payload, headers=headers, timeout=10)

        if response.status_code != 200:
            logger.error(f"Token exchange failed with status {response.status_code}: {response.text}")

        response.raise_for_status()
        return response.json()

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error during token exchange: {e}")
        if hasattr(e.response, 'text'):
            logger.error(f"Response body: {e.response.text}")
        return {}
    except Exception as e:
        logger.error(f"Error exchanging code for tokens: {e}")
        return {}


def require_auth(f):
    """
    Decorator to require authentication for routes.
    Redirects to login page if not authenticated.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Skip authentication if disabled
        if not auth_config.get("enabled", False):
            return f(*args, **kwargs)

        # Check if user is authenticated
        if "authenticated" not in session or not session.get("authenticated"):
            logger.info("Unauthenticated access attempt, redirecting to login")
            return redirect(url_for("login"))

        # Check if session has expired
        if "auth_time" in session:
            auth_time = datetime.fromisoformat(session["auth_time"])
            timeout_hours = auth_config.get("session", {}).get("timeout_hours", 24)

            if datetime.now() - auth_time > timedelta(hours=timeout_hours):
                logger.info("Session expired, redirecting to login")
                session.clear()
                return redirect(url_for("login"))

        return f(*args, **kwargs)

    return decorated_function


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
@require_auth
def index():
    """
    Main dashboard page with graphical interface.
    Requires authentication via Webex OAuth.

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

        # Get user info from session
        user_info = {
            "name": session.get("user_name", "User"),
            "email": session.get("user_email", ""),
            "org_id": session.get("org_id", "")
        }

        return render_template(
            "dashboard.html",
            status=status_data,
            config=config_data,
            connections=connection_data,
            user=user_info,
        )
    except Exception as e:
        logger.error(f"Error rendering dashboard: {e}")
        return render_template("error.html", error=str(e))


@app.route("/login")
def login():
    """
    Login page with Webex OAuth.

    Returns:
        Rendered HTML template with login interface
    """
    # If already authenticated, redirect to dashboard
    if session.get("authenticated"):
        return redirect(url_for("index"))

    # Check if there's an error message in the query params
    error_message = request.args.get("error", None)

    # Build OAuth URL
    oauth_config = auth_config.get("webex_oauth", {})
    client_id = os.getenv("WEBEX_CLIENT_ID")
    redirect_uri = os.getenv("WEBEX_REDIRECT_URI")
    scopes = oauth_config.get("scopes", "openid email profile")
    state = oauth_config.get("state", "byova_gateway_auth")

    # Log configuration for debugging (sanitized)
    logger.info(f"OAuth configuration: client_id={'set' if client_id else 'MISSING'}, "
                f"redirect_uri={redirect_uri}, scopes={scopes}")

    if not client_id:
        logger.error("WEBEX_CLIENT_ID environment variable is not set!")
        return render_template("login.html", oauth_url="#",
                             error="Configuration error: Client ID not configured")

    if not redirect_uri:
        logger.error("WEBEX_REDIRECT_URI environment variable is not set!")
        return render_template("login.html", oauth_url="#",
                             error="Configuration error: Redirect URI not configured")

    oauth_url = (
        f"https://webexapis.com/v1/authorize?"
        f"response_type=code&"
        f"client_id={client_id}&"
        f"redirect_uri={redirect_uri}&"
        f"scope={scopes.replace(' ', '%20')}&"
        f"state={state}"
    )

    return render_template("login.html", oauth_url=oauth_url, error=error_message)


@app.route("/oauth")
def oauth_callback():
    """
    OAuth callback handler.
    Validates state, exchanges code for tokens, validates org ID, and creates session.

    Returns:
        Redirect to dashboard on success, login page on failure
    """
    try:
        # Verify state parameter
        oauth_config = auth_config.get("webex_oauth", {})
        expected_state = oauth_config.get("state", "byova_gateway_auth")
        state = request.args.get("state")

        if state != expected_state:
            logger.warning(f"Invalid state parameter: {state}")
            return redirect(url_for("login", error="Invalid state parameter"))

        # Get authorization code
        code = request.args.get("code")

        if not code:
            logger.error("No authorization code received")
            return redirect(url_for("login", error="No authorization code received"))

        # Exchange code for tokens
        logger.info("Exchanging authorization code for tokens")
        tokens = exchange_code_for_tokens(code)

        if not tokens or "id_token" not in tokens:
            logger.error("Failed to exchange code for tokens")
            return redirect(url_for("login", error="Failed to authenticate with Webex"))

        # Parse JWT to get claims
        id_token = tokens.get("id_token")
        access_token = tokens.get("access_token")
        claims = parse_jwt_token(id_token)

        # Extract org ID from access token
        # Webex access tokens are formatted as: {access_token}_{ci_cluster}_{org_id}
        try:
            token_parts = access_token.split("_")
            if len(token_parts) >= 3:
                org_id = token_parts[2]
                logger.info(f"Extracted organization ID from access token: {org_id}")
            else:
                logger.error(f"Access token format unexpected: {len(token_parts)} parts")
                return redirect(url_for("login", error="Invalid access token format"))
        except Exception as e:
            logger.error(f"Error extracting org ID from access token: {e}")
            return redirect(url_for("login", error="Failed to extract organization ID"))

        if not org_id:
            logger.error("No organization ID found in access token")
            return redirect(url_for("login", error="No organization ID found"))

        # Validate org ID
        if not validate_org_id(org_id):
            logger.warning(f"Unauthorized organization attempted access: {org_id}")
            return redirect(
                url_for("login", error="Your organization is not authorized to access this dashboard")
            )

        # Get user info from Webex
        user_info = get_webex_user_info(access_token)

        # Create session
        session.permanent = True
        session["authenticated"] = True
        session["auth_time"] = datetime.now().isoformat()
        session["access_token"] = access_token
        session["id_token"] = id_token
        session["org_id"] = org_id
        session["user_name"] = user_info.get("name", claims.get("name", "User"))
        session["user_email"] = user_info.get("email", claims.get("email", ""))

        logger.info(f"User authenticated successfully: {session['user_email']} (Org: {org_id})")

        return redirect(url_for("index"))

    except Exception as e:
        logger.error(f"Error in OAuth callback: {e}")
        return redirect(url_for("login", error="Authentication failed"))


@app.route("/logout")
def logout():
    """
    Logout route that clears the session.

    Returns:
        Redirect to login page
    """
    user_email = session.get("user_email", "Unknown")
    session.clear()
    logger.info(f"User logged out: {user_email}")
    return redirect(url_for("login"))


@app.route("/auth/status")
def auth_status():
    """
    Authentication status endpoint for AJAX calls.

    Returns:
        JSON response with authentication status
    """
    return jsonify({
        "authenticated": session.get("authenticated", False),
        "user_name": session.get("user_name", None),
        "user_email": session.get("user_email", None),
        "org_id": session.get("org_id", None),
    })


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
            # Get individual service statuses using the correct method
            from grpc_health.v1 import health_pb2
            service_statuses = gateway_server_instance.health_service.get_all_service_statuses()

            # Convert status codes to names for display
            services = {}
            serving_count = 0
            total_count = len(service_statuses)

            for service_name, status_code in service_statuses.items():
                status_name = health_pb2.HealthCheckResponse.ServingStatus.Name(status_code)
                services[service_name] = status_name
                if status_code == health_pb2.HealthCheckResponse.SERVING:
                    serving_count += 1

            # Determine overall health
            overall_healthy = serving_count > 0 and serving_count == total_count
            grpc_status = "SERVING" if overall_healthy else ("NOT_SERVING" if serving_count == 0 else "DEGRADED")

            health_data = {
                "overall_healthy": overall_healthy,
                "grpc_status": grpc_status,
                "services": services,
                "serving_services": serving_count,
                "total_services": total_count
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
