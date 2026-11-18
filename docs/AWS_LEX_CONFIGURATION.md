# AWS Lex Connector Configuration

The AWS Lex connector integrates with AWS Lex v2 bots to provide virtual agent capabilities.

If you have a Webex Contact Center sandbox but have not selected a voice-agent
provider, start with the [Local Audio Connector Configuration](LOCAL_AUDIO_CONFIGURATION.md)
guide instead. It validates the vendor-neutral BYOVA path without an AWS account.

## Configuration Options

### Required
- **`region_name`**: AWS region where your Lex bots are located

### Optional
- **`initial_trigger_text`**: Text sent when starting a conversation (default: "hello")
  - For Bedrock agents, use a simple greeting to avoid triggering function calls prematurely
- **`barge_in_enabled`**: Allow users to interrupt bot responses (default: false)

### AWS Credentials
**IMPORTANT**: AWS credentials are NOT configured in config files for security reasons. Use one of these methods instead:
- **Environment variables**: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
- **AWS credentials file**: `~/.aws/credentials`
- **IAM roles**: Attach IAM roles to your EC2, ECS, or Lambda resources (recommended for production)
- **AWS SSO**: If configured

### Audio Format
- **WAV conversion is always enabled** - WxCC requires WAV format with proper headers
- **Automatic conversion** from AWS Lex's 16kHz PCM to 8kHz u-law WAV

## Example Configuration

```yaml
aws_lex_connector:
  type: "aws_lex_connector"
  class: "AWSLexConnector"
  module: "connectors.aws_lex_connector"
  config:
    region_name: "us-east-1"
    # Note: Bot aliases are discovered automatically
    initial_trigger_text: "hello"  # Text sent when starting conversation
    barge_in_enabled: false
  agents: []
```

## Separate WebSocket Adapter

Use `AWSLexWebSocketConnector` for the WxCC WebSocket listener. The existing
`AWSLexConnector` keeps its gRPC-only default. Both use the AWS credential chain
and share bot discovery, session handling, audio conversion and Lex API calls.

Under `connectors` in the gateway configuration, add:

```yaml
aws_lex_websocket_connector:
  type: "aws_lex_websocket_connector"
  class: "AWSLexWebSocketConnector"
  module: "connectors.aws_lex_websocket_connector"
  supported_transports: ["websocket"]
  config:
    region_name: "us-east-1"
    initial_trigger_text: "hello"
    barge_in_enabled: false
    audio_logging:
      enabled: false
```

Enable `transports.mode: websocket` or `both`, with the independent WebSocket
datasource and JWT profile described in [WebSocket transport setup](WEBSOCKET_TRANSPORT.md).
Select `aws_lex_websocket_connector: <Bot Name>` in WxCC. The gRPC catalog retains
`aws_lex_connector: <Bot Name>`, so loading both adapters does not replace an
existing agent mapping. Each adapter owns its conversation state.

The WebSocket hop is **WxCC to gateway**. The AWS hop uses the existing
`RecognizeUtterance` calls: caller audio is buffered until the gateway detects
the end of speech, and each Lex response is sent as one complete WAV in a
`FINAL` response. This is not a native Lex WebSocket or `StartConversation`
implementation. AWS documents its bidirectional streaming protocol as
[HTTP/2](https://docs.aws.amazon.com/lexv2/latest/dg/streaming.html).
The WebSocket adapter requests up to ten DTMF digits, a five-second inter-digit
timeout and `#` termination, including after each response turn.

Local socket tests cover discovery isolation, welcome and voice responses,
DTMF symbols including `0`, `*` and `#`, and disconnect cleanup with a mocked
AWS SDK. Real WxCC-to-Lex calls remain a separate live acceptance check. Do not
infer that Lex has passed live validation from Local Audio or GECX results.

### SDK Baseline

The AWS runtime requirements now require Boto3 and Botocore `>=1.43.114`, with
S3Transfer `>=0.19.2`. Both adapters were locally tested on Python 3.12 with
those exact versions, including Botocore Stubber validation of the discovery
and `RecognizeUtterance` request shapes. No live AWS calls are made by those tests.
Use the resolver to keep the AWS packages compatible; do not upgrade Botocore
independently outside Boto3's supported range. See the
[Boto3 release](https://pypi.org/project/boto3/1.43.114/) and
[Botocore release](https://pypi.org/project/botocore/1.43.114/).

## Bot Alias Discovery

Bot aliases are **discovered automatically** by the connector:
- The connector queries AWS Lex for all available bots in the configured region
- For each bot, it discovers all available aliases
- The **most recent alias** (by last updated date) is automatically selected for each bot
- WxCC administrators select which bot to route calls to on the WxCC side

This eliminates the need for manual alias configuration and ensures the connector always uses the latest bot version.

## Required AWS IAM Permissions

The AWS Lex connector requires specific IAM permissions to function properly. Ensure your AWS credentials have the following permissions:

### Minimum Required Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "lex:ListBots",
        "lex:ListBotAliases",
        "lex:RecognizeUtterance",
        "lex:RecognizeText"
      ],
      "Resource": "*"
    }
  ]
}
```

### Permission Details

| Permission | Purpose | Required |
|------------|---------|----------|
| `lex:ListBots` | Discover available bots in the configured region | Yes |
| `lex:ListBotAliases` | Discover bot aliases for automatic selection | Yes |
| `lex:RecognizeUtterance` | Send audio/text to bots and receive responses | Yes |
| `lex:RecognizeText` | Process text-based interactions | Yes |

### Using Managed Policies

Alternatively, you can use the AWS managed policy **AmazonLexFullAccess**, which includes all necessary permissions:

```bash
# Attach managed policy to an IAM user
aws iam attach-user-policy \
  --user-name your-username \
  --policy-arn arn:aws:iam::aws:policy/AmazonLexFullAccess
```

### Troubleshooting Permission Issues

If you encounter permission errors:

1. **"AccessDeniedException" when starting the connector**
   - Ensure your credentials have `lex:ListBots` permission

2. **Bots not appearing in the available agents list**
   - Verify your credentials have `lex:ListBotAliases` permission
   - Check that bots exist in the configured region

3. **Conversation fails to start**
   - Confirm `lex:RecognizeUtterance` permission is granted
   - Verify the bot has at least one published alias

### Using IAM Roles (Recommended for Production)

For production deployments, use IAM roles instead of access keys:

1. Create an IAM role with the required Lex permissions
2. Attach the role to your EC2 instance, ECS task, or Lambda function
3. The AWS SDK will automatically use the role credentials

### Using Environment Variables (For Development)

For local development, set environment variables:

```bash
export AWS_ACCESS_KEY_ID=your_access_key_id
export AWS_SECRET_ACCESS_KEY=your_secret_access_key
export AWS_DEFAULT_REGION=us-east-1
```

Or configure AWS CLI:

```bash
aws configure
```

## Why WAV Conversion is Always Enabled

WxCC **always** requires:
- Complete WAV files with headers (not raw PCM data)
- 8kHz sample rate (avoids 5-second delays)
- 8-bit u-law encoding (WxCC requirement)

Since AWS Lex **always** returns raw PCM data, conversion to WAV is mandatory for compatibility.
