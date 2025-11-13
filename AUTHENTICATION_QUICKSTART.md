# Authentication Quick Start Guide

This guide will help you quickly set up and test Webex authentication for the BYOVA Gateway monitoring dashboard.

## Prerequisites

- Python 3.8+ with virtual environment activated
- Access to [Webex Developer Portal](https://developer.webex.com/)
- A Webex account

## Step 1: Create a Webex Integration

1. Go to https://developer.webex.com/
2. Log in with your Webex account
3. Click **"Create an Integration"** (under "My Apps")
4. Fill in the form:
   - **Integration Name**: BYOVA Gateway Monitor (Dev)
   - **Icon**: Upload an icon or use default
   - **Description**: Development environment for BYOVA Gateway monitoring
   - **Redirect URI**: `http://localhost:8080/oauth`
   - **Scopes**: Check `openid`, `email`, and `profile`
5. Click **"Add Integration"**
6. **Save your Client ID and Client Secret** - you'll need these next

## Step 2: Find Your Organization ID

### Method 1: Using Access Token Parsing

1. Get your Webex access token from the Developer Portal (click your profile icon)
2. The access token format is: `{access_token}_{ci_cluster}_{org_id}`
3. Split the token by underscores and take the third part
4. Copy the organization ID (the third segment after splitting)

Example in a browser console or terminal:
```javascript
// JavaScript
let accessToken = "your_access_token_here";
let parts = accessToken.split('_');
let orgId = parts[2];
console.log("Organization ID:", orgId);
```

```bash
# Bash
echo "your_access_token_here" | awk -F'_' '{print $3}'
```

### Method 2: Using Webex API

1. Go to https://developer.webex.com/docs/api/v1/people/get-my-own-details
2. Click "Run" in the API Reference
3. Look for `orgId` in the response
4. Copy the organization ID

## Step 3: Set Environment Variables

### For macOS/Linux (bash/zsh):

```bash
# Generate a random secret key
export FLASK_SECRET_KEY="$(openssl rand -hex 32)"

# Set Webex OAuth credentials
export WEBEX_CLIENT_ID="your-client-id-from-step-1"
export WEBEX_CLIENT_SECRET="your-client-secret-from-step-1"
export WEBEX_REDIRECT_URI="http://localhost:8080/oauth"

# Set your organization ID
export AUTHORIZED_WEBEX_ORG_IDS="your-org-id-from-step-2"
```

### For Persistent Configuration:

Add these to your shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
# Add to ~/.zshrc or ~/.bashrc
export FLASK_SECRET_KEY="$(openssl rand -hex 32)"
export WEBEX_CLIENT_ID="Cyour-client-id"
export WEBEX_CLIENT_SECRET="your-client-secret"
export WEBEX_REDIRECT_URI="http://localhost:8080/oauth"
export AUTHORIZED_WEBEX_ORG_IDS="your-org-id"
```

Then reload your shell:
```bash
source ~/.zshrc  # or source ~/.bashrc
```

## Step 4: Verify Configuration

Check that all environment variables are set:

```bash
echo "Flask Secret: $FLASK_SECRET_KEY"
echo "Client ID: $WEBEX_CLIENT_ID"
echo "Client Secret: $WEBEX_CLIENT_SECRET"
echo "Redirect URI: $WEBEX_REDIRECT_URI"
echo "Authorized Orgs: $AUTHORIZED_WEBEX_ORG_IDS"
```

All values should be displayed (not empty).

## Step 5: Start the Gateway

```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Start the gateway
python main.py
```

You should see output indicating both servers have started:
```
Starting BYOVA Gateway monitoring web app on 0.0.0.0:8080
```

## Step 6: Test Authentication

1. **Open the dashboard**: http://localhost:8080
2. **Expected behavior**: You should be redirected to `/login`
3. **Click "Login with Webex"**
4. **Authorize the integration**: Log in with your Webex credentials and authorize the app
5. **Expected result**: You should be redirected back to the dashboard
6. **Verify**: Your name and email should appear in the top right corner

## Step 7: Test Logout

1. Click the **"Logout"** button in the top right
2. **Expected behavior**: You should be redirected back to the login page
3. **Verify**: Trying to access http://localhost:8080 should redirect to login

## Troubleshooting

### "Your organization is not authorized" Error

**Problem**: After logging in with Webex, you see this error message.

**Solution**:
1. Verify your organization ID is correct:
   ```bash
   echo $AUTHORIZED_WEBEX_ORG_IDS
   ```
2. Make sure the org ID matches exactly (case-sensitive)
3. Restart the gateway after changing environment variables

### "No authorization code received" Error

**Problem**: OAuth callback fails with this error.

**Solution**:
1. Check that your Redirect URI in the Webex Integration matches exactly: `http://localhost:8080/oauth`
2. Make sure the `WEBEX_REDIRECT_URI` environment variable matches
3. Try recreating the integration with the correct redirect URI

### Environment Variables Not Loading

**Problem**: Gateway starts but authentication doesn't work.

**Solution**:
1. Make sure environment variables are exported in the current shell
2. Check variables are set:
   ```bash
   env | grep WEBEX
   env | grep FLASK
   env | grep AUTHORIZED
   ```
3. Restart the gateway after setting variables
4. Make sure you're running from the same terminal where you set the variables

### Redirect Loop

**Problem**: Browser keeps redirecting between login and dashboard.

**Solution**:
1. Clear browser cookies for localhost:8080
2. Check that `FLASK_SECRET_KEY` is set and consistent
3. Make sure authentication is enabled in `config/config.yaml`:
   ```yaml
   authentication:
     enabled: true
   ```

## Testing API Endpoints (No Auth Required)

API endpoints remain accessible without authentication:

```bash
# Test status endpoint
curl http://localhost:8080/api/status

# Test health endpoint
curl http://localhost:8080/health

# Test connections endpoint
curl http://localhost:8080/api/connections
```

## Disabling Authentication (Development Only)

To disable authentication for local testing:

1. Edit `config/config.yaml`:
   ```yaml
   authentication:
     enabled: false
   ```
2. Restart the gateway
3. Dashboard will be accessible without login

**Warning**: Never disable authentication in production!

## Adding Additional Authorized Organizations

To authorize multiple organizations:

```bash
export AUTHORIZED_WEBEX_ORG_IDS="org-id-1,org-id-2,org-id-3"
```

Separate organization IDs with commas (no spaces).

## Next Steps

- Review the [main README](README.md#authentication-setup) for production deployment
- Check [monitoring README](src/monitoring/README.md#authentication) for detailed auth flow
- Set up AWS Secrets Manager for production (see main README)

## Support

For issues or questions:
1. Check the [monitoring README troubleshooting section](src/monitoring/README.md#troubleshooting-authentication)
2. Review [Webex OAuth documentation](https://developer.webex.com/docs/integrations)
3. Create an issue in the repository

