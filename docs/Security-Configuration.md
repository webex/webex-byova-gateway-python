# Security Configuration

This document provides recommended security configurations for the BYOVA Gateway. The steps below are specific to the AWS Cloud Provider, but represent recommended security implementations for any platform hosting the BYOVA Gateway.

## Table of Contents

1. [HTTPS Configuration for Web Monitor](#https-configuration-for-web-monitor)
   - [Prerequisites](#web-monitor-prerequisites)
   - [SSL Certificate Setup](#web-monitor-ssl-certificate-setup)
   - [Create Target Group](#web-monitor-target-group)
   - [Create Load Balancer](#web-monitor-load-balancer)
   - [Configure HTTPS Listener](#web-monitor-https-listener)
   - [Security Groups](#web-monitor-security-groups)
   - [Verification](#web-monitor-verification)

2. [gRPC TLS Termination Setup](#grpc-tls-termination-setup)
   - [Prerequisites](#grpc-prerequisites)
   - [Create gRPC Target Group](#grpc-target-group)
   - [Add gRPC Listener](#grpc-listener)
   - [Configure Security Groups](#grpc-security-groups)
   - [Verification](#grpc-verification)

---

# HTTPS Configuration for Web Monitor

This section configures HTTPS for the web monitoring interface (port 8080) with HTTP to HTTPS redirect.

## Web Monitor Prerequisites

- AWS CLI configured with appropriate permissions
- SSL/TLS certificate in AWS Certificate Manager (ACM)
- VPC and subnets configured
- Security groups allowing inbound traffic on ports 80, 443, and 8080

## Web Monitor SSL Certificate Setup

### Option A: Request Certificate via ACM (Recommended)

```bash
# Request a certificate via ACM (replace with your domain)
aws acm request-certificate \
  --domain-name your-domain.com \
  --subject-alternative-names "*.your-domain.com" \
  --validation-method DNS \
  --region us-east-1
```

### Option B: Import Your Own Certificate (BYOC)

If you have existing certificates from a third-party CA or internal PKI:

#### Prerequisites for BYOC
- Certificate file (PEM format)
- Private key file (PEM format)
- Certificate chain file (PEM format, optional but recommended)

#### Import Certificate to ACM

```bash
# Import your certificate to ACM
aws acm import-certificate \
  --certificate fileb://certificate.pem \
  --private-key fileb://private-key.pem \
  --certificate-chain fileb://certificate-chain.pem \
  --region us-east-1
```

#### Certificate File Preparation

**Certificate Format (certificate.pem)**:
```
-----BEGIN CERTIFICATE-----
MIIDXTCCAkWgAwIBAgIJAKoK/heBjcOuMA0GCSqGSIb3DQEBBQUAMEUxCzAJBgNV
BAYTAkFVMRMwEQYDVQQIDApTb21lLVN0YXRlMSEwHwYDVQQKDBhJbnRlcm5ldCBX
aWRnaXRzIFB0eSBMdGQwHhcNMTMwOTI5MTQwNjIyWhcNMjMwOTI3MTQwNjIyWjBF
MQswCQYDVQQGEwJBVTETMBEGA1UECAwKU29tZS1TdGF0ZTEhMB8GA1UECgwYSW50
ZXJuZXQgV2lkZ2l0cyBQdHkgTHRkMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIB
CgKCAQEAwuqTiuGqkIX7/y4fNDGDNvXfObgWrVzaATuL0mxjxjBJ...
-----END CERTIFICATE-----
```

**Private Key Format (private-key.pem)**:
```
-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDC6pOK4aqQhfv/
Lh80MYM29d85uBatXNoBOvSbGPGMEkmPiIrXZcZvLVPGahZNUtFJrBvftJ+urpH
MYFrcMiMLXB40kecwCDfAHrhY3ePqifsVqAC5CcupccfNUX5E4K99H/zbr8RB77
AdFiIN6yjOHGU1Z4ykUKrUYtwqED93jx6uy2wc6w8CgWINiDZuFAOisPL4WQQgqV
WFXA+IkU3oPwIrCrTQtO7zQAHxLkiQIDAQABAoIBABd0Ov7+QQynbqHiuIqbw
...
-----END PRIVATE KEY-----
```

**Certificate Chain Format (certificate-chain.pem)**:
```
-----BEGIN CERTIFICATE-----
[Intermediate CA Certificate]
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
[Root CA Certificate]
-----END CERTIFICATE-----
```

#### Verify Imported Certificate

```bash
# List certificates to get the ARN
aws acm list-certificates --region us-east-1

# Describe the imported certificate
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-east-1:account:certificate/xxxxx
```

#### Certificate Renewal for BYOC

**Important**: Imported certificates do NOT auto-renew. You must:

1. **Monitor expiration dates**:
```bash
# Check certificate expiration
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-east-1:account:certificate/xxxxx \
  --query 'Certificate.NotAfter'
```

2. **Set up renewal alerts**:
```bash
# Create CloudWatch alarm for certificate expiration
aws cloudwatch put-metric-alarm \
  --alarm-name "Certificate-Expiration-Warning" \
  --alarm-description "Certificate expires in 30 days" \
  --metric-name DaysToExpiry \
  --namespace AWS/CertificateManager \
  --statistic Minimum \
  --period 86400 \
  --threshold 30 \
  --comparison-operator LessThanThreshold \
  --dimensions Name=CertificateArn,Value=arn:aws:acm:us-east-1:account:certificate/xxxxx
```

3. **Update certificate before expiration**:
```bash
# Import renewed certificate (same command as initial import)
aws acm import-certificate \
  --certificate-arn arn:aws:acm:us-east-1:account:certificate/xxxxx \
  --certificate fileb://new-certificate.pem \
  --private-key fileb://new-private-key.pem \
  --certificate-chain fileb://new-certificate-chain.pem
```

## Web Monitor Target Group

```bash
aws elbv2 create-target-group \
  --name byova-web-monitor-tg \
  --protocol HTTP \
  --port 8080 \
  --vpc-id vpc-xxxxxxxxx \
  --health-check-path /health \
  --health-check-protocol HTTP \
  --health-check-port 8080 \
  --target-type ip
```

## Web Monitor Load Balancer

```bash
aws elbv2 create-load-balancer \
  --name byova-web-monitor-alb \
  --subnets subnet-xxxxxxxxx subnet-yyyyyyyyy \
  --security-groups sg-xxxxxxxxx \
  --scheme internet-facing \
  --type application \
  --ip-address-type ipv4
```

## Web Monitor HTTPS Listener

### HTTP Redirect Listener (Port 80)
```bash
aws elbv2 create-listener \
  --load-balancer-arn arn:aws:elasticloadbalancing:region:account:loadbalancer/app/byova-web-monitor-alb/xxxxx \
  --protocol HTTP \
  --port 80 \
  --default-actions Type=redirect,RedirectConfig='{Protocol=HTTPS,Port=443,StatusCode=HTTP_301}'
```

### HTTPS Listener (Port 443)
```bash
aws elbv2 create-listener \
  --load-balancer-arn arn:aws:elasticloadbalancing:region:account:loadbalancer/app/byova-web-monitor-alb/xxxxx \
  --protocol HTTPS \
  --port 443 \
  --certificates CertificateArn=arn:aws:acm:region:account:certificate/xxxxx \
  --ssl-policy ELBSecurityPolicy-TLS13-1-2-Res-2021-06 \
  --default-actions Type=forward,TargetGroupArn=arn:aws:elasticloadbalancing:region:account:targetgroup/byova-web-monitor-tg/xxxxx
```

## Web Monitor Security Groups

### ALB Security Group
```bash
# Allow HTTP traffic on port 80 (for redirect)
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxxx \
  --protocol tcp \
  --port 80 \
  --cidr 0.0.0.0/0

# Allow HTTPS traffic on port 443
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxxx \
  --protocol tcp \
  --port 443 \
  --cidr 0.0.0.0/0

# Allow ALB to reach backend on port 8080
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxxx \
  --protocol tcp \
  --port 8080 \
  --cidr 0.0.0.0/0
```

### Backend Service Security Group
```bash
# Allow HTTP traffic from ALB to port 8080
aws ec2 authorize-security-group-ingress \
  --group-id sg-backend-xxxxx \
  --protocol tcp \
  --port 8080 \
  --source-group sg-xxxxxxxxx
```

## Register Targets

```bash
# Register ECS service or EC2 instances with target group
aws elbv2 register-targets \
  --target-group-arn arn:aws:elasticloadbalancing:region:account:targetgroup/byova-web-monitor-tg/xxxxx \
  --targets Id=10.0.1.100,Port=8080
```

## Web Monitor Verification

```bash
# Test HTTP to HTTPS redirect
curl -I http://your-domain.com
# Should return: HTTP/1.1 301 Moved Permanently

# Test HTTPS endpoints
curl -k https://your-domain.com/api/status
curl -k https://your-domain.com/health
```

---

# gRPC TLS Termination Setup

This section configures TLS termination for the gRPC service (port 50051) using the existing ALB infrastructure.

## gRPC Prerequisites

- Existing ALB with SSL certificate configured (from Web Monitor setup above)
- gRPC service running on port 50051
- Target group for gRPC backend services

## gRPC Target Group

```bash
# Create target group for gRPC service
aws elbv2 create-target-group \
  --name byova-grpc-tg \
  --protocol HTTP \
  --port 50051 \
  --vpc-id vpc-xxxxxxxxx \
  --health-check-path /grpc.health.v1.Health/Check \
  --health-check-protocol HTTP \
  --health-check-port 50051 \
  --target-type ip \
  --protocol-version GRPC
```

## gRPC Listener

**Note**: Webex Contact Center sends all gRPC traffic on port 443 by default. Use path-based routing to separate gRPC from web traffic.

```bash
# Add path-based routing rule for VoiceVirtualAgent service
aws elbv2 create-rule \
  --listener-arn arn:aws:elasticloadbalancing:region:account:listener/app/byova-gateway-alb/xxxxx/xxxxx \
  --priority 100 \
  --conditions Field=path-pattern,Values='/com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent/*' \
  --actions Type=forward,TargetGroupArn=arn:aws:elasticloadbalancing:region:account:targetgroup/byova-grpc-tg/xxxxx

# Optional: Add path-based routing rule for gRPC health check service (for external testing)
aws elbv2 create-rule \
  --listener-arn arn:aws:elasticloadbalancing:region:account:listener/app/byova-gateway-alb/xxxxx/xxxxx \
  --priority 99 \
  --conditions Field=path-pattern,Values='/grpc.health.v1.Health/*' \
  --actions Type=forward,TargetGroupArn=arn:aws:elasticloadbalancing:region:account:targetgroup/byova-grpc-tg/xxxxx
```

## gRPC Security Groups

```bash
# Allow ALB to reach gRPC backend on port 50051
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxxx \
  --protocol tcp \
  --port 50051 \
  --cidr 0.0.0.0/0 \
  --description "gRPC Backend Access"
```

## Register gRPC Targets

```bash
# Register ECS service or EC2 instances with gRPC target group
aws elbv2 register-targets \
  --target-group-arn arn:aws:elasticloadbalancing:region:account:targetgroup/byova-grpc-tg/xxxxx \
  --targets Id=10.0.1.100,Port=50051
```

## gRPC Verification

```bash
# Test gRPC TLS connection using grpcurl (port 443 with path-based routing)
grpcurl -import-path proto -proto voicevirtualagent.proto \
  your-domain.com:443 \
  com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent/ListVirtualAgents

# Test gRPC health check (requires optional health check routing rule above)
grpcurl -import-path proto -proto health.proto \
  your-domain.com:443 \
  grpc.health.v1.Health/Check
```
