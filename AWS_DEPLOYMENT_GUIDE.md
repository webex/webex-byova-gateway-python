# AWS Deployment Guide for BYOVA Gateway

This guide walks you through deploying the Webex Contact Center BYOVA Gateway to AWS, starting from an account that only has AWS Lex service enabled.

## Prerequisites

- AWS Account with AWS Lex service access
- Docker installed locally
- AWS CLI configured
- Basic understanding of AWS services

## Overview

We'll deploy the BYOVA Gateway using:
- **AWS ECS (Elastic Container Service)** with Fargate for serverless container orchestration
- **AWS ECR (Elastic Container Registry)** for storing Docker images
- **AWS IAM** for security and permissions
- **AWS VPC** for networking (optional but recommended)
- **AWS CloudWatch** for logging and monitoring

## Step 1: Enable Required AWS Services

### 1.1 Enable AWS Services

Go to the AWS Management Console and enable these services:

1. **AWS ECS (Elastic Container Service)**
   - Navigate to ECS in the AWS Console
   - Click "Get Started" if prompted
   - **Skip the sample application setup** - Click "Cancel" or "Skip" when it asks to create a sample application
   - You should now see the ECS dashboard with "Clusters" in the left sidebar
   - **Note**: We'll create our cluster programmatically later, so no need to create one manually now

2. **AWS ECR (Elastic Container Registry)**
   - Navigate to ECR in the AWS Console
   - Click "Create repository"
   - **Repository name**: `byova-gateway`
   - **Namespace**: Leave blank (will use your AWS account ID as namespace)
   - **Visibility settings**: Select "Private"
   - **Tag immutability**: Leave as "Mutable" (allows overwriting tags)
   - **Encryption settings**: 
     - **Encryption type**: Select "AES-256" (default and recommended)
     - **KMS encryption**: Leave unchecked (uses AWS managed encryption)
   - Click "Create repository"

3. **AWS IAM (Identity and Access Management)**
   - Navigate to IAM in the AWS Console
   - This should already be available

4. **AWS CloudWatch**
   - Navigate to CloudWatch in the AWS Console
   - This should already be available

### 1.2 Verify AWS Lex Access

Ensure your AWS Lex bots are accessible:
```bash
aws lexv2-models list-bots --region us-east-1
```

You should see your existing Lex bots (Booking, HotelBookingBot).

## Step 2: Set Up AWS Infrastructure

### 2.1 Authenticate Docker with ECR

Now that you have your ECR repository created, authenticate Docker to push images:

```bash
# Get login token and authenticate Docker
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <YOUR_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com
```

Replace `<YOUR_ACCOUNT_ID>` with your actual AWS account ID.

### 2.2 Create IAM Role for ECS Task

Create an IAM role that allows ECS tasks to access AWS Lex:

```bash
# Trust policy file is already created at aws/ecs-task-trust-policy.json

# Create IAM role
aws iam create-role \
    --role-name BYOVAGatewayTaskRole \
    --assume-role-policy-document file://aws/ecs-task-trust-policy.json

# Policy file is already created at aws/ecs-task-policy.json

# Attach policy to role
aws iam put-role-policy \
    --role-name BYOVAGatewayTaskRole \
    --policy-name LexAccessPolicy \
    --policy-document file://aws/ecs-task-policy.json
```

### 2.3 Create ECS Cluster

```bash
# Create ECS cluster
aws ecs create-cluster \
    --cluster-name byova-gateway-cluster \
    --region us-east-1
```

## Step 3: Prepare Docker Image

### 3.1 Build and Push Docker Image

```bash
# Build the Docker image for AWS ECS (linux/amd64 platform)
docker build --platform linux/amd64 -t byova-gateway:latest .

# Tag for ECR
docker tag byova-gateway:latest <YOUR_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/byova-gateway:latest

# Push to ECR
docker push <YOUR_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/byova-gateway:latest
```

**📝 Important**: Always use `--platform linux/amd64` when building for AWS ECS Fargate, even if you're on an M1/M2 Mac or ARM-based system. This ensures compatibility with AWS infrastructure.

### 3.2 Create Task Definition

The task definition file is already created at `aws/task-definition.json`.

