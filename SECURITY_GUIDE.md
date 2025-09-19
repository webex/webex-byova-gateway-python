# Security Guide for BYOVA Gateway Docker Deployment

This guide covers security best practices for handling environment variables, AWS credentials, and sensitive configuration in Docker deployments.

## 🔐 Environment Variable Security

### 1. Local Development

#### Option A: .env File (Recommended for Development)
```bash
# Copy the template
cp env.example .env

# Edit with your credentials
nano .env
```

**Security Notes:**
- ✅ `.env` is in `.gitignore` (won't be committed)
- ✅ Use for local development only
- ❌ Never commit `.env` files to version control

#### Option B: AWS Credentials Directory
```bash
# Mount your local AWS credentials
docker-compose up -d
```

**Security Notes:**
- ✅ Uses existing AWS CLI credentials
- ✅ No need to store credentials in files
- ✅ Works with AWS SSO and temporary credentials

### 2. Production Deployment

#### Option A: IAM Roles (Recommended for AWS ECS)
```yaml
# In ECS Task Definition
taskRoleArn: "arn:aws:iam::ACCOUNT:role/ecsTaskRole"
executionRoleArn: "arn:aws:iam::ACCOUNT:role/ecsTaskExecutionRole"
```

**Benefits:**
- ✅ No credentials in environment variables
- ✅ Automatic credential rotation
- ✅ Fine-grained permissions
- ✅ Audit trail through CloudTrail

#### Option B: AWS Secrets Manager
```yaml
# In ECS Task Definition
secrets:
  - name: "AWS_ACCESS_KEY_ID"
    valueFrom: "arn:aws:secretsmanager:region:account:secret:byova-gateway/aws-credentials"
  - name: "AWS_SECRET_ACCESS_KEY"
    valueFrom: "arn:aws:secretsmanager:region:account:secret:byova-gateway/aws-credentials"
```

**Benefits:**
- ✅ Encrypted at rest
- ✅ Automatic rotation
- ✅ Fine-grained access control
- ✅ Audit logging

#### Option C: Environment Variables (Less Secure)
```yaml
# In ECS Task Definition
environment:
  - name: "AWS_ACCESS_KEY_ID"
    value: "AKIA..."
  - name: "AWS_SECRET_ACCESS_KEY"
    value: "secret..."
```

**Security Concerns:**
- ❌ Visible in ECS console
- ❌ Stored in plain text
- ❌ No automatic rotation
- ❌ Hard to audit

## 🛡️ Security Best Practices

### 1. Credential Management

#### For Development:
```bash
# Use AWS CLI profiles
aws configure --profile byova-dev
export AWS_PROFILE=byova-dev

# Or use temporary credentials
aws sts assume-role --role-arn arn:aws:iam::ACCOUNT:role/ByovaGatewayRole --role-session-name byova-session
```

#### For Production:
```bash
# Use IAM roles with least privilege
# Create specific roles for the gateway
aws iam create-role --role-name ByovaGatewayRole --assume-role-policy-document file://trust-policy.json
```

### 2. Network Security

#### Docker Compose (Local):
```yaml
services:
  byova-gateway:
    networks:
      - byova-network
    ports:
      - "127.0.0.1:50051:50051"  # Bind to localhost only
      - "127.0.0.1:8080:8080"

networks:
  byova-network:
    driver: bridge
    internal: true  # No external access
```

#### ECS (Production):
```yaml
# Use private subnets
networkConfiguration:
  awsvpcConfiguration:
    subnets:
      - subnet-12345678  # Private subnet
    securityGroups:
      - sg-12345678      # Restrictive security group
    assignPublicIp: DISABLED
```

### 3. Container Security

#### Non-Root User:
```dockerfile
# Already implemented in Dockerfile
RUN useradd --create-home --shell /bin/bash appuser
USER appuser
```

#### Resource Limits:
```yaml
# In docker-compose.prod.yml
deploy:
  resources:
    limits:
      memory: 1G
      cpus: '0.5'
```

#### Read-Only Filesystem:
```dockerfile
# Add to Dockerfile for production
RUN mkdir -p /tmp /app/logs
VOLUME ["/tmp", "/app/logs"]
```

### 4. Configuration Security

#### Environment Variable Validation:
```python
# Add to main.py
import os

def validate_required_env_vars():
    required_vars = ['AWS_REGION']
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise ValueError(f"Missing required environment variables: {missing}")
```

#### Sensitive Data Masking:
```python
# In logging configuration
import logging

class SensitiveFormatter(logging.Formatter):
    def format(self, record):
        # Mask sensitive data in logs
        msg = super().format(record)
        msg = re.sub(r'AWS_SECRET_ACCESS_KEY=[^\s]+', 'AWS_SECRET_ACCESS_KEY=***', msg)
        return msg
```

## 🔧 Implementation Examples

### 1. Local Development Setup

```bash
# 1. Copy environment template
cp env.example .env

# 2. Edit with your values
nano .env

# 3. Start with environment variables
./docker-dev.sh start
```

### 2. AWS ECS with IAM Roles

```bash
# 1. Create IAM role
aws iam create-role --role-name ByovaGatewayRole

# 2. Attach policies
aws iam attach-role-policy --role-name ByovaGatewayRole --policy-arn arn:aws:iam::aws:policy/AmazonLexFullAccess

# 3. Update ECS task definition
# Use the role ARN in taskRoleArn
```

### 3. AWS ECS with Secrets Manager

```bash
# 1. Store credentials in Secrets Manager
aws secretsmanager create-secret \
  --name "byova-gateway/aws-credentials" \
  --secret-string '{"aws_access_key_id":"AKIA...","aws_secret_access_key":"..."}'

# 2. Update ECS task definition
# Reference the secret ARN in secrets section
```

## 🚨 Security Checklist

### Before Deployment:
- [ ] Remove hardcoded credentials from code
- [ ] Use IAM roles or Secrets Manager
- [ ] Enable CloudTrail logging
- [ ] Set up VPC with private subnets
- [ ] Configure security groups with minimal access
- [ ] Enable container image scanning
- [ ] Set up log monitoring and alerting
- [ ] Test credential rotation
- [ ] Verify network isolation
- [ ] Review IAM permissions (least privilege)

### During Deployment:
- [ ] Monitor for credential exposure in logs
- [ ] Verify network connectivity
- [ ] Test health checks
- [ ] Validate configuration processing
- [ ] Check container security scanning results

### After Deployment:
- [ ] Monitor access logs
- [ ] Review CloudTrail events
- [ ] Test credential rotation
- [ ] Verify security group rules
- [ ] Check for security updates
- [ ] Monitor resource usage

## 🔍 Troubleshooting Security Issues

### Common Issues:

1. **Credentials not found:**
   ```bash
   # Check if credentials are loaded
   docker-compose exec byova-gateway env | grep AWS
   ```

2. **Permission denied:**
   ```bash
   # Check IAM role permissions
   aws sts get-caller-identity
   ```

3. **Network connectivity:**
   ```bash
   # Test from container
   docker-compose exec byova-gateway curl -I https://lex.us-east-1.amazonaws.com
   ```

### Security Monitoring:

```bash
# Check for exposed credentials in logs
docker-compose logs | grep -i "secret\|key\|password"

# Monitor AWS API calls
aws logs filter-log-events --log-group-name /aws/ecs/byova-gateway --filter-pattern "ERROR"
```

## 📚 Additional Resources

- [AWS IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [Docker Security Best Practices](https://docs.docker.com/develop/security-best-practices/)
- [AWS ECS Security](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/security.html)
- [AWS Secrets Manager](https://docs.aws.amazon.com/secretsmanager/)
- [OWASP Docker Security](https://owasp.org/www-project-docker-security/)





