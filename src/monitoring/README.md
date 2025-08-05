# Monitoring Interface

This directory contains the web-based monitoring interface for the Webex Contact Center BYOVA Gateway, providing real-time visibility into gateway operations and virtual agent sessions.

## Features

### Real-time Dashboard

The monitoring interface provides comprehensive visibility into:

- **Gateway Status**: Live status of the gRPC server and connectors
- **Active Sessions**: Real-time tracking of active virtual agent sessions
- **Connection History**: Historical connection events with timestamps
- **Available Agents**: List of configured virtual agents and their status
- **Performance Metrics**: Request/response metrics and error tracking
- **System Health**: Overall system health and component status

### Management Interface

Administrative capabilities include:

- **Agent Configuration**: View and manage virtual agent settings
- **Connector Status**: Monitor connector health and availability
- **Session Management**: View and manage active sessions
- **Log Viewing**: Access to structured logs with filtering
- **Debug Information**: Detailed debugging information for troubleshooting

## Technology Stack

### Backend
- **Flask**: Lightweight web framework for API endpoints
- **Threading**: Non-blocking web server alongside gRPC server
- **JSON APIs**: RESTful endpoints for data access
- **Template Engine**: Jinja2 for HTML rendering

### Frontend
- **Bootstrap 5**: Modern, responsive UI framework
- **Font Awesome**: Icon library for visual elements
- **JavaScript**: Dynamic updates and real-time data fetching
- **AJAX**: Asynchronous data loading without page refreshes

### Data Sources
- **Gateway Server**: Direct access to `WxCCGatewayServer` instance
- **Virtual Agent Router**: Access to router and connector information
- **Session Tracking**: Real-time session and connection event data

## API Endpoints

### Status and Health
- `GET /` - Main dashboard with real-time data
- `GET /status` - Basic status information
- `GET /health` - Health check endpoint
- `GET /api/status` - Detailed status JSON API

### Configuration and Data
- `GET /api/config` - Gateway configuration information
- `GET /api/connections` - Active sessions and connection history
- `GET /api/debug/sessions` - Detailed session debugging information

### Testing and Development
- `GET /api/test/create-session` - Create test session for UI testing

## Dashboard Components

### Status Overview
```json
{
  "status": "running",
  "uptime": "2h 15m 30s",
  "active_sessions": 3,
  "total_connections": 15,
  "available_agents": ["Local Playback"]
}
```

### Active Connections
```json
{
  "active_sessions": [
    {
      "session_id": "session_123",
      "agent_id": "Local Playback",
      "customer_org_id": "org_456",
      "start_time": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### Connection History
```json
{
  "connection_events": [
    {
      "event_type": "start",
      "session_id": "session_123",
      "agent_id": "Local Playback",
      "timestamp": 1705312200.0,
      "customer_org_id": "org_456"
    }
  ]
}
```

## Installation and Setup

### Prerequisites
- Python 3.8+
- Flask web framework
- Access to gateway server instance

### Configuration

The monitoring interface is configured via the main `config.yaml`:

```yaml
monitoring:
  enabled: true
  host: "0.0.0.0"
  port: 8080
  debug: false
  metrics_enabled: true
  health_check_interval: 30
```

### Starting the Interface

The monitoring interface is automatically started with the main gateway:

```bash
# Start gateway with monitoring
python main.py

# Access monitoring interface
open http://localhost:8080
```

## Development

### Adding New Features

1. **New API Endpoints**: Add routes to `app.py`
2. **Frontend Components**: Update `templates/dashboard.html`
3. **Data Sources**: Extend gateway server for new data
4. **Styling**: Update CSS and Bootstrap classes

### Testing

```bash
# Test API endpoints
curl http://localhost:8080/api/status
curl http://localhost:8080/api/connections

# Test dashboard
open http://localhost:8080
```

### Customization

#### Adding New Metrics

```python
# In app.py
@app.route('/api/custom-metrics')
def api_custom_metrics():
    return jsonify({
        "custom_metric": "value",
        "timestamp": time.time()
    })
```

#### Custom Dashboard Sections

```html
<!-- In dashboard.html -->
<div class="card">
    <div class="card-header">
        <h5>Custom Section</h5>
    </div>
    <div class="card-body" id="custom-section">
        <!-- Dynamic content -->
    </div>
</div>
```

## Troubleshooting

### Common Issues

1. **Port Conflicts**: Change port in `config.yaml` if 8080 is in use
2. **No Data Displayed**: Check gateway server is running and accessible
3. **Template Errors**: Verify Jinja2 templates are properly formatted
4. **JavaScript Errors**: Check browser console for JavaScript errors

### Debug Mode

Enable debug mode for detailed error information:

```yaml
monitoring:
  debug: true
```

### Logs

Monitor application logs for errors:

```bash
# Check gateway logs
tail -f logs/gateway.log

# Check Flask logs (if debug enabled)
python main.py 2>&1 | grep "monitoring"
```

## Security Considerations

- **Access Control**: Consider implementing authentication for production
- **Network Security**: Use HTTPS in production environments
- **Data Privacy**: Ensure sensitive session data is properly handled
- **Rate Limiting**: Implement rate limiting for API endpoints

## Performance

### Optimization Tips

- **Caching**: Implement caching for frequently accessed data
- **Compression**: Enable gzip compression for static assets
- **CDN**: Use CDN for static assets in production
- **Database**: Consider persistent storage for historical data

### Monitoring

- **Response Times**: Monitor API endpoint response times
- **Memory Usage**: Track memory usage of monitoring interface
- **Error Rates**: Monitor error rates and types
- **User Activity**: Track dashboard usage patterns

## License

This code is licensed under the [Cisco Sample Code License v1.1](../LICENSE). See the main project README for details. 