**Important**: Before using this file, you need to replace the placeholder values:
- Replace `<YOUR_ACCOUNT_ID>` with your actual AWS account ID in two places:
  - `executionRoleArn`
  - `taskRoleArn` 
  - `image` URL

### 3.3 Create CloudWatch Log Group

```bash
# Create log group
aws logs create-log-group \
    --log-group-name /ecs/byova-gateway \
    --region us-east-1
```

### 3.4 Register Task Definition

```bash
# Register task definition
aws ecs register-task-definition \
    --cli-input-json file://aws/task-definition.json \
    --region us-east-1
```

## Step 4: Set Up Networking (Optional but Recommended)

### 4.1 Create VPC and Subnets

```bash
# Create VPC
VPC_ID=$(aws ec2 create-vpc \
    --cidr-block 10.0.0.0/16 \
    --query 'Vpc.VpcId' \
    --output text)

# Create Internet Gateway
IGW_ID=$(aws ec2 create-internet-gateway \
    --query 'InternetGateway.InternetGatewayId' \
    --output text)

# Attach Internet Gateway to VPC
aws ec2 attach-internet-gateway \
    --vpc-id $VPC_ID \
    --internet-gateway-id $IGW_ID

# Create public subnet 1
SUBNET_ID_1=$(aws ec2 create-subnet \
    --vpc-id $VPC_ID \
    --cidr-block 10.0.1.0/24 \
    --availability-zone us-east-1a \
    --query 'Subnet.SubnetId' \
    --output text)

# Create public subnet 2 (required for ALB)
SUBNET_ID_2=$(aws ec2 create-subnet \
    --vpc-id $VPC_ID \
    --cidr-block 10.0.2.0/24 \
    --availability-zone us-east-1b \
    --query 'Subnet.SubnetId' \
    --output text)

# Enable auto-assign public IP for both subnets
aws ec2 modify-subnet-attribute \
    --subnet-id $SUBNET_ID_1 \
    --map-public-ip-on-launch

aws ec2 modify-subnet-attribute \
    --subnet-id $SUBNET_ID_2 \
    --map-public-ip-on-launch

# Create route table
ROUTE_TABLE_ID=$(aws ec2 create-route-table \
    --vpc-id $VPC_ID \
    --query 'RouteTable.RouteTableId' \
    --output text)

# Create route to Internet Gateway
aws ec2 create-route \
    --route-table-id $ROUTE_TABLE_ID \
    --destination-cidr-block 0.0.0.0/0 \
    --gateway-id $IGW_ID

# Associate route table with both subnets
aws ec2 associate-route-table \
    --subnet-id $SUBNET_ID_1 \
    --route-table-id $ROUTE_TABLE_ID

aws ec2 associate-route-table \
    --subnet-id $SUBNET_ID_2 \
    --route-table-id $ROUTE_TABLE_ID

# Create security group
SECURITY_GROUP_ID=$(aws ec2 create-security-group \
    --group-name byova-gateway-sg \
    --description "Security group for BYOVA Gateway" \
    --vpc-id $VPC_ID \
    --query 'GroupId' \
    --output text)

# Allow inbound traffic on ports 50051 and 8080
aws ec2 authorize-security-group-ingress \
    --group-id $SECURITY_GROUP_ID \
    --protocol tcp \
    --port 50051 \
    --cidr 0.0.0.0/0

aws ec2 authorize-security-group-ingress \
    --group-id $SECURITY_GROUP_ID \
    --protocol tcp \
    --port 8080 \
    --cidr 0.0.0.0/0
```

## Step 5: Deploy to ECS

### 5.1 Create ECS Service

#### Option A: With Custom Networking (Recommended - if you completed Step 4)

```bash
# Create ECS service with custom networking
aws ecs create-service \
    --cluster byova-gateway-cluster \
    --service-name byova-gateway-service \
    --task-definition byova-gateway:1 \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_ID_1],securityGroups=[$SECURITY_GROUP_ID],assignPublicIp=ENABLED}" \
    --region us-east-1
```

#### Option B: Using Default VPC (if you skipped Step 4)

**⚠️ Warning**: This approach uses the default VPC and exposes your service to the internet. Only use for development/testing.

