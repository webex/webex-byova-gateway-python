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

## Authentication

The monitoring dashboard is protected by Webex OAuth authentication with organization-based access control. This ensures that only authorized users from approved organizations can access the gateway monitoring interface.

> **⚠️ IMPORTANT: Sample Implementation for Development**
>
> This authentication implementation is a **sample/reference implementation** designed for learning and development purposes. The configuration described below uses environment variables set directly in your shell (via `export` commands).
>
> **For production deployments**, you **MUST**:
> - Use a secure secret management service (AWS Secrets Manager, Azure Key Vault, HashiCorp Vault, etc.)
> - **Never** store credentials in code, configuration files, or environment variables in production
> - Implement proper secret rotation policies
> - Use separate credentials for each environment (dev/staging/production)
> - Implement comprehensive security auditing and monitoring
>
> **This gateway does NOT use `.env` files**. All environment variables must be set using `export` commands or loaded from a secret manager.

### Authentication Flow

```
┌─────────────┐                                     ┌─────────────┐
│   User      │                                     │   Webex     │
│  Browser    │                                     │   OAuth     │
└──────┬──────┘                                     └──────┬──────┘
       │                                                   │
       │  1. Access Dashboard (/)                          │
       ├──────────────────────────────────►                │
       │                                  │                │
       │  2. Redirect to /login          │                │
       │◄─────────────────────────────────┤                │
       │                                  │                │
       │  3. Click "Login with Webex"    │                │
       ├──────────────────────────────────┼───────────────►│
       │                                  │                │
       │  4. OAuth Authorization         │                │
       │◄─────────────────────────────────┼────────────────┤
       │                                  │                │
       │  5. User grants permission       │                │
       ├──────────────────────────────────┼───────────────►│
       │                                  │                │
       │  6. Redirect to /oauth with code│                │
       │◄─────────────────────────────────┼────────────────┤
       │                                  │                │
       │  7. Exchange code for tokens    │                │
       │                                  ├───────────────►│
       │                                  │                │
       │  8. Return access & id tokens   │                │
       │                                  │◄───────────────┤
       │                                  │                │
       │  9. Validate org ID              │                │
       │     ✓ Create session             │                │
       │     ✗ Show error                 │                │
       │                                  │                │
       │  10. Redirect to Dashboard (/)   │                │
       │◄─────────────────────────────────┤                │
       │                                  │                │
```

### Organization Validation

After successful OAuth authentication, the application validates the user's organization ID against a configured list of authorized organizations:

1. **Extract Organization ID**: Parse the access token which is formatted as `{access_token}_{ci_cluster}_{org_id}` and extract the third component
2. **Load Authorized Organizations**: Read from the `AUTHORIZED_WEBEX_ORG_IDS` environment variable
3. **Validate**: Check if the user's organization ID is in the authorized list
4. **Grant/Deny Access**: Allow dashboard access only for authorized organizations

**Note**: The organization ID is embedded in the Webex access token itself, not in the OpenID Connect JWT claims.

### Session Management

User sessions are managed using Flask's session mechanism:

- **Session Storage**: Server-side session with encrypted cookies
- **Session Timeout**: Configurable timeout (default: 24 hours)
- **Token Storage**: Access and ID tokens stored in session
- **User Information**: Name, email, and org ID cached in session
- **Automatic Expiration**: Sessions expire after configured timeout period

### Configuration

Authentication is configured in `config/config.yaml`, which specifies the **names** of environment variables to read credentials from:

```yaml
authentication:
  enabled: true
  environment: "dev"  # or "production"

  session:
    timeout_hours: 24
    secret_key_env: "FLASK_SECRET_KEY"  # Reads from $FLASK_SECRET_KEY

  webex_oauth:
    client_id_env: "WEBEX_CLIENT_ID"     # Reads from $WEBEX_CLIENT_ID
    client_secret_env: "WEBEX_CLIENT_SECRET"  # Reads from $WEBEX_CLIENT_SECRET
    redirect_uri_env: "WEBEX_REDIRECT_URI"    # Reads from $WEBEX_REDIRECT_URI
    scopes: "openid email profile"
    state: "byova_gateway_auth"

  authorized_orgs_env: "AUTHORIZED_WEBEX_ORG_IDS"  # Reads from $AUTHORIZED_WEBEX_ORG_IDS
```

**Setting Up Environment Variables for Development:**

