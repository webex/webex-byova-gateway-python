"""
gRPC Health Service implementation with real health monitoring.

This module provides a health checking service that monitors the actual
operational status of the gateway components instead of returning hardcoded values.
"""

import logging
import threading
from typing import Optional

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

from .virtual_agent_router import VirtualAgentRouter

# Global router reference to avoid variable conflicts
_global_router = None

def set_global_router(router):
    global _global_router
    _global_router = router


class HealthCheckService(health_pb2_grpc.HealthServicer):
    """
    Health check service that provides real-time health monitoring.
    
    This service monitors the actual operational status of gateway components
    including connector availability and service health.
    """

    def __init__(self, router: Optional[VirtualAgentRouter] = None):
        """
        Initialize the health check service.
        
        Args:
            router: VirtualAgentRouter instance for checking connector health
        """
        super().__init__()
        set_global_router(router)
        self.logger = logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._service_status = {}
        
        # Initialize with unknown status - will be updated on first check
        self._initialize_services()
        
        self.logger.info("HealthCheckService initialized with real health monitoring")

    def _initialize_services(self):
        """Initialize service statuses with unknown state."""
        with self._lock:
            # Initialize with unknown status - will be updated by health checks
            self._service_status[""] = health_pb2.HealthCheckResponse.SERVICE_UNKNOWN
            self._service_status["byova.gateway"] = health_pb2.HealthCheckResponse.SERVICE_UNKNOWN
            self._service_status["byova.VoiceVirtualAgentService"] = health_pb2.HealthCheckResponse.SERVICE_UNKNOWN

    def _update_service_health(self):
        """Update service health status based on actual system state."""
        try:
            with self._lock:
                # Use global router to avoid variable conflicts
                if _global_router:
                    available_agents = _global_router.get_all_available_agents()
                    has_agents = len(available_agents) > 0
                    
                    if has_agents:
                        # Gateway is serving if it has available agents
                        self._service_status["byova.gateway"] = health_pb2.HealthCheckResponse.SERVING
                        self._service_status["byova.VoiceVirtualAgentService"] = health_pb2.HealthCheckResponse.SERVING
                        self._service_status[""] = health_pb2.HealthCheckResponse.SERVING
                    else:
                        # No agents available
                        self._service_status["byova.gateway"] = health_pb2.HealthCheckResponse.NOT_SERVING
                        self._service_status["byova.VoiceVirtualAgentService"] = health_pb2.HealthCheckResponse.NOT_SERVING
                        self._service_status[""] = health_pb2.HealthCheckResponse.NOT_SERVING
                else:
                    # No router available
                    self._service_status["byova.gateway"] = health_pb2.HealthCheckResponse.SERVICE_UNKNOWN
                    self._service_status["byova.VoiceVirtualAgentService"] = health_pb2.HealthCheckResponse.SERVICE_UNKNOWN
                    self._service_status[""] = health_pb2.HealthCheckResponse.SERVICE_UNKNOWN
        except Exception as e:
            self.logger.error(f"Error updating service health: {e}")
            with self._lock:
                self._service_status[""] = health_pb2.HealthCheckResponse.SERVICE_UNKNOWN
                self._service_status["byova.gateway"] = health_pb2.HealthCheckResponse.SERVICE_UNKNOWN
                self._service_status["byova.VoiceVirtualAgentService"] = health_pb2.HealthCheckResponse.SERVICE_UNKNOWN

    def set_service_status(self, service_name: str, status: int):
        """
        Set the health status for a specific service.
        
        Args:
            service_name: Name of the service
            status: Health status (from health_pb2.HealthCheckResponse)
        """
        with self._lock:
            self._service_status[service_name] = status
            self.logger.debug(f"Set health status for '{service_name}': {status}")

    def Check(self, request, context):
        """
        Check the health of a specific service.
        
        Args:
            request: HealthCheckRequest containing service name
            context: gRPC context
            
        Returns:
            HealthCheckResponse with current service status
        """
        service_name = request.service
        
        # Update health status before responding
        self._update_service_health()
        
        with self._lock:
            if service_name in self._service_status:
                status = self._service_status[service_name]
                self.logger.debug(f"Health check for '{service_name}': {status}")
                return health_pb2.HealthCheckResponse(status=status)
            else:
                self.logger.warning(f"Health check for unknown service '{service_name}': SERVICE_UNKNOWN")
                return health_pb2.HealthCheckResponse(
                    status=health_pb2.HealthCheckResponse.SERVICE_UNKNOWN
                )

    def Watch(self, request, context):
        """
        Watch for health status changes (streaming).
        
        This is a placeholder implementation - streaming health updates
        are not currently implemented.
        """
        # Not implemented - would require streaming health updates
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Health status streaming is not implemented")
        return

    def get_all_service_statuses(self):
        """
        Get all service statuses for monitoring dashboard.
        
        Returns:
            Dictionary of service names to status codes
        """
        self._update_service_health()
        with self._lock:
            return self._service_status.copy()
