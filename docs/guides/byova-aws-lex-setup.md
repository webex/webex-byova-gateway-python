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
3. [Step 1: Setting Up AWS Lex](#step-1-setting-up-aws-lex)
4. [Step 2: Configuring the BYOVA Gateway](#step-2-configuring-the-byova-gateway)
5. [Step 3: Setting Up Your Webex Contact Center Sandbox](#step-3-setting-up-your-webex-contact-center-sandbox)
6. [Step 4: Configuring BYOVA and BYODS](#step-4-configuring-byova-and-byods)
7. [Step 5: Testing Your Integration](#step-5-testing-your-integration)
8. [Troubleshooting](#troubleshooting)
9. [Next Steps](#next-steps)
10. [Conclusion](#conclusion)

---

## Introduction

Webex Contact Center's BYOVA (Bring Your Own Virtual Agent) feature allows you to integrate your own AI-powered voice agents directly into your contact center workflows. Combined with AWS Lex, you can create sophisticated conversational AI experiences that handle customer inquiries, route calls, and provide intelligent responses.

This guide will walk you through the complete process of:
- Setting up a Webex Contact Center sandbox environment
- Configuring BYOVA and BYODS (Bring Your Own Data Source)
- Creating and configuring a AWS Lex bot
- Deploying and configuring the BYOVA Gateway
- Testing your voice AI integration end-to-end

**What You'll Build:**
A fully functional voice AI system where customers can call your contact center, interact with an AWS Lex-powered virtual agent, and seamlessly transfer to human agents when needed.

---

## Prerequisites

Before starting, ensure you have:

- **Webex Account**: A Webex account (create one at [webex.com](https://webex.com) if needed)
- **AWS Account**: An active AWS account with appropriate permissions
- **Development Environment**: 
  - Python 3.8 or higher
  - Git
  - Terminal/Command Prompt access
- **Gateway Hosting**: Plan how you will publicly host the BYOVA Gateway:
  - **For Testing**: Use [ngrok](https://ngrok.com) (free tier available) or similar tunneling service to expose your local gateway
  - **For Production**: Prepare a public IP address or domain name where you'll deploy the gateway
    - Cloud hosting (AWS EC2, Azure VM, Google Cloud, etc.)
    - On-premises server with public IP
    - Container orchestration platform (Kubernetes, ECS, etc.)
  - **Note**: You'll need this domain/IP information in Step 2 when creating the Service App and registering the data source
- **Basic Knowledge**: Familiarity with:
  - Webex Contact Center concepts
  - AWS services (Lex, IAM)
  - Python development
  - gRPC and REST APIs

---

## Step 1: Setting Up AWS Lex

### 1.1 Sign in to your AWS account

1. Sign in to the AWS Management Console and open the Amazon Lex console at https://console.aws.amazon.com.


### 1.2 Create Your AWS Lex Bot

You can create a bot with Amazon Lex V2 in multiple ways. If you want to learn more about all the ways, refer to [this](https://docs.aws.amazon.com/lexv2/latest/dg/create-bot.html) guide.

In this section, you create an Amazon Lex bot (BookTrip).

1. Sign in to the AWS Management Console and open the Amazon Lex console at https://console.aws.amazon.com/lex/.

2. On the **Bots** page, choose **Create**.
3. On the **Create your Lex bot** page,
   - Choose **BookTrip** blueprint.
   - Leave the default bot name (BookTrip).
4. Choose **Create**. The console sends a series of requests to Amazon Lex to create the bot. Note the following:

5. The console shows the BookTrip bot. On the **Editor** tab, review the details of the preconfigured intents (BookCar and BookHotel).

6. Test the bot in the test window.

If you would like to use generative AI to optimize LexV2 bot creation and performance, please refer to this [guide](https://docs.aws.amazon.com/lexv2/latest/dg/generative-features.html)

If you wish to use AWS Bedrock Agents with a custom knowledge base—as part of your autonomous bot workflow, here are some guides that can help you [setup agents](https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html) and [knowledge base](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-create.html)

### 1.3 Lex Bot Configuration & Testing

Once you have successfully created the Lex bot following the documentations provided above, please make sure to add Agent Intent to your bot.

1. Sign in to the AWS Management Console and open the Amazon Lex console at https://console.aws.amazon.com/lex/.

2. From the list of bots, choose the bot that you created, then from **Add languages** choose **View languages**.

3. Choose the language to add the intent to, then choose **Intents**.
4. Choose **Add intent**, give your intent a name, and then choose **Add**.
5. Add **Sample Utterances**

   ```text
   Agent
   Can I talk to an agent
   Can I talk to a person
   Representative please
   Connect me to a person
   ```

   Feel free to add or remove utterances, but please keep it specific to the agent

6. Set up **Fulfillment** response<br/>
   - On successful fulfillment
     ```text
     Okay, transferring you to a human agent.
     ```
   - In case of failure
     ```text
     I'm sorry, but I couldn't connect you to a human agent. Please try again.
     ```

After creation, test your bot inside the AWS Lex UI and ensure that all basic and agent-related intents work as expected.

### 1.4 Collect Lex Bot Identifiers

Once your bot is ready, note the following identifiers:

- Bot name
- Bot ID
- Bot alias name
- Alias bot ID

You will enter these into your Webex Lex connector configuration.

### 1.5 IAM Policy and Permissions

To allow Lex and its integrations to function, attach these managed policies to your IAM user:

- AmazonLexFullAccess
- AmazonPollyReadOnlyAccess (required for text-to-speech features)​

For Bedrock/advanced integrations, you may to add extra policies. Please refer to this [documentation](https://docs.aws.amazon.com/lexv2/latest/dg/bedrock-agent-intent-permissions.html) to learn more.

### 1.6 Create access keys

1. Use your AWS account ID or account alias, your IAM user name, and your password to sign in to the [IAM console](https://console.aws.amazon.com/iam).

2. In the navigation bar on the upper right, choose your user name, and then choose **Security credentials**.

3. In the **Access keys** section, choose **Create access key**. If you already have two access keys, this button is deactivated and you must delete an access key before you can create a new one.

4. On the **Access key best practices & alternatives** page, choose your use case to learn about additional options which can help you avoid creating a long-term access key. If you determine that your use case still requires an access key, choose **Other** and then choose **Next**.

5. (Optional) Set a description tag value for the access key. This adds a tag key-value pair to your IAM user. This can help you identify and update access keys later. The tag key is set to the access key id. The tag value is set to the access key description that you specify. When you are finished, choose **Create access key**.

6. On the **Retrieve access keys** page, choose either **Show** to reveal the value of your user's secret access key, or **Download .csv file**. This is your only opportunity to save your secret access key. After you've saved your secret access key in a secure location, choose **Done**.

Please save this Access Key and Secret Access Key very safely.

---

## Step 2: Configuring the BYOVA Gateway

### 2.1 Clone and Set Up the Gateway

1. **Clone the Repository**
   ```bash
   git clone https://github.com/webex/webex-byova-gateway-python.git
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

### 2.2 Configure AWS Lex Connector

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
         # Initial trigger text sent when starting a conversation (default: "hello")
         # For Bedrock agents, use a simple greeting rather than a specific request
         # to avoid triggering function calls before the agent is ready
         initial_trigger_text: "hello"
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

### 2.3 Start the Gateway

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

## Step 3: Setting Up Your Webex Contact Center Sandbox

### 3.1 Request a Sandbox

1. **Sign in to Webex Developer Portal**
   - Go to [developer.webex.com](https://developer.webex.com)
   - Sign in with your Webex account

2. **Navigate to Contact Center Sandbox**
   - Go to [Contact Center Sandbox](/create/docs/sandbox_cc)
   - Click **"Request a Sandbox"**

3. **Complete the Request Process**
   - Read and accept the Terms and Conditions
   - Check "By creating this app, I accept the Terms of Service"
   - Click **"Request a Sandbox"**

4. **Wait for Provisioning**
   - Sandbox creation takes up to 15 minutes
   - You'll receive several emails with account details
   - **Save the final provisioning email** - it contains critical information

### 3.2 Access Your Sandbox

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

### 3.3 Access the Administrator Portal

1. **Open a Private/Incognito Browser Window**
   - Chrome: `Ctrl+Shift+N` (Windows) or `Cmd+Shift+N` (Mac)
   - Firefox: `Ctrl+Shift+P` (Windows) or `Cmd+Shift+P` (Mac)

2. **Navigate to the Administrator Portal**
   - Go to [https://admin.webex.com](https://admin.webex.com)
   - Enter your administrator email and password from the provisioning email

3. **Verify Access**
   - You should see the Webex Contact Center Administrator Portal
   - Note the site configuration and available features

### 3.4 Request the BYOVA Feature for your Sandbox

**NOTE:** Service apps created for "Voice Virtual Agent" will be disabled unless there is an active BYO Virtual Agent Subscription in a production organization. To request access for Voice Virtual Agent apps in Sandboxes, Gold Tenants, and EFT orgs, please reach out to [Developer Support](https://developer.webex.com/explore/support). Here are the steps to do so:

1. **Copy your Organization ID**
   - In the Administrator Portal, navigate to **Settings** → **Organization**
   - Copy the Organization ID

2. **Submit a Developer Support Ticket**
   - Go to the [Webex Developer Support](/support) page.
   - Click **"Contact Support"** and fill out the ticket.
     - Subject: Request to Enable BYOVA Feature for Webex Contact Center Sandbox
     - Description:
       - Hello Webex Developer Support Team,
       - I would like to request the activation of the **BYOVA (Bring Your Own Virtual Agent)** feature for my Webex Contact Center sandbox environment.
       - **Organization Name:** ACME Test Org
       - **Organization ID:** `your-organization-id-here`
       - **Sandbox Email Used for Request:** `admin@xxxxxx-xxxx.wbx.ai`
       - **Sandbox URL:** `https://xxxxxx-xxxx.webex.com`
       - This feature is required to continue development and testing for virtual agent integrations. Please let me know if you need any additional information.
   - Wait for confirmation from the support team. You'll receive an email when BYOVA is enabled for your org.
---

## Step 4: Configuring BYOVA and BYODS

### 4.1 Understanding BYOVA and BYODS

- **BYOVA (Bring Your Own Virtual Agent)**: Allows you to integrate external AI services as virtual agents
- **BYODS (Bring Your Own Data Source)**: Enables integration with external data sources for enhanced AI capabilities
  - BYOVA builds on top of the BYODS framework
  - Provides secure, standardized data exchange between Webex and third-party providers
  - Uses JWS (JSON Web Signature) tokens for authentication
  - Requires Service App creation and admin authorization

**Important**: BYOVA requires BYODS setup first, as the virtual agent configuration depends on having a registered data source.

### 4.2 Create a Service App for BYODS

Before configuring BYOVA, we need to set up a Service App for data source integration, as BYOVA builds on top of the BYODS (Bring Your Own Data Source) framework.

1. **Navigate to Webex Developer Portal**
   - Go to [developer.webex.com](https://developer.webex.com)
   - Sign in with your Webex account

2. **Create a New Service App**
   - Go to **My Apps** → **Create a New App**
   - Choose **Service App** as the application type

3. **Configure the Service App**
   - **App Name**: `BYOVA Gateway Service App` (or your preferred name)
   - **Icon**: Choose a suitable icon for your app or upload your own
   - **Description**: Enter a brief description of your app
   - **Contact Email**: Enter your admin email address
   - **Scopes**: Ensure you select:
     - `spark-admin:datasource_read`
     - `spark-admin:datasource_write`
   - **Domains**: Specify your public gateway domain (e.g., `your-domain.com` or `ngrok-free.app`)
     - Avoid registering ports in the domain - all ports will be accepted later
     - **For Testing with ngrok**: If you're using ngrok for testing, start it now (in a separate terminal):
       ```bash
       # Create public tunnel to the gRPC server
       ngrok http --upstream-protocol=http2 50051
       ```
       **Important**: Use the `--upstream-protocol=http2` flag as gRPC requires HTTP/2 protocol.
       
       Use the provided HTTPS URL (without the `https://` prefix, e.g., `abc123.ngrok-free.app`)
     - **For Production**: Use your planned production domain or IP address from the Prerequisites
   - **Data Exchange Schema**: Select `VA_service_schema` for voice virtual agent interactions
     - This schema (ID: `5397013b-7920-4ffc-807c-e8a3e0a18f43`) is specifically designed for voice virtual agent services
     - Reference: [VoiceVirtualAgent Schema](https://github.com/webex/dataSourceSchemas/tree/v1.10/Services/VoiceVirtualAgent/5397013b-7920-4ffc-807c-e8a3e0a18f43)
   
   - Complete any other required information

4. **Save the Service App Client ID and Client Secret**
   - Under **Authentication**, locate the **Client ID** and **Client Secret**
   - Save these credentials for later use

5. **Submit for Admin Approval**
   - In your sandbox, select **"Request Admin Approval"**
   - This makes the Service App visible in Control Hub for admin authorization

### 4.3 Register Your Data Source

1. **Get Admin Authorization**
   - In Control Hub (admin.webex.com), navigate to **Apps** → **Service Apps**
   - Find your Service App and click **"Authorize"**
   - This generates org-specific access and refresh tokens

2. **Get Service App Token**
   - After admin approval, return to [developer.webex.com](https://developer.webex.com)
   - Go to **My Apps** and select your Service App
   - Under **Org Authorizations**, locate your org in the list and select it
   - Paste the **Client Secret** from step 1 into the **Client Secret** field and click **"Generate Tokens"**
   - Save the returned `access_token` - you'll need it to register your data source
   - Note: Tokens expire and will need to be refreshed using the refresh token provided

3. **Register the Data Source**
   - Use the access token from step 1 to register your data source
   - Make a POST request to `/v1/datasources` with the following payload:
   - **API Reference**: [Register a Data Source](/admin/docs/api/v1/data-sources/register-a-data-source)

   ```json
   {
     "schemaId": "5397013b-7920-4ffc-807c-e8a3e0a18f43",
     "url": "https://your-gateway-ip:50051",
     "audience": "BYOVAGateway",
     "subject": "callAudioData",
     "nonce": "123456",
     "tokenLifetimeMinutes": "1440"
   }
   ```

   - **Important**: Replace `your-gateway-ip` with your actual gateway URL:
     - **For Testing with ngrok**: Use your ngrok URL (e.g., `https://abc123.ngrok-free.app:50051`)
     - **For Production**: Use your production domain or public IP address (e.g., `https://gateway.yourdomain.com:50051`)
   - Save the data source ID for later use

**Reference**: For detailed BYODS setup instructions, see the [Bring Your Own Data Source documentation](/create/docs/bring-your-own-datasource).

### 4.4 Configure BYOVA Virtual Agent

1. **Navigate to Virtual Agents**
   - In Control Hub, go to **Contact Center** → **Integrations** → **Features**
   - Click **"Create Feature"**

2. **Configure Virtual Agent Settings**
   - **Name**: `AWS Lex Virtual Agent`
   - **Type of Connector**: Select **"Service App"**
   - **Authorized Service App**: Select your Service App from step 4.2
   - **Resource Identifier**: Enter the datasource ID you saved in step 4.3
   - Click **"Create"**

### 4.5 Import the BYOVA Flow Template


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
   - Download the [`BYOVA_Gateway_Flow.json`](https://github.com/Webex/webex-byova-gateway-python/blob/main/BYOVA_Gateway_Flow.json) file from the gateway repository 
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

### 4.6 Assign Flow to Entry Point

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

## Step 5: Testing Your Integration

### 5.1 Set Up Agent Desktop

1. **Install Webex Contact Center Desktop**
   - Download from the Administrator Portal
   - Install on a test machine

2. **Log in as Agent**
   - Use the Premium Agent credentials from your provisioning email
   - Enter the extension number (1001)

3. **Set Agent Status to Available**
   - Ensure the agent is ready to receive calls

### 5.2 Test the Voice AI Integration

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

### 5.3 Monitor the Integration

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


1. **Add Advanced Features**
   - Implement sentiment analysis
   - Add multi-language support
   - Integrate with CRM systems

2. **Scale Your Solution**
   - Deploy to production AWS environment
   - Implement load balancing
   - Add monitoring and alerting

3.. **Customize the Gateway**
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

- [AWS Lex Developer Guide](https://docs.aws.amazon.com/lex/)
- [BYOVA Gateway Repository](https://github.com/webex/webex-byova-gateway-python)
- [Webex Contact Center Sandbox](/create/docs/sandbox_cc)

### Support

For questions about this integration:
- Check the troubleshooting section above
- Review the gateway logs and monitoring interface
- Consult the AWS Lex and Webex Contact Center documentation
- Reach out to the developer community for assistance

Happy building! 🚀

---

*This guide provides a comprehensive walkthrough for integrating AWS Lex with Webex Contact Center using the BYOVA Gateway. The setup process is designed to be developer-friendly while following enterprise best practices for security and scalability.*