```bash
# Get default VPC and subnet IDs
DEFAULT_VPC_ID=$(aws ec2 describe-vpcs --filters "Name=is-default,Values=true" --query "Vpcs[0].VpcId" --output text)
DEFAULT_SUBNET_ID=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$DEFAULT_VPC_ID" --query "Subnets[0].SubnetId" --output text)

# Create a basic security group (allows all traffic - NOT recommended for production)
SECURITY_GROUP_ID=$(aws ec2 create-security-group \
    --group-name byova-gateway-sg \
    --description "Security group for BYOVA Gateway" \
    --vpc-id $DEFAULT_VPC_ID \
    --query "GroupId" --output text)

# Allow all traffic (for development only)
aws ec2 authorize-security-group-ingress \
    --group-id $SECURITY_GROUP_ID \
    --protocol all \
    --cidr 0.0.0.0/0

# Create ECS service with default VPC
aws ecs create-service \
    --cluster byova-gateway-cluster \
    --service-name byova-gateway-service \
    --task-definition byova-gateway:1 \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[$DEFAULT_SUBNET_ID],securityGroups=[$SECURITY_GROUP_ID],assignPublicIp=ENABLED}" \
    --region us-east-1
```

**Note**: If you use Option B, your BYOVA Gateway will be accessible from the internet. Make sure to:
- Monitor access logs
- Consider adding IP restrictions
- Use this only for development/testing
- Plan to implement proper networking for production

### 5.2 Check Service Status

```bash
# Check service status
aws ecs describe-services \
    --cluster byova-gateway-cluster \
    --services byova-gateway-service \
    --region us-east-1

# Check running tasks
aws ecs list-tasks \
    --cluster byova-gateway-cluster \
    --service-name byova-gateway-service \
    --region us-east-1
```

## Step 6: Set Up Load Balancer (Optional)

### 6.1 Create Application Load Balancer

```bash
# Create Application Load Balancer
ALB_ARN=$(aws elbv2 create-load-balancer \
    --name byova-gateway-alb \
    --subnets $SUBNET_ID_1 $SUBNET_ID_2 \
    --security-groups $SECURITY_GROUP_ID \
    --query 'LoadBalancers[0].LoadBalancerArn' \
    --output text)

# Create target group
TARGET_GROUP_ARN=$(aws elbv2 create-target-group \
    --name byova-gateway-tg \
    --protocol HTTP \
    --port 8080 \
    --vpc-id $VPC_ID \
    --target-type ip \
    --health-check-path /health \
    --query 'TargetGroups[0].TargetGroupArn' \
    --output text)

# Create listener
aws elbv2 create-listener \
    --load-balancer-arn $ALB_ARN \
    --protocol HTTP \
    --port 80 \
    --default-actions Type=forward,TargetGroupArn=$TARGET_GROUP_ARN
```

### 6.2 Update ECS Service with Load Balancer

```bash
# Update service to include load balancer
aws ecs update-service \
    --cluster byova-gateway-cluster \
    --service byova-gateway-service \
    --task-definition byova-gateway:1 \
    --load-balancers "targetGroupArn=$TARGET_GROUP_ARN,containerName=byova-gateway,containerPort=8080" \
    --region us-east-1
```

## Step 7: Monitoring and Logging

### 7.1 View Logs

```bash
# View logs in CloudWatch
aws logs describe-log-streams \
    --log-group-name /ecs/byova-gateway \
    --region us-east-1

# Get log events
# First, get the log stream name
LOG_STREAM_NAME=$(aws logs describe-log-streams \
    --log-group-name /ecs/byova-gateway \
    --order-by LastEventTime \
    --descending \
    --max-items 1 \
    --query "logStreams[0].logStreamName" \
    --output text \
    --region us-east-1)

# Then get the log events
aws logs get-log-events \
    --log-group-name /ecs/byova-gateway \
    --log-stream-name $LOG_STREAM_NAME \
    --region us-east-1
```

### 7.2 Set Up CloudWatch Alarms

```bash
# Create alarm for high CPU usage
aws cloudwatch put-metric-alarm \
    --alarm-name "BYOVA-Gateway-High-CPU" \
    --alarm-description "Alert when CPU usage is high" \
    --metric-name CPUUtilization \
    --namespace AWS/ECS \
    --statistic Average \
    --period 300 \
    --threshold 80 \
    --comparison-operator GreaterThanThreshold \
    --dimensions Name=ServiceName,Value=byova-gateway-service Name=ClusterName,Value=byova-gateway-cluster \
    --evaluation-periods 2 \
    --region us-east-1
```