```bash
# Generate a random secret key
export FLASK_SECRET_KEY="$(openssl rand -hex 32)"

# Set Webex OAuth credentials from your Webex Integration
export WEBEX_CLIENT_ID="your-client-id"
export WEBEX_CLIENT_SECRET="your-client-secret"
export WEBEX_REDIRECT_URI="http://localhost:8080/oauth"

# Set your organization ID
export AUTHORIZED_WEBEX_ORG_IDS="your-org-id"
```

For detailed setup instructions, see the [Authentication Quick Start Guide](../../AUTHENTICATION_QUICKSTART.md).

### Troubleshooting Authentication

#### Login Issues

**Problem**: Redirect loop or unable to log in

**Solutions**:
- Verify environment variables are set correctly
- Check Webex Integration configuration (redirect URI must match)
- Ensure `FLASK_SECRET_KEY` is set and consistent
- Clear browser cookies and try again

**Problem**: "Your organization is not authorized" error

**Solutions**:
- Verify your organization ID is in `AUTHORIZED_WEBEX_ORG_IDS`
- Check for typos in organization ID (case-sensitive)
- Confirm environment variables are loaded (run `echo $AUTHORIZED_WEBEX_ORG_IDS`)

#### Session Issues

**Problem**: Session expires too quickly

**Solutions**:
- Increase `timeout_hours` in configuration
- Check system clock is synchronized
- Verify `session.permanent = True` is set in code

**Problem**: Session doesn't persist across restarts

**Solutions**:
- Use a consistent `FLASK_SECRET_KEY` (not random each time)
- Consider using a session backend like Redis for production

#### Token Issues

**Problem**: Invalid or expired tokens

**Solutions**:
- Tokens expire after 1 hour - re-authenticate
- Check Webex Integration credentials are correct
- Verify redirect URI exactly matches integration settings
- Check for network issues connecting to Webex APIs

#### Configuration Issues

**Problem**: Authentication not working

**Solutions**:
```bash
# Check if authentication is enabled
grep -A 3 "authentication:" config/config.yaml

# Verify environment variables
echo $WEBEX_CLIENT_ID
echo $WEBEX_CLIENT_SECRET
echo $WEBEX_REDIRECT_URI
echo $AUTHORIZED_WEBEX_ORG_IDS
echo $FLASK_SECRET_KEY

# Test OAuth URL construction
curl -v http://localhost:8080/login
```

**Problem**: Missing environment variables

**Solutions**:
- Ensure variables are exported in your shell using `export` commands
- Add to shell profile for persistence (~/.zshrc, ~/.bashrc)
- Verify variables are set: `echo $WEBEX_CLIENT_ID`
- Check variables are loaded in Python: `os.getenv('VARIABLE_NAME')`
- **Note**: This gateway does NOT use `.env` files - variables must be set in your shell or loaded from a secret manager

### Disabling Authentication

For development or testing, you can disable authentication:

```yaml
# config/config.yaml
authentication:
  enabled: false
```

When disabled, the dashboard is accessible without login. **Never disable authentication in production.**

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

### Authentication and Access Control

- **OAuth 2.0**: Production-ready Webex OAuth implementation
- **Organization Validation**: Only authorized organizations can access the dashboard
- **Session Management**: Secure session handling with encrypted cookies
- **Token Security**: Access and ID tokens stored securely in server-side sessions
- **Session Timeout**: Configurable session expiration (default: 24 hours)
- **Protected Routes**: Main dashboard requires authentication
- **Public APIs**: Monitoring APIs remain accessible for health checks

### Network Security

- **HTTPS Required**: Always use HTTPS in production environments
- **Secure Cookies**: Enable secure cookie flags in production
- **CORS Protection**: Configure CORS policies for production
- **Network Isolation**: Deploy in private networks when possible

### Credential Management

- **Development Setup**: Set environment variables directly using `export` commands (development/testing only)
- **No .env Files**: This gateway does NOT use `.env` files - set environment variables in your shell
- **Production Setup**: Use AWS Secrets Manager, Azure Key Vault, or similar secret management service
- **No Hard-coded Secrets**: Never commit credentials to version control or configuration files
- **Regular Rotation**: Rotate credentials periodically, especially in production
- **Separate Credentials**: Use different credentials for dev/staging/production environments

### Data Privacy

- **Session Data**: Sensitive data encrypted in sessions
- **Logging**: Avoid logging tokens or sensitive user data
- **PII Protection**: Handle personally identifiable information appropriately
- **Token Expiration**: Tokens expire automatically (1 hour for Webex)

### Additional Security Measures

- **Rate Limiting**: Consider implementing rate limiting for API endpoints
- **Input Validation**: Validate all user inputs
- **XSS Protection**: Template engine provides XSS protection
- **CSRF Protection**: OAuth state parameter provides CSRF protection

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