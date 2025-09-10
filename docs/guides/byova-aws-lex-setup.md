---
layout: guide
title: Building Voice AI with Webex Contact Center BYOVA and AWS Lex
description: A Complete Developer Guide
date: 2025-09-10
---

# Building Voice AI with Webex Contact Center BYOVA and AWS Lex: A Complete Developer Guide

*Transform your contact center with intelligent voice interactions using Webex Contact Center's BYOVA (Bring Your Own Virtual Agent) feature and AWS Lex.*

---

## Table of Contents

1. [Introduction](#introduction)
2. [Prerequisites](#prerequisites)
3. [Step 1: Setting Up Your Webex Contact Center Sandbox](#step-1-setting-up-your-webex-contact-center-sandbox)
4. [Step 2: Configuring BYOVA and BYODS](#step-2-configuring-byova-and-byds)
5. [Step 3: Setting Up AWS Lex](#step-3-setting-up-aws-lex)
6. [Step 4: Configuring the BYOVA Gateway](#step-4-configuring-the-byova-gateway)
7. [Step 5: Testing Your Integration](#step-5-testing-your-integration)
8. [Troubleshooting](#troubleshooting)
9. [Next Steps](#next-steps)

---

## Introduction

Webex Contact Center's BYOVA (Bring Your Own Virtual Agent) feature allows you to integrate your own AI-powered voice agents directly into your contact center workflows. Combined with AWS Lex, you can create sophisticated conversational AI experiences that handle customer inquiries, route calls, and provide intelligent responses.

This guide will walk you through the complete process of:
- Setting up a Webex Contact Center sandbox environment
- Configuring BYOVA and BYODS (Bring Your Own Data Source)
- Creating and configuring an AWS Lex bot
- Deploying and configuring the BYOVA Gateway
- Testing your voice AI integration end-to-end

**What You'll Build:**
A fully functional voice AI system where customers can call your contact center, interact with an AWS Lex-powered virtual agent, and seamlessly transfer to human agents when needed.

---

## Prerequisites

Before starting, ensure you have:

- **Webex Account**: A free Webex account (create one at [webex.com](https://webex.com) if needed)
- **AWS Account**: An active AWS account with appropriate permissions
- **Development Environment**: 
  - Python 3.8 or higher
  - Git
  - Terminal/Command Prompt access
- **Basic Knowledge**: Familiarity with:
  - Webex Contact Center concepts
  - AWS services (Lex, IAM)
  - Python development
  - gRPC and REST APIs

---

## Step 1: Setting Up Your Webex Contact Center Sandbox

### 1.1 Request a Sandbox

1. **Sign in to Webex Developer Portal**
   - Go to [developer.webex.com](https://developer.webex.com)
   - Sign in with your Webex account

2. **Navigate to Contact Center Sandbox**
   - Go to [Contact Center Sandbox](https://developer.webex.com/create/docs/sandbox_cc)
   - Click **"Request a Sandbox"**

3. **Complete the Request Process**
   - Read and accept the Terms and Conditions
   - Check "By creating this app, I accept the Terms of Service"
   - Click **"Request a Sandbox"**

4. **Wait for Provisioning**
   - Sandbox creation takes up to 15 minutes
   - You'll receive several emails with account details
   - **Save the final provisioning email** - it contains critical information

### 1.2 Access Your Sandbox

Your provisioning email will contain:

**Administrator Account:**
- **Username**: `admin@xxxxxx-xxxx.wbx.ai`
- **Password**: `********`
- **Webex Site URL**: `xxxxxx-xxxx.webex.com`

**Agent Accounts:**
- **Premium Agent**: `user1@xxxxxx-xxxx.wbx.ai` (Extension: 1001)
- **Supervisor Agent**: `user2@xxxxxx-xxxx.wbx.ai` (Extension: 1002)

**Phone Numbers:**
- **Main PSTN Number**: `+1nnnnnnnnnn` (for Webex calling)
- **Entrypoint Number**: `+1nnnnnnnnnn` (for Contact Center)

### 1.3 Access the Administrator Portal

1. **Open a Private/Incognito Browser Window**
   - Chrome: `Ctrl+Shift+N` (Windows) or `Cmd+Shift+N` (Mac)
   - Firefox: `Ctrl+Shift+P` (Windows) or `Cmd+Shift+P` (Mac)

2. **Navigate to the Administrator Portal**
   - Go to [https://admin.webex.com](https://admin.webex.com)
   - Enter your administrator email and password from the provisioning email

3. **Verify Access**
   - You should see the Webex Contact Center Administrator Portal
   - Note the site configuration and available features

---

## Step 2: Configuring BYOVA and BYODS

### 2.1 Understanding BYOVA and BYODS

- **BYOVA (Bring Your Own Virtual Agent)**: Allows you to integrate external AI services as virtual agents
- **BYODS (Bring Your Own Data Source)**: Enables integration with external data sources for enhanced AI capabilities
  - BYOVA builds on top of the BYODS framework
  - Provides secure, standardized data exchange between Webex and third-party providers
  - Uses JWS (JSON Web Signature) tokens for authentication
  - Requires Service App creation and admin authorization

**Important**: BYOVA requires BYODS setup first, as the virtual agent configuration depends on having a registered data source.

### 2.2 Create a Service App for BYODS

Before configuring BYOVA, we need to set up a Service App for data source integration, as BYOVA builds on top of the BYODS (Bring Your Own Data Source) framework.

1. **Navigate to Webex Developer Portal**
   - Go to [developer.webex.com](https://developer.webex.com)
   - Sign in with your Webex account

2. **Create a New Service App**
   - Go to **My Apps** → **Create a New App**
   - Choose **Service App** as the application type

3. **Configure the Service App**
   - **Name**: `BYOVA Gateway Service App` (or your preferred name)
   - **Data Exchange Schema**: Select `VA_service_schema` for voice virtual agent interactions
     - This schema (ID: `5397013b-7920-4ffc-807c-e8a3e0a18f43`) is specifically designed for voice virtual agent services
     - Reference: [VoiceVirtualAgent Schema](https://github.com/webex/dataSourceSchemas/tree/v1.10/Services/VoiceVirtualAgent/5397013b-7920-4ffc-807c-e8a3e0a18f43)
   - **Domains**: Specify your gateway domain (e.g., `your-domain.com` or `your-ip-address`)
     - Avoid registering ports in the domain - all ports will be accepted later
   - **Scopes**: Ensure you select:
     - `spark-admin:datasource_read`
     - `spark-admin:datasource_write`
   - Complete any other required information

4. **Submit for Admin Approval**
   - In your sandbox, select **"Request Admin Approval"**
   - This makes the Service App visible in Control Hub for admin authorization

### 2.3 Register Your Data Source

1. **Get Admin Authorization**
   - In Control Hub (admin.webex.com), navigate to **Services** → **Data Sources**
   - Find your Service App and click **"Authorize"**
   - This generates org-specific access and refresh tokens

2. **Register the Data Source**
   - Use the access token from step 1 to register your data source
   - Make a POST request to `/v1/datasources` with the following payload:
   - **API Reference**: [Register a Data Source](https://developer.webex.com/admin/docs/api/v1/data-sources/register-a-data-source)

   ```json
   {
     "schemaId": ["5397013b-7920-4ffc-807c-e8a3e0a18f43"],
     "url": "https://your-gateway-ip:50051",
     "audience": "BYOVAGateway",
     "subject": "callAudioData",
     "nonce": "123456",
     "tokenLifeMinutes": "1440"
   }
   ```

3. **Save the JWS Token**
   - The response will include a `jwsToken` for authenticating requests
   - Save this token and the `tokenExpiryTime` for later use
   - **Important**: Tokens expire in 1-24 hours and must be refreshed before expiration
   - Update the data source with a new `nonce` to refresh the token

**Reference**: For detailed BYODS setup instructions, see the [Bring Your Own Data Source documentation](https://developer.webex.com/create/docs/bring-your-own-datasource).

### 2.4 Configure BYOVA Virtual Agent

1. **Navigate to Virtual Agents**
   - In Control Hub, go to **Services** → **Virtual Agents**
   - Click **"Add Virtual Agent"**

2. **Configure Virtual Agent Settings**
   - **Name**: `AWS Lex Virtual Agent`
   - **Type**: Select **"External"** or **"Custom"**
   - **Endpoint**: `http://your-gateway-ip:50051`
   - **Protocol**: `gRPC`
   - **Data Source**: Select the data source you registered in step 2.3
   - **Status**: `Active`

3. **Configure Authentication**
   - Use the JWS token from your data source registration
   - Ensure the token is refreshed before expiration (max 24 hours)

### 2.5 Import the BYOVA Flow Template

1. **Navigate to Control Hub**
   - Go to [https://admin.webex.com/login](https://admin.webex.com/login)
   - Sign in with your administrator credentials from the provisioning email

2. **Access Contact Center Flows**
   - In Control Hub, navigate to **Contact Center**
   - Click on **Flows**
   - Select **Manage Flows**
   - Click **Import Flow**

   **Reference**: For detailed information about Flow Designer and flow management, see the [Build and manage flows with Flow Designer documentation](https://help.webex.com/en-us/article/nhovcy4/Build-and-manage-flows-with-Flow-Designer#Cisco_Task.dita_0e76fcdd-29a3-47c3-8544-f6613dfeb8f0).

3. **Import the BYOVA Flow Template**
   - Download the `BYOVA_Gateway_Flow.json` file from the gateway repository (located in the project root)
   - In the import dialog, choose the `BYOVA_Gateway_Flow.json` file
   - The flow will be imported with the name "BYOVA"

4. **Configure the Virtual Agent**
   - In the imported flow, locate the **VirtualAgentV2_q2c** activity
   - Click on the activity to open its properties
   - Update the **Virtual Agent** selection:
     - **Connector Name**: Select your BYOVA connector (e.g., "AWS Lex Connector")
     - **Virtual Agent ID**: Select your configured virtual agent
   - Save the activity configuration

5. **Review Flow Structure**
   The imported flow includes:
   - **Start**: Entry point for calls
   - **Virtual Agent**: Routes to your BYOVA virtual agent
   - **Decision Logic**: Handles agent disconnection and transfer scenarios
   - **Play Message**: Provides feedback to callers
   - **End**: Terminates the call

6. **Save and Activate the Flow**
   - Save your flow configuration
   - Activate the flow for testing

### 2.6 Assign Flow to Entry Point

1. **Navigate to Channels**
   - In Control Hub, go to **Contact Center** → **Channels**
   - Select **Entry Point 1** (or your configured entry point)

2. **Configure Entry Point Routing**
   - In the Entry Point 1 configuration, locate the **Routing Flow** setting
   - Change the routing flow from the default to your **BYOVA** flow
   - Save the configuration

3. **Verify Assignment**
   - Confirm that Entry Point 1 is now using the BYOVA flow
   - The entry point will now route calls through your virtual agent integration

---

## Step 3: Testing with Local Audio Connector

Before setting up AWS Lex, let's test the BYOVA integration using the local audio connector. This allows you to verify that your BYOVA configuration is working correctly with pre-recorded audio files.

### 3.1 Configure the Local Audio Connector

1. **Update Gateway Configuration**
   - Edit `config/config.yaml` to ensure the local audio connector is enabled
   - The local connector should already be configured by default:

   ```yaml
   connectors:
     local_audio_connector:
       type: "local_audio_connector"
       class: "LocalAudioConnector"
       module: "connectors.local_audio_connector"
       config:
         audio_files:
           welcome: "welcome.wav"
           transfer: "transferring.wav"
           goodbye: "goodbye.wav"
           error: "error.wav"
           default: "default_response.wav"
         agents:
           - "Local Playback"
   ```

2. **Prepare Audio Files**
   - Ensure audio files are in the `audio/` directory
   - Default files should already be present:
     - `welcome.wav` - Welcome message
     - `default_response.wav` - Response messages
     - `goodbye.wav` - Goodbye message
     - `transferring.wav` - Transfer message
     - `error.wav` - Error message

### 3.2 Start the Gateway

1. **Activate Virtual Environment**
   ```bash
   source venv/bin/activate
   ```

2. **Start the Gateway**
   ```bash
   python main.py
   ```

3. **Verify Startup**
   - Check that both gRPC server (port 50051) and web interface (port 8080) are running
   - Access the monitoring interface at `http://localhost:8080`

### 3.3 Test the Local Connector

1. **Make a Test Call**
   - Call the entrypoint number from your sandbox provisioning email
   - You should hear the welcome message from the local audio connector

2. **Verify Audio Playback**
   - The local connector will play the configured audio files
   - Check the monitoring interface for active connections
   - Review logs to ensure proper audio file playback

3. **Test Flow Integration**
   - Verify the call flows through your imported BYOVA flow
   - Test different scenarios (welcome, responses, goodbye)
   - Ensure proper call termination

### 3.4 Troubleshoot Local Connector Issues

**Common Issues:**
- **No Audio**: Check that audio files exist in the `audio/` directory
- **Wrong Audio**: Verify audio file names match the configuration
- **Connection Issues**: Ensure the gateway is accessible from Webex Contact Center

**Debug Commands:**
```bash
# Check gateway status
curl http://localhost:8080/api/status

# View available agents
curl http://localhost:8080/api/agents

# Check active connections
curl http://localhost:8080/api/connections
```

Once the local connector is working correctly, you can proceed to set up AWS Lex for more sophisticated voice AI interactions.

---

## Step 4: Setting Up AWS Lex

### 4.1 Create an AWS Lex Bot

1. **Sign in to AWS Console**
   - Go to [aws.amazon.com](https://aws.amazon.com)
   - Sign in to your AWS account

2. **Navigate to Amazon Lex**
   - Search for "Lex" in the AWS services search
   - Click on **Amazon Lex V2**

3. **Create a New Bot**
   - Click **"Create Bot"**
   - Choose **"Create a blank bot"**

4. **Configure Bot Settings**
   - **Bot name**: `webex-contact-center-bot`
   - **IAM role**: Create new role or use existing
   - **Data privacy**: Configure as needed
   - **Idle session timeout**: `5 minutes`

### 4.2 Design Your Bot's Intent

1. **Create an Intent**
   - Click **"Create Intent"**
   - **Intent name**: `CustomerServiceIntent`

2. **Add Sample Utterances**
   ```
   I need help with my account
   How do I reset my password
   I want to speak to a human agent
   What are your business hours
   I have a billing question
   ```

3. **Configure Slots (Optional)**
   - Add slots for customer information if needed
   - Example: `customerId`, `issueType`, `priority`

4. **Set Up Responses**
   - **Fulfillment**: Use Lambda function or return static responses
   - **Confirmation prompt**: "Is there anything else I can help you with?"
   - **Follow-up prompt**: "What else can I help you with today?"

### 4.3 Configure Bot Alias

1. **Create Bot Alias**
   - Go to **Bot Aliases** tab
   - Click **"Create Bot Alias"**
   - **Alias name**: `TSTALIASID` (or your preferred name)
   - **Bot version**: Select the latest version

2. **Configure Alias Settings**
   - **Description**: `Test alias for Webex integration`
   - **Language**: `English (US)`
   - **Voice settings**: Configure as needed

### 4.4 Set Up IAM Permissions

1. **Create IAM User for BYOVA Gateway**
   - Go to **IAM** → **Users** → **Create User**
   - **Username**: `webex-byova-gateway`
   - **Access type**: Programmatic access

2. **Attach Policies**
   - Attach the following policies:
     - `AmazonLexFullAccess`
     - `AmazonPollyReadOnlyAccess` (for text-to-speech)

3. **Create Access Keys**
   - Go to **Security credentials** tab
   - Click **"Create access key"**
   - **Use case**: Application running outside AWS
   - **Save the Access Key ID and Secret Access Key**

### 4.5 Test Your Bot

1. **Test in Lex Console**
   - Use the test window in the Lex console
   - Try various utterances to ensure your bot responds correctly

2. **Verify Bot Alias**
   - Ensure your bot alias is working
   - Note the bot ID and alias ID for configuration

---

## Step 5: Configuring the BYOVA Gateway

### 5.1 Clone and Set Up the Gateway

1. **Clone the Repository**
   ```bash
   git clone https://github.com/your-org/webex-byova-gateway-python.git
   cd webex-byova-gateway-python
   ```

2. **Create Virtual Environment**
   ```bash
   # Create virtual environment
   python -m venv venv
   
   # Activate virtual environment (REQUIRED)
   # On macOS/Linux:
   source venv/bin/activate
   # On Windows:
   # venv\Scripts\activate
   
   # Verify activation - you should see (venv) in your prompt
   which python  # Should show path to venv/bin/python
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Generate gRPC Stubs**
   ```bash
   python -m grpc_tools.protoc -I./proto --python_out=src/generated --grpc_python_out=src/generated proto/*.proto
   ```

### 5.2 Configure AWS Lex Connector

1. **Set AWS Credentials**
   ```bash
   # Set environment variables (recommended for production)
   export AWS_ACCESS_KEY_ID=your_access_key_here
   export AWS_SECRET_ACCESS_KEY=your_secret_key_here
   export AWS_DEFAULT_REGION=us-east-1
   ```

2. **Update Configuration File**
   Edit `config/config.yaml`:
   ```yaml
   # Gateway settings
   gateway:
     host: "0.0.0.0"
     port: 50051

   # Monitoring interface
   monitoring:
     enabled: true
     host: "0.0.0.0"
     port: 8080

   # Connectors
   connectors:
     # AWS Lex Connector
     aws_lex_connector:
       type: "aws_lex_connector"
       class: "AWSLexConnector"
       module: "connectors.aws_lex_connector"
       config:
         region_name: "us-east-1"  # Your AWS region
         bot_alias_id: "TSTALIASID"  # Your bot alias
         barge_in_enabled: false
         audio_logging:
           enabled: true
           output_dir: "logs/audio_recordings"
           filename_format: "{conversation_id}_{timestamp}_{source}.wav"
           log_all_audio: true
           max_file_size: 10485760
           sample_rate: 8000
           bit_depth: 8
           channels: 1
           encoding: "ulaw"
         agents: []
   ```

### 5.3 Configure Network Access

1. **Determine Your Gateway's IP Address**
   ```bash
   # On macOS/Linux:
   ifconfig | grep "inet " | grep -v 127.0.0.1
   
   # On Windows:
   ipconfig
   ```

2. **Update Webex Contact Center Configuration**
   - In the Administrator Portal, update your virtual agent endpoint
   - Use: `http://your-gateway-ip:50051`

3. **Configure Firewall (if needed)**
   - Ensure port 50051 is accessible from Webex Contact Center
   - For testing, you may need to configure port forwarding

### 5.4 Start the Gateway

1. **Start the Server**
   ```bash
   # Ensure virtual environment is activated
   source venv/bin/activate
   
   # Start the gateway
   python main.py
   ```

2. **Verify Startup**
   - You should see output indicating both gRPC and web servers are running
   - Check the monitoring interface at `http://localhost:8080`

3. **Test Gateway Status**
   ```bash
   # Test the API
   curl http://localhost:8080/api/status
   
   # Check available agents
   curl http://localhost:8080/api/agents
   ```

---

## Step 6: Testing Your Integration

### 6.1 Set Up Agent Desktop

1. **Install Webex Contact Center Desktop**
   - Download from the Administrator Portal
   - Install on a test machine

2. **Log in as Agent**
   - Use the Premium Agent credentials from your provisioning email
   - Enter the extension number (1001)

3. **Set Agent Status to Available**
   - Ensure the agent is ready to receive calls

### 6.2 Test the Voice AI Integration

1. **Make a Test Call**
   - Call the entrypoint number from your provisioning email
   - You should hear the default greeting

2. **Interact with the Virtual Agent**
   - Speak naturally to test your AWS Lex bot
   - Try various utterances you configured
   - Test the conversation flow

3. **Test Agent Transfer**
   - Request to speak to a human agent
   - Verify the call transfers to your logged-in agent

### 6.3 Monitor the Integration

1. **Use the Monitoring Interface**
   - Open `http://localhost:8080` in your browser
   - Monitor active connections and session data

2. **Check Logs**
   - Review gateway logs for any errors
   - Check AWS CloudWatch logs for Lex activity

3. **Verify Audio Quality**
   - Test audio clarity and response times
   - Check audio recordings in `logs/audio_recordings/`

---

## Troubleshooting

### Common Issues and Solutions

#### 1. Gateway Won't Start
**Problem**: `python: command not found` or import errors
**Solution**: Ensure virtual environment is activated
```bash
source venv/bin/activate
which python  # Should show venv path
```

#### 2. AWS Lex Connection Issues
**Problem**: Authentication or region errors
**Solution**: Verify AWS credentials and region
```bash
aws sts get-caller-identity  # Test AWS credentials
```

#### 3. Webex Contact Center Can't Reach Gateway
**Problem**: Connection timeout or refused
**Solution**: Check network configuration
- Verify gateway IP address
- Ensure port 50051 is accessible
- Check firewall settings

#### 4. Audio Quality Issues
**Problem**: Poor audio quality or delays
**Solution**: Check audio configuration
- Verify sample rate (8000 Hz)
- Check encoding (u-law)
- Review network latency

#### 5. Bot Not Responding
**Problem**: Lex bot doesn't respond to utterances
**Solution**: Check bot configuration
- Verify bot alias ID
- Test bot in Lex console
- Check intent configuration

### Debug Commands

```bash
# Check gateway status
curl http://localhost:8080/api/status

# View active connections
curl http://localhost:8080/api/connections

# Check debug information
curl http://localhost:8080/api/debug/sessions

# Test AWS credentials
aws sts get-caller-identity

# Check Lex bot status
aws lex-models-v2 describe-bot --bot-id YOUR_BOT_ID
```

---

## Next Steps

### Enhance Your Integration

1. **Improve Bot Intelligence**
   - Add more intents and utterances
   - Implement slot filling for complex interactions
   - Add Lambda functions for dynamic responses

2. **Add Advanced Features**
   - Implement sentiment analysis
   - Add multi-language support
   - Integrate with CRM systems

3. **Scale Your Solution**
   - Deploy to production AWS environment
   - Implement load balancing
   - Add monitoring and alerting

4. **Customize the Gateway**
   - Add new connector types
   - Implement custom audio processing
   - Add advanced logging and analytics

### Production Considerations

1. **Security**
   - Use IAM roles instead of access keys
   - Implement proper authentication
   - Encrypt sensitive data

2. **Monitoring**
   - Set up CloudWatch alarms
   - Implement health checks
   - Add performance metrics

3. **Scalability**
   - Use auto-scaling groups
   - Implement load balancing
   - Plan for high availability

---

## Conclusion

You've successfully set up a complete voice AI integration using Webex Contact Center BYOVA and AWS Lex! This powerful combination allows you to:

- **Provide 24/7 intelligent customer service** with AI-powered virtual agents
- **Seamlessly transfer** complex inquiries to human agents when needed
- **Scale your contact center** without proportional increases in staff
- **Improve customer satisfaction** with faster response times and consistent service

The BYOVA Gateway provides a flexible foundation that you can extend and customize for your specific needs. Whether you're building a simple FAQ bot or a complex conversational AI system, this architecture gives you the tools to succeed.

### Resources

- [Webex Contact Center Developer Documentation](https://developer.webex.com)
- [AWS Lex Developer Guide](https://docs.aws.amazon.com/lex/)
- [BYOVA Gateway Repository](https://github.com/your-org/webex-byova-gateway-python)
- [Webex Contact Center Sandbox](https://developer.webex.com/create/docs/sandbox_cc)

### Support

For questions about this integration:
- Check the troubleshooting section above
- Review the gateway logs and monitoring interface
- Consult the AWS Lex and Webex Contact Center documentation
- Reach out to the developer community for assistance

Happy building! 🚀

---

*This guide provides a comprehensive walkthrough for integrating AWS Lex with Webex Contact Center using the BYOVA Gateway. The setup process is designed to be developer-friendly while following enterprise best practices for security and scalability.*