## Step 8: Access Your Deployment

### 8.1 Get Service Endpoint

#### Option A: With Load Balancer (if you completed Step 4)

```bash
# Get load balancer DNS name and store in variable
LOAD_BALANCER_DNS=$(aws elbv2 describe-load-balancers \
    --load-balancer-arns $ALB_ARN \
    --query 'LoadBalancers[0].DNSName' \
    --output text)

echo "Load Balancer DNS: $LOAD_BALANCER_DNS"
```

#### Option B: Direct Container Access (if you skipped Step 4)

**⚠️ Note**: This gives you the direct container IP, which changes when tasks restart.

```bash
# Get the public IP of your running task
TASK_ARN=$(aws ecs list-tasks \
    --cluster byova-gateway-cluster \
    --service-name byova-gateway-service \
    --query 'taskArns[0]' \
    --output text)

# Get the task's public IP
aws ecs describe-tasks \
    --cluster byova-gateway-cluster \
    --tasks $TASK_ARN \
    --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
    --output text | xargs -I {} aws ec2 describe-network-interfaces \
    --network-interface-ids {} \
    --query 'NetworkInterfaces[0].Association.PublicIp' \
    --output text
```

**Alternative**: Check the ECS console to see your task's public IP address.

**Note**: If you skipped Step 4, set your endpoint manually:
```bash
# For direct container access, set your container's public IP
LOAD_BALANCER_DNS="<YOUR_CONTAINER_PUBLIC_IP>"
echo "Container IP: $LOAD_BALANCER_DNS"
```

### 8.2 Test Your Deployment

```bash
# Test health endpoint
curl http://$LOAD_BALANCER_DNS/health

# Test status endpoint
curl http://$LOAD_BALANCER_DNS/api/status

# Test monitoring interface
echo "Monitoring interface: http://$LOAD_BALANCER_DNS"
```

## Step 9: Scaling and Updates

**📝 Note**: Scaling is **optional** for development/testing but **recommended** for production deployments.

### When to Scale:
- **Production environments** - High availability and fault tolerance
- **High traffic** - Multiple concurrent conversations (>50-100)
- **Business-critical** - Zero-downtime requirements
- **Peak hours** - Handle traffic spikes

### When NOT to Scale:
- **Development/testing** - Single instance is sufficient
- **Low traffic** - <10 concurrent conversations
- **Cost-sensitive** - Minimize AWS costs
- **Proof-of-concept** - Simple demos and learning

### 9.1 Scale Your Service

```bash
# Scale to 2 instances
aws ecs update-service \
    --cluster byova-gateway-cluster \
    --service byova-gateway-service \
    --desired-count 2 \
    --region us-east-1
```

### 9.2 Update Your Application

```bash
# Build new image
docker build -t byova-gateway:v2 .

# Tag and push new version
docker tag byova-gateway:v2 <YOUR_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/byova-gateway:v2
docker push <YOUR_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/byova-gateway:v2

# Update task definition with new image
# Edit task-definition.json to use v2 image, then:
aws ecs register-task-definition \
    --cli-input-json file://aws/task-definition.json \
    --region us-east-1

# Update service to use new task definition
aws ecs update-service \
    --cluster byova-gateway-cluster \
    --service byova-gateway-service \
    --task-definition byova-gateway:2 \
    --region us-east-1
```

## Troubleshooting: Can't Connect to Your Service

### Check ECS Service Status

```bash
# Check if your service is running
aws ecs describe-services \
    --cluster byova-gateway-cluster \
    --services byova-gateway-service \
    --region us-east-1

# Check running tasks
aws ecs list-tasks \
    --cluster byova-gateway-cluster \
    --service-name byova-gateway-service \
    --region us-east-1
```

**🔍 What to Look For:**
- **Service Status**: Look for `"status": "ACTIVE"` and `"runningCount": 1`
- **Task Count**: Should show `"runningCount": 1` and `"pendingCount": 0`
- **Task ARNs**: Should return actual task IDs (not empty array)
- **Events**: Check recent events for errors like "failed to start" or "health check failed"

### View Container Logs

