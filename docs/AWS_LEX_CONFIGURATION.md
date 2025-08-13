# AWS Lex Connector Configuration

The AWS Lex connector integrates with AWS Lex v2 bots to provide virtual agent capabilities.

## Configuration Options

### Required
- **`region_name`**: AWS region where your Lex bots are located

### Optional
- **`bot_alias_id`**: Bot alias ID (default: TSTALIASID)
- **`aws_access_key_id`**: Explicit AWS access key
- **`aws_secret_access_key`**: Explicit AWS secret key

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
    bot_alias_id: "TSTALIASID"
  agents: []
```

## Bot Alias

A bot alias points to a specific version of your bot. Common aliases:
- **TSTALIASID**: Default test alias
- **PRODALIASID**: Production alias
- **Custom aliases**: Any alias you create

The connector now makes this configurable instead of hardcoded.

## Why WAV Conversion is Always Enabled

WxCC **always** requires:
- Complete WAV files with headers (not raw PCM data)
- 8kHz sample rate (avoids 5-second delays)
- 8-bit u-law encoding (WxCC requirement)

Since AWS Lex **always** returns raw PCM data, conversion to WAV is mandatory for compatibility.
