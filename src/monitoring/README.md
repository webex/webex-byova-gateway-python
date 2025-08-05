# Monitoring Interface

This directory contains the web-based monitoring interface for the Webex Contact Center BYOVA Gateway.

## Features

### Real-time Dashboard
- Live status of virtual agents
- Request/response metrics
- Error tracking and alerts
- Performance monitoring

### Management Interface
- Agent configuration
- Connector status
- System health monitoring
- Log viewing and filtering

## Technology Stack

- Flask web framework
- Real-time updates via WebSocket
- Prometheus metrics integration
- Structured logging with structlog

## Access

The monitoring interface is typically available at:
- Development: http://localhost:5000
- Production: Configured via environment variables 