```bash
# Get the most recent log stream
LOG_STREAM_NAME=$(aws logs describe-log-streams \
    --log-group-name /ecs/byova-gateway \
    --order-by LastEventTime \
    --descending \
    --max-items 1 \
    --query "logStreams[0].logStreamName" \
    --output text \
    --region us-east-1)

# View recent logs
aws logs get-log-events \
    --log-group-name /ecs/byova-gateway \
    --log-stream-name $LOG_STREAM_NAME \
    --region us-east-1 \
    --start-time $(date -d '10 minutes ago' +%s)000
```

**🔍 What to Look For:**
- **✅ Success**: Look for `"Gateway is running!"` and `"Found X available Lex bots"`
- **❌ Errors**: Look for `"ERROR"` messages like:
  - `"AWS Lex API error"` - Credential/permission issues
  - `"ModuleNotFoundError"` - Missing Python dependencies
  - `"Address already in use"` - Port conflicts
  - `"Unable to locate credentials"` - AWS credential problems
- **🚨 Crashes**: Look for `"Traceback"` or `"Exception"` followed by stack traces

### Check Task Health

```bash
# Get task details
TASK_ARN=$(aws ecs list-tasks \
    --cluster byova-gateway-cluster \
    --service-name byova-gateway-service \
    --query 'taskArns[0]' \
    --output text)

# Check task health and status
aws ecs describe-tasks \
    --cluster byova-gateway-cluster \
    --tasks $TASK_ARN \
    --region us-east-1
```

**🔍 What to Look For:**
- **Task Status**: Should be `"RUNNING"` (not `"STOPPED"` or `"PENDING"`)
- **Health Status**: Should be `"HEALTHY"` (not `"UNHEALTHY"`)
- **Exit Code**: Should be `null` (if not null, container crashed)
- **Stopped Reason**: Should be `null` (if not null, shows why it stopped)
- **Last Status**: Should be `"RUNNING"` with recent timestamp

### Common Issues and Solutions

#### 1. **Service Not Running**
- Check if tasks are being created: `aws ecs list-tasks --cluster byova-gateway-cluster`
- Look for errors in task definition or IAM permissions

#### 2. **Container Crashing**
- Check logs for Python errors or missing dependencies
- Verify environment variables are set correctly
- Check if AWS credentials are working

#### 3. **Health Check Failing**
- Container might be starting but failing health checks
- Check if port 8080 is accessible: `curl http://localhost:8080/health`
- Verify health check path in task definition

#### 4. **Network Issues**
- Check security group rules allow traffic on ports 50051 and 8080
- Verify load balancer target group health
- Check if container is getting public IP

#### 5. **AWS Lex Connection Issues**
- Verify AWS credentials have Lex permissions
- Check if Lex bots exist and are accessible
- Look for "UnrecognizedClientException" in logs

#### 6. **Platform Architecture Issues**
- **Error**: `"CannotPullContainerError: image Manifest does not contain descriptor matching platform 'linux/amd64'"`
- **Solution**: Rebuild Docker image with `--platform linux/amd64` flag
- **Command**: `docker build --platform linux/amd64 -t byova-gateway:latest .`

### Quick Debug Commands

```bash
# Check service events (shows recent changes)
aws ecs describe-services \
    --cluster byova-gateway-cluster \
    --services byova-gateway-service \
    --query 'services[0].events' \
    --region us-east-1

# Check task stopped reason
aws ecs describe-tasks \
    --cluster byova-gateway-cluster \
    --tasks $TASK_ARN \
    --query 'tasks[0].stoppedReason' \
    --region us-east-1

# Check container exit code
aws ecs describe-tasks \
    --cluster byova-gateway-cluster \
    --tasks $TASK_ARN \
    --query 'tasks[0].containers[0].exitCode' \
    --region us-east-1
```

**🔍 What to Look For:**
- **Service Events**: Look for recent events with timestamps - errors will show here
- **Stopped Reason**: Should be `null` (if not null, shows why container stopped)
- **Exit Code**: Should be `null` (if not null, shows error code when container crashed)
- **Event Messages**: Look for phrases like "failed to start", "health check failed", "insufficient resources"

## Step 10: Cleanup (Optional)

**📝 Note**: Cleanup is **optional** but **recommended** to avoid ongoing AWS charges.

