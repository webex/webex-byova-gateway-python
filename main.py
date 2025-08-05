#!/usr/bin/env python3
"""
Main entry point for the Webex Contact Center BYOVA Gateway.

This script loads configuration, initializes the virtual agent router,
creates the gRPC server, and starts listening for requests.
"""

import logging
import os
import sys
import yaml
import threading
from concurrent import futures
from pathlib import Path

import grpc

# Add src and src/core to Python path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent / "src" / "core"))

from core.virtual_agent_router import VirtualAgentRouter
from core.wxcc_gateway_server import WxCCGatewayServer
from core import voicevirtualagent_pb2_grpc
from monitoring.app import run_web_app


def setup_logging(config: dict) -> None:
    """
    Set up logging configuration.
    
    Args:
        config: Configuration dictionary containing logging settings
    """
    logging_config = config.get('logging', {})
    
    # Configure logging level
    log_level = getattr(logging, logging_config.get('level', 'INFO').upper())
    
    # Configure logging format
    log_format = logging_config.get('format', 
                                   '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Create logs directory if it doesn't exist
    log_file = logging_config.get('file', 'logs/gateway.log')
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    
    # Configure logging handlers
    handlers = [logging.StreamHandler(sys.stdout)]
    
    # Add file handler if log file is specified
    if log_file:
        try:
            handlers.append(logging.FileHandler(log_file))
        except Exception as e:
            print(f"Warning: Could not create log file {log_file}: {e}")
    
    # Configure logging
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=handlers
    )


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
        with open(config_path, 'r') as file:
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
    # Convert the list-based connector config to the dictionary format expected by router
    connectors_config = {}
    
    for connector in config.get('connectors', []):
        connector_id = connector.get('name', 'unknown')
        connectors_config[connector_id] = {
            'class': connector.get('class'),
            'module': connector.get('module'),
            'config': connector.get('config', {})
        }
    
    return {'connectors': connectors_config}


def main():
    """
    Main entry point for the BYOVA Gateway.
    
    This function:
    1. Loads configuration from YAML file
    2. Sets up logging
    3. Creates and configures the VirtualAgentRouter
    4. Creates the WxCCGatewayServer
    5. Starts the gRPC server
    """
    logger = None
    server = None
    try:
        # Load configuration
        config_path = "config/config.yaml"
        config = load_config(config_path)
        
        # Set up logging
        setup_logging(config)
        logger = logging.getLogger(__name__)
        
        logger.info("Starting Webex Contact Center BYOVA Gateway")
        
        # Create VirtualAgentRouter
        router = VirtualAgentRouter()
        logger.info("VirtualAgentRouter created")
        
        # Load connectors
        router_config = create_router_config(config)
        router.load_connectors(router_config)
        logger.info("Connectors loaded successfully")
        
        # Get session timeout configuration
        session_config = config.get('sessions', {})
        session_timeout = session_config.get('timeout', 300)  # 5 minutes default
        
        # Create WxCCGatewayServer with session timeout
        server = WxCCGatewayServer(router, session_timeout=session_timeout)
        logger.info(f"WxCCGatewayServer created with session timeout: {session_timeout}s")
        
        # Get server configuration
        gateway_config = config.get('gateway', {})
        host = gateway_config.get('host', '0.0.0.0')
        port = gateway_config.get('port', 50051)
        
        # Create gRPC server
        grpc_server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=10),
            options=[
                ('grpc.max_send_message_length', 50 * 1024 * 1024),  # 50MB
                ('grpc.max_receive_message_length', 50 * 1024 * 1024),  # 50MB
                ('grpc.max_concurrent_streams', 100),
            ]
        )
        
        # Add servicer to the server
        voicevirtualagent_pb2_grpc.add_VoiceVirtualAgentServicer_to_server(
            server, grpc_server
        )
        
        # Bind server to address
        server_address = f"{host}:{port}"
        grpc_server.add_insecure_port(server_address)
        
        # Start the server
        grpc_server.start()
        
        # Start Flask monitoring app in a separate thread
        monitoring_config = config.get('monitoring', {})
        if monitoring_config.get('enabled', True):  # Enable by default
            monitoring_host = monitoring_config.get('host', '0.0.0.0')
            monitoring_port = monitoring_config.get('port', 8080)
            
            # Create and start Flask app in a separate thread
            flask_thread = threading.Thread(
                target=run_web_app,
                args=(router, server),
                kwargs={
                    'host': monitoring_host,
                    'port': monitoring_port,
                    'debug': monitoring_config.get('debug', False)
                },
                daemon=True  # Make it a daemon thread so it stops when main thread stops
            )
            flask_thread.start()
            logger.info(f"Flask monitoring app started on {monitoring_host}:{monitoring_port}")
        
        # Print startup information
        print("\n" + "="*60)
        print("🚀 Webex Contact Center BYOVA Gateway")
        print("="*60)
        print(f"📡 gRPC Server: {server_address}")
        print(f"🌐 Access URL: grpc://{host}:{port}")
        print(f"📁 Configuration: {config_path}")
        print(f"📝 Log Level: {gateway_config.get('log_level', 'INFO')}")
        print(f"🔧 Gateway Version: {gateway_config.get('version', '1.0.0')}")
        print(f"⏱️  Session Timeout: {session_timeout}s")
        print()
        
        # Print connector information
        print("🔌 Loaded Connectors:")
        router_info = router.get_connector_info()
        for connector_name in router_info['loaded_connectors']:
            print(f"   • {connector_name}")
        
        print()
        print("🎯 Available Agents:")
        available_agents = router.get_all_available_agents()
        for agent in available_agents:
            print(f"   • {agent}")
        
        print()
        print("📊 Monitoring Interface:")
        if monitoring_config.get('enabled', True):
            print(f"   • Web UI: http://{monitoring_host}:{monitoring_port}")
            print(f"   • Status: http://{monitoring_host}:{monitoring_port}/status")
            print(f"   • Health: http://{monitoring_host}:{monitoring_port}/health")
        else:
            print("   • Disabled")
        
        print()
        print("✅ Gateway is running! Press Ctrl+C to stop.")
        print("="*60)
        
        # Keep the server running
        try:
            grpc_server.wait_for_termination()
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        finally:
            # Graceful shutdown
            logger.info("Shutting down gateway...")
            if server:
                server.shutdown()
            grpc_server.stop(grace=5)
            logger.info("Gateway shutdown complete")
            
    except Exception as e:
        if logger:
            logger.error(f"Failed to start gateway: {e}")
        else:
            print(f"Failed to start gateway: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 