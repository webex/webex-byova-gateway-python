#!/usr/bin/env python3
"""
gRPC Health Check Test Script

Tests the health status of all registered gRPC services.
Run this script while the gateway server is running.
"""

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

def get_status_name(status_code):
    """Convert status code to readable name."""
    status_names = {
        0: "SERVICE_UNKNOWN",
        1: "SERVING", 
        2: "NOT_SERVING",
        3: "SERVICE_UNKNOWN"
    }
    return status_names.get(status_code, f"UNKNOWN({status_code})")

def test_health_service():
    """Test all registered gRPC services."""
    channel = grpc.insecure_channel('localhost:50051')
    stub = health_pb2_grpc.HealthStub(channel)
    
    # Services to check
    services = [
        ("Overall", ""),
        ("byova.gateway", "byova.gateway"),
        ("byova.VoiceVirtualAgentService", "byova.VoiceVirtualAgentService")
    ]
    
    print("Testing gRPC Health Service:")
    print("-" * 40)
    
    for service_name, service_id in services:
        try:
            request = health_pb2.HealthCheckRequest(service=service_id)
            response = stub.Check(request)
            status_name = get_status_name(response.status)
            print(f"{service_name}: {status_name} ({response.status})")
        except grpc.RpcError as e:
            print(f"{service_name}: ERROR - {e.details()}")
    
    channel.close()

if __name__ == "__main__":
    try:
        test_health_service()
    except grpc.RpcError as e:
        print(f"Failed to connect to gRPC server: {e}")
        print("Make sure the gateway server is running on localhost:50051")
    except Exception as e:
        print(f"Error: {e}")