### When to Clean Up:
- **Development/testing** - Stop charges when not actively using
- **Temporary deployments** - Proof-of-concept or demos
- **Cost management** - Avoid unexpected AWS bills
- **Resource cleanup** - Remove unused infrastructure

### When NOT to Clean Up:
- **Production environments** - Keep infrastructure running
- **Frequent usage** - If you use the gateway regularly
- **Persistent deployments** - Long-term production systems
- **Team sharing** - Multiple developers using the same deployment

### 10.1 Delete Resources

```bash
# Delete ECS service
aws ecs update-service \
    --cluster byova-gateway-cluster \
    --service byova-gateway-service \
    --desired-count 0 \
    --region us-east-1

aws ecs delete-service \
    --cluster byova-gateway-cluster \
    --service byova-gateway-service \
    --region us-east-1

# Delete ECS cluster
aws ecs delete-cluster \
    --cluster byova-gateway-cluster \
    --region us-east-1

# Delete ECR repository
aws ecr delete-repository \
    --repository-name byova-gateway \
    --force \
    --region us-east-1

# Delete IAM role
aws iam delete-role-policy \
    --role-name BYOVAGatewayTaskRole \
    --policy-name LexAccessPolicy

aws iam delete-role \
    --role-name BYOVAGatewayTaskRole

# Delete VPC resources
aws ec2 delete-security-group \
    --group-id $SECURITY_GROUP_ID

aws ec2 delete-subnet \
    --subnet-id $SUBNET_ID

aws ec2 delete-route-table \
    --route-table-id $ROUTE_TABLE_ID

aws ec2 detach-internet-gateway \
    --internet-gateway-id $IGW_ID \
    --vpc-id $VPC_ID

aws ec2 delete-internet-gateway \
    --internet-gateway-id $IGW_ID

aws ec2 delete-vpc \
    --vpc-id $VPC_ID
```

## Troubleshooting

### Common Issues

1. **Task fails to start**
   - Check CloudWatch logs for errors
   - Verify IAM permissions
   - Ensure ECR repository exists and image is pushed

2. **Cannot connect to AWS Lex**
   - Verify IAM role has Lex permissions
   - Check AWS region configuration
   - Ensure Lex bots are accessible

3. **Health checks failing**
   - Verify container is listening on port 8080
   - Check security group allows inbound traffic
   - Ensure health check endpoint is working

### Useful Commands

```bash
# Check ECS service events
aws ecs describe-services \
    --cluster byova-gateway-cluster \
    --services byova-gateway-service \
    --region us-east-1 \
    --query 'services[0].events'

# Check task status
aws ecs describe-tasks \
    --cluster byova-gateway-cluster \
    --tasks <TASK_ARN> \
    --region us-east-1

# Check CloudWatch metrics
aws cloudwatch get-metric-statistics \
    --namespace AWS/ECS \
    --metric-name CPUUtilization \
    --dimensions Name=ServiceName,Value=byova-gateway-service \
    --start-time 2023-01-01T00:00:00Z \
    --end-time 2023-01-01T23:59:59Z \
    --period 300 \
    --statistics Average
```

## Security Best Practices

1. **Use IAM roles instead of hardcoded credentials**
2. **Enable VPC Flow Logs for network monitoring**
3. **Use AWS Secrets Manager for sensitive configuration**
4. **Enable CloudTrail for API call logging**
5. **Regularly update your Docker images**
6. **Use least privilege principle for IAM permissions**

## Cost Optimization

1. **Use Fargate Spot for non-critical workloads**
2. **Set up auto-scaling based on demand**
3. **Use CloudWatch Insights for log analysis**
4. **Monitor and optimize resource allocation**
5. **Use S3 for long-term log storage**

## Next Steps

1. **Set up CI/CD pipeline** using AWS CodePipeline
2. **Implement monitoring and alerting** with CloudWatch
3. **Add SSL/TLS termination** with AWS Certificate Manager
4. **Set up backup and disaster recovery**
5. **Implement blue-green deployments**

## Support

For issues with this deployment:
1. Check AWS CloudWatch logs
2. Review ECS service events
3. Verify IAM permissions
4. Check security group configurations
5. Consult AWS documentation for specific services

---

**Note**: This guide assumes you have the necessary AWS permissions to create and manage these resources. Some services may require additional permissions or may not be available in all AWS regions.
