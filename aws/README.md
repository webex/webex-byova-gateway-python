# AWS Deployment Configuration Files

This directory contains the AWS configuration files needed for deploying the BYOVA Gateway to AWS ECS.

## Files

### IAM Policies
- **`ecs-task-trust-policy.json`** - Trust policy that allows ECS tasks to assume the IAM role
- **`ecs-task-policy.json`** - Policy granting permissions for AWS Lex, CloudWatch Logs, and ECR access

### ECS Configuration
- **`task-definition.json`** - ECS task definition for the BYOVA Gateway container

## Usage

These files are referenced in the `AWS_DEPLOYMENT_GUIDE.md` for creating AWS infrastructure. Before using the task definition file, you need to replace the placeholder `<YOUR_ACCOUNT_ID>` with your actual AWS account ID.

## Customization

You can modify these files to:
- Add additional AWS service permissions
- Change resource limits (CPU, memory)
- Add environment variables
- Modify health check settings
- Update logging configuration

## Security Notes

- The IAM policies follow the principle of least privilege
- Only necessary AWS Lex permissions are included
- ECR permissions are limited to pulling images
- CloudWatch Logs permissions are scoped to the application's log group
