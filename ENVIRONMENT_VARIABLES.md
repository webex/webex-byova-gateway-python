# Environment Variables Guide

This guide explains how to configure the BYOVA Gateway using environment variables for different deployment scenarios.

## 📋 Available Environment Variables

### AWS Configuration
| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `AWS_REGION` | AWS region for services | `us-east-1` | Yes |
| `AWS_ACCESS_KEY_ID` | AWS access key ID | - | For local dev |
| `AWS_SECRET_ACCESS_KEY` | AWS secret access key | - | For local dev |
| `AWS_SESSION_TOKEN` | AWS session token (for temporary credentials) | - | Optional |
| `AWS_PROFILE` | AWS CLI profile name | - | Optional |

### AWS Lex Configuration
| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `AWS_LEX_BOT_ALIAS_ID` | Lex bot alias ID | `TSTALIASID` | Yes |
| `AWS_LEX_BOT_NAME` | Lex bot name | - | Optional |
| `AWS_LEX_LOCALE` | Lex bot locale | `en_US` | Optional |

### Gateway Configuration
| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `GATEWAY_HOST` | gRPC server host | `0.0.0.0` | No |
| `GATEWAY_PORT` | gRPC server port | `50051` | No |
| `MONITORING_HOST` | Web UI host | `0.0.0.0` | No |
| `MONITORING_PORT` | Web UI port | `8080` | No |

### Logging Configuration
| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` | No |
| `LOG_FILE` | Log file path | `/app/logs/gateway.log` | No |

### Security (Production)
| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `JWT_SECRET` | JWT secret for authentication | - | Optional |
| `ENCRYPTION_KEY` | Encryption key for sensitive data | - | Optional |

## 🚀 Usage Examples

### 1. Local Development with .env File

Create a `.env` file in the project root:

```bash
# Copy the template
cp env.example .env

# Edit with your values
nano .env
```

Example `.env` file:
```bash
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIA1234567890ABCDEF
AWS_SECRET_ACCESS_KEY=your_secret_key_here

# AWS Lex Configuration
AWS_LEX_BOT_ALIAS_ID=TSTALIASID
AWS_LEX_BOT_NAME=MyBot
AWS_LEX_LOCALE=en_US

# Gateway Configuration
GATEWAY_HOST=0.0.0.0
GATEWAY_PORT=50051
MONITORING_HOST=0.0.0.0
MONITORING_PORT=8080

# Logging
LOG_LEVEL=INFO
```

### 2. Local Development with AWS CLI

If you have AWS CLI configured:

```bash
# No .env file needed - uses AWS CLI credentials
./docker-dev.sh start
```

The container will automatically use your AWS CLI credentials from `~/.aws/`.

### 3. Docker Run with Environment Variables

```bash
docker run -d \
  --name byova-gateway \
  -p 50051:50051 \
  -p 8080:8080 \
  -e AWS_REGION=us-east-1 \
  -e AWS_ACCESS_KEY_ID=AKIA1234567890ABCDEF \
  -e AWS_SECRET_ACCESS_KEY=your_secret_key \
  -e AWS_LEX_BOT_ALIAS_ID=TSTALIASID \
  -e LOG_LEVEL=INFO \
  webex-byova-gateway-python-byova-gateway:latest
```

### 4. Docker Compose with Environment Variables

```yaml
# docker-compose.override.yml
services:
  byova-gateway:
    environment:
      - AWS_REGION=us-east-1
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
      - AWS_LEX_BOT_ALIAS_ID=TSTALIASID
      - LOG_LEVEL=DEBUG
```

### 5. AWS ECS with IAM Roles (Recommended for Production)

```json
{
  "taskDefinition": {
    "taskRoleArn": "arn:aws:iam::123456789012:role/ByovaGatewayRole",
    "executionRoleArn": "arn:aws:iam::123456789012:role/ecsTaskExecutionRole",
    "containerDefinitions": [
      {
        "environment": [
          {
            "name": "AWS_REGION",
            "value": "us-east-1"
          },
          {
            "name": "AWS_LEX_BOT_ALIAS_ID",
            "value": "TSTALIASID"
          }
        ]
      }
    ]
  }
}
```

### 6. AWS ECS with Secrets Manager

```json
{
  "containerDefinitions": [
    {
      "secrets": [
        {
          "name": "AWS_ACCESS_KEY_ID",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:byova-gateway/aws-credentials:AWS_ACCESS_KEY_ID::"
        },
        {
          "name": "AWS_SECRET_ACCESS_KEY",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:byova-gateway/aws-credentials:AWS_SECRET_ACCESS_KEY::"
        }
      ],
      "environment": [
        {
          "name": "AWS_REGION",
          "value": "us-east-1"
        }
      ]
    }
  ]
}
```

## 🔧 Configuration Processing

The gateway automatically processes environment variables in configuration files:

### Template Processing
The `config/config.template.yaml` file supports environment variable substitution:

```yaml
# Template file
gateway:
  host: "${GATEWAY_HOST:-0.0.0.0}"
  port: ${GATEWAY_PORT:-50051}

connectors:
  aws_lex_connector:
    config:
      region_name: "${AWS_REGION:-us-east-1}"
      bot_alias_id: "${AWS_LEX_BOT_ALIAS_ID:-TSTALIASID}"
```

### Automatic Processing
The Docker container automatically processes the template:

```bash
# Inside container startup
envsubst < config/config.template.yaml > config/config.yaml
```

## 🛠️ Development Workflow

### 1. Quick Start
```bash
# Copy environment template
cp env.example .env

# Edit with your values
nano .env

# Start the gateway
./docker-dev.sh start
```

### 2. Using AWS CLI
```bash
# Configure AWS CLI
aws configure

# Start without .env file
./docker-dev.sh start
```

### 3. Testing Different Configurations
```bash
# Test with different log level
LOG_LEVEL=DEBUG ./docker-dev.sh start

# Test with different region
AWS_REGION=eu-west-1 ./docker-dev.sh start
```

## 🔍 Troubleshooting

### Check Environment Variables
```bash
# Check if variables are loaded
docker-compose exec byova-gateway env | grep AWS

# Check processed configuration
docker-compose exec byova-gateway cat config/config.yaml
```

### Common Issues

1. **Missing AWS credentials:**
   ```bash
   # Error: Unable to locate credentials
   # Solution: Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
   ```

2. **Invalid region:**
   ```bash
   # Error: Invalid region
   # Solution: Set AWS_REGION to a valid region (e.g., us-east-1)
   ```

3. **Configuration not processed:**
   ```bash
   # Check if template exists
   ls -la config/config.template.yaml
   
   # Check if envsubst is available
   docker-compose exec byova-gateway which envsubst
   ```

### Validation
```bash
# Validate environment variables
./scripts/process-env.sh

# Check gateway status
curl http://localhost:8080/api/status
```

## 📚 Best Practices

### Security
- ✅ Use IAM roles in production
- ✅ Never commit `.env` files
- ✅ Use Secrets Manager for sensitive data
- ✅ Rotate credentials regularly
- ❌ Don't hardcode credentials in code

### Development
- ✅ Use `.env` files for local development
- ✅ Use AWS CLI profiles when possible
- ✅ Test with different configurations
- ✅ Validate environment variables

### Production
- ✅ Use IAM roles with least privilege
- ✅ Enable CloudTrail logging
- ✅ Use private subnets
- ✅ Implement monitoring and alerting



