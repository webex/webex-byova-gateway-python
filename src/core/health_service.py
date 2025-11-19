"""
Health Check Service for BYOVA Gateway

Implements gRPC health checking protocol to monitor service health status.
"""

import time
import threading
from typing import Dict, Optional
from grpc_health.v1 import health_pb2, health_pb2_grpc
from grpc_health.v1.health import HealthServicer


class HealthCheckService(HealthServicer):
    """
    Health check service that monitors the status of all gateway services.
    
    Implements the standard gRPC health checking protocol.
    """
    
    def __init__(self, logger=None):
        super().__init__()
        self.logger = logger
        self._service_status: Dict[str, health_pb2.HealthCheckResponse.ServingStatus] = {}
        self._last_check_time = time.time()
        self._lock = threading.Lock()
        
        # Initialize default services
        self._initialize_services()
    
    def _initialize_services(self):
        """Initialize default service statuses."""
        with self._lock:
            # Main gateway service
            self._service_status[""] = health_pb2.HealthCheckResponse.SERVING
            self._service_status["byova.gateway"] = health_pb2.HealthCheckResponse.SERVING
    
    def Check(self, request, context):
        """
        Perform a health check for the requested service.
        """
        service_name = request.service
        
        with self._lock:
            status = self._service_status.get(
                service_name, 
                health_pb2.HealthCheckResponse.SERVICE_UNKNOWN
            )
            
            self._last_check_time = time.time()
        
        return health_pb2.HealthCheckResponse(status=status)
    
    def get_overall_health(self) -> Dict[str, any]:
        """
        Get overall health summary.
        """
        with self._lock:
            total_services = len(self._service_status)
            serving_count = sum(
                1 for status in self._service_status.values() 
                if status == health_pb2.HealthCheckResponse.SERVING
            )
            
            overall_healthy = serving_count == total_services
            
            return {
                "overall_healthy": overall_healthy,
                "total_services": total_services,
                "serving_services": serving_count,
                "last_check_time": self._last_check_time
            }