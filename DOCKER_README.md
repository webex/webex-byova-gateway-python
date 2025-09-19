# Docker Production Deployment Guide

This guide covers building and deploying the Webex BYOVA Gateway using Docker for production environments, particularly AWS.

## Prerequisites

- Docker installed and running
- AWS CLI configured (for AWS deployments)
- Docker Compose installed

## Quick Start

### Build the Docker Image

```bash
# Build the production image
docker build -t byova-gateway:latest .

# Or using docker-compose
docker-compose build
```

### Run Locally (for testing)

The docker-compose.yml is designed to work both locally and in production:

**Option 1: With AWS credentials (local testing)**
```bash
# Set your AWS credentials as environment variables
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_REGION=us-east-1
export AWS_LEX_BOT_NAME=your_bot_name

# Start the gateway
docker-compose up -d

# View logs
docker-compose logs -f

# Check status
docker-compose ps

# Stop the gateway
docker-compose down
```

**Option 2: With .env file (local testing)**
```bash
# Copy environment template
cp env.example .env

# Edit with your values
nano .env

# Start the gateway
docker-compose up -d
```

**Option 3: Without AWS credentials (local testing with local connector)**
```bash
# Just start with defaults - will use local audio connector
docker-compose up -d
```

## Production Deployment

### AWS ECR Deployment

```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

# Tag the image for ECR
docker tag byova-gateway:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/byova-gateway:latest

# Push to ECR
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/byova-gateway:latest
```

### AWS ECS Deployment

```bash
# Update ECS service with new image
aws ecs update-service --cluster byova-gateway-cluster --service byova-gateway-service --force-new-deployment --region us-east-1
```

## Environment Variables

### Using .env File

```bash
# Copy environment template
cp env.example .env

# Edit with your values
nano .env

# Start with environment variables
docker-compose up -d
```

### Using Environment Variables Directly

```bash
# Run with environment variables
docker run -d \
  --name byova-gateway \
  -p 50051:50051 \
  -p 8080:8080 \
  -e AWS_REGION=us-east-1 \
  -e AWS_ACCESS_KEY_ID=your_access_key \
  -e AWS_SECRET_ACCESS_KEY=your_secret_key \
  -e AWS_LEX_BOT_ALIAS_ID=TSTALIASID \
  -e LOG_LEVEL=INFO \
  byova-gateway:latest
```

## Configuration

The Docker setup uses the configuration from `config/config.yaml`. The container:

- Mounts the `config/` directory as read-only
- Mounts the `audio/` directory for audio files
- Mounts the `logs/` directory for log files
- Sets the correct Python path for imports
- Supports environment variable overrides

## Accessing the Gateway

Once running, you can access:

- **gRPC Server**: `localhost:50051`
- **Web Monitoring UI**: http://localhost:8080
- **Health Check**: http://localhost:8080/health
- **Status API**: http://localhost:8080/api/status

## Troubleshooting

### Common Issues

1. **Port conflicts**: Ensure ports 50051 and 8080 are available
2. **Permission errors**: Check file permissions in mounted directories
3. **Build failures**: Check Docker logs for specific error messages
4. **Service won't start**: Check the logs with `docker-compose logs`

### Debugging

```bash
# Access the container shell for debugging
docker-compose exec byova-gateway /bin/bash

# Check container status
docker-compose ps

# View detailed logs
docker-compose logs byova-gateway

# Check container health
docker inspect <container_id> | grep -A 10 Health
```

### Clean Up

```bash
# Stop and remove containers, networks, and volumes
docker-compose down -v

# Remove unused Docker resources
docker system prune -f

# Remove the image
docker rmi byova-gateway:latest
```

## File Structure

```
.
├── Dockerfile              # Docker image definition
├── docker-compose.yml      # Production deployment setup
├── .dockerignore          # Files to exclude from Docker context
├── env.example            # Environment variables template
└── DOCKER_README.md       # This file
```

## Security Considerations

- The container runs as a non-root user
- Only necessary ports are exposed
- Use IAM roles in production instead of hardcoded credentials
- Enable CloudTrail logging for audit trails
- Use private subnets for production deployments

## Next Steps

Once you have the Docker setup working:

1. Test the gateway functionality
2. Verify all connectors work correctly
3. Check the monitoring interface
4. Deploy to AWS ECS/Fargate
5. Set up monitoring and alerting

## Support

If you encounter issues:

1. Check the logs: `docker-compose logs`
2. Verify Docker is running: `docker info`
3. Check port availability: `netstat -an | grep -E "(50051|8080)"`
4. Review the main project README for additional troubleshooting