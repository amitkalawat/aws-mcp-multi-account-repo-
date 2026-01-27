# AgentCore Gateway - Multi-Account AWS Operations Agent

Production-ready agent deployment using **AgentCore Runtime**, **AgentCore Gateway**, and a **Lambda Bridge** to query AWS resources across multiple accounts via AWS MCP Server.

## Overview

This implementation uses the AgentCore Gateway's Lambda target feature to bridge to AWS MCP Server. The Lambda Bridge pattern solves a key constraint: AWS MCP Server requires SigV4 authentication, but AgentCore Gateway only supports SigV4 for Lambda targets (not for MCP targets directly).

**Key Features:**
- Managed AgentCore Runtime for agent execution
- JWT authentication via Cognito for client access
- Workload Identity for Runtime-to-Gateway authentication
- Automatic SigV4 signing for Gateway-to-Lambda calls
- Cross-account AWS resource queries via STS AssumeRole

## Architecture

```
                                    CENTRAL OPERATIONS ACCOUNT
+--------------------------------------------------------------------------------+
|                                                                                |
|    +--------+     JWT (Cognito)     +------------------+                       |
|    | Client | -------------------> | AgentCore        |                       |
|    +--------+                       | Runtime          |                       |
|                                     | (CentralOpsAgent)|                       |
|                                     +--------+---------+                       |
|                                              |                                 |
|                                              | Workload Identity Token         |
|                                              v                                 |
|                                     +------------------+                       |
|                                     | AgentCore        |                       |
|                                     | Gateway          |                       |
|                                     +--------+---------+                       |
|                                              |                                 |
|                                              | SigV4 (automatic)               |
|                                              v                                 |
|                                     +------------------+                       |
|                                     | Lambda Bridge    |                       |
|                                     | (aws-mcp-bridge) |                       |
|                                     +--------+---------+                       |
|                                              |                                 |
|                                              | SigV4 (per-account credentials) |
|                                              v                                 |
|                                     +------------------+                       |
|                                     | AWS MCP Server   |                       |
|                                     +--------+---------+                       |
|                                              |                                 |
+----------------------------------------------+--------------------------------+
                                               |
                                               | STS AssumeRole
                                               v
                    +--------------------------------------------------+
                    |                 MEMBER ACCOUNTS                   |
                    |  +----------+  +----------+  +----------+        |
                    |  | Account  |  | Account  |  | Account  |  ...   |
                    |  | (Prod)   |  | (Stage)  |  | (Dev)    |        |
                    |  | Target   |  | Target   |  | Target   |        |
                    |  | Role     |  | Role     |  | Role     |        |
                    |  +----------+  +----------+  +----------+        |
                    +--------------------------------------------------+
```

### Authentication Flow

| Hop | From | To | Auth Method |
|-----|------|----|-------------|
| 1 | Client | Runtime | JWT (Cognito) |
| 2 | Runtime | Gateway | Workload Identity Token |
| 3 | Gateway | Lambda | SigV4 (automatic via service role) |
| 4 | Lambda | MCP Server | SigV4 (per-account credentials) |

## Prerequisites

- **AWS CLI v2** - Configured with credentials for central account
- **Node.js 18+** and **npm** - For CDK deployment
- **Python 3.12** - For Lambda and agent code
- **AWS CDK** - Installed globally or via npx
- **AWS Organizations** - With member accounts configured
- **Bedrock Model Access** - Claude 3.5 Sonnet enabled in region

Verify prerequisites:
```bash
aws --version          # AWS CLI v2.x.x
node --version         # v18.x.x or higher
python3 --version      # Python 3.12.x
aws sts get-caller-identity  # Valid credentials
```

## Project Structure

```
agentcore-gateway/
├── README.md                              # This file
├── agent/
│   ├── central_ops_agent.py               # Agent code (Bedrock Converse API)
│   ├── .bedrock_agentcore.yaml            # Runtime configuration
│   └── requirements.txt                   # Python dependencies
├── lambda/
│   └── handler.py                         # Lambda Bridge function
├── infrastructure/
│   ├── bin/
│   │   └── infrastructure.ts              # CDK app entry point
│   ├── lib/
│   │   ├── cognito-stack.ts               # Cognito User Pool
│   │   ├── lambda-stack.ts                # Bridge Lambda function
│   │   ├── roles-stack.ts                 # Gateway and Runtime IAM roles
│   │   └── member-account-stack.ts        # Member account target role
│   ├── config/
│   │   └── accounts.json                  # Account configuration (gitignored)
│   ├── package.json                       # Node.js dependencies
│   ├── cdk.json                           # CDK configuration
│   └── tsconfig.json                      # TypeScript configuration
├── scripts/
│   └── deploy.sh                          # Deployment automation
└── tests/
    ├── conftest.py                        # Pytest configuration
    ├── test_handler.py                    # Lambda tests
    └── test_central_ops_agent.py          # Agent tests
```

## Quick Start

### 1. Configure Accounts

Create `infrastructure/config/accounts.json`:

```json
{
  "accounts": [
    {"id": "111111111111", "name": "Central", "role": "central"},
    {"id": "222222222222", "name": "Production", "role": "member"},
    {"id": "333333333333", "name": "Staging", "role": "member"}
  ]
}
```

### 2. Deploy Infrastructure

```bash
cd agentcore-gateway

# Set environment variables (optional, defaults shown)
export ENVIRONMENT=dev
export AWS_REGION=us-east-1

# Run deployment script
./scripts/deploy.sh
```

The script will:
1. Check prerequisites (AWS CLI, Node.js, credentials)
2. Install CDK dependencies
3. Bootstrap CDK (if needed)
4. Deploy all stacks (Cognito, Lambda, Roles)
5. Output CLI commands for manual Gateway/Runtime creation

### 3. Create Gateway and Runtime (Manual)

After CDK deployment, run the CLI commands printed by the deploy script:

```bash
# Create Gateway
aws bedrock-agentcore-control create-gateway \
  --gateway-name central-ops-gateway-dev \
  --role-arn arn:aws:iam::111111111111:role/CentralOpsGatewayRole-dev

# Add Lambda target to Gateway
aws bedrock-agentcore-control create-gateway-target \
  --gateway-identifier central-ops-gateway-dev \
  --name bridge-lambda \
  --target-configuration '{"lambdaTargetConfiguration": {"lambdaArn": "arn:aws:lambda:us-east-1:111111111111:function:aws-mcp-bridge-dev"}}'

# Deploy agent to Runtime
cd agent
agentcore deploy --execution-role arn:aws:iam::111111111111:role/CentralOpsRuntimeRole-dev
```

### 4. Deploy Member Account Roles

For each member account, deploy the target role:

```bash
# Using CDK (from member account)
npx cdk deploy MemberAccountStack \
  --context centralAccountId=111111111111 \
  --context bridgeLambdaRoleArn=arn:aws:iam::111111111111:role/CentralOpsBridgeRole-dev

# Or using StackSets from central account for automation
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `dev` | Deployment environment (dev, staging, prod) |
| `AWS_REGION` | `us-east-1` | AWS region for deployment |

### Agent Configuration

The agent configuration in `.bedrock_agentcore.yaml`:

```yaml
name: central-ops-agent
entrypoint: central_ops_agent.py

runtime:
  execution_role: ${RUNTIME_ROLE_ARN}
  authorizer:
    type: customJWTAuthorizer
    discovery_url: ${COGNITO_DISCOVERY_URL}
    allowed_audiences:
      - central-ops-client
    allowed_clients:
      - ${COGNITO_CLIENT_ID}
  request_header_allowlist:
    - Authorization

gateway:
  target_name: bridge-lambda
  gateway_id: ${GATEWAY_ID}
```

### Lambda Environment Variables

| Variable | Description |
|----------|-------------|
| `TARGET_ACCOUNTS` | JSON array of target accounts |
| `TARGET_ROLE_NAME` | IAM role name in member accounts (default: `CentralOpsTargetRole`) |

## Testing

### Unit Tests

```bash
cd agentcore-gateway

# Install test dependencies
pip install pytest

# Run all tests
pytest tests/ -v

# Run specific test files
pytest tests/test_handler.py -v
pytest tests/test_central_ops_agent.py -v
```

### CDK Tests

```bash
cd infrastructure
npm test
```

### Integration Testing

After deployment, test the agent:

```bash
# Get Cognito token
TOKEN=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id $COGNITO_CLIENT_ID \
  --auth-parameters USERNAME=$USER,PASSWORD=$PASS \
  --query 'AuthenticationResult.IdToken' --output text)

# Call agent
curl -X POST https://$RUNTIME_ENDPOINT/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "List EC2 instances in account 222222222222"}'
```

## CDK Stacks

### CognitoStack
- Cognito User Pool for client authentication
- User Pool Client with password auth flows
- OIDC discovery URL for JWT validation

### LambdaStack
- Bridge Lambda function (Python 3.12)
- IAM role with cross-account AssumeRole permissions
- AWS MCP access permissions

### RolesStack
- Gateway service role (for Lambda invocation)
- Runtime execution role (for Bedrock, Gateway, and Identity access)

### MemberAccountStack
- Target role for cross-account access (deploy in each member account)
- ReadOnlyAccess managed policy
- AWS MCP access permissions

## Architecture Decision: Why Lambda Bridge?

AgentCore Gateway supports multiple target types with different authentication options:

| Target Type | No Auth | SigV4 | OAuth | API Key |
|-------------|---------|-------|-------|---------|
| Lambda | No | **Yes** | No | No |
| MCP Server | Yes | No | Yes | No |
| API Gateway | No | Yes | No | Yes |

AWS MCP Server **only supports SigV4** authentication. Since Gateway cannot use SigV4 for MCP targets, we use Lambda as a bridge:

1. **Gateway to Lambda**: SigV4 authentication is automatic via the Gateway service role
2. **Lambda to MCP Server**: Lambda signs requests using assumed credentials from target accounts

This approach avoids the complexity of setting up an OAuth provider for MCP targets while still leveraging the managed AgentCore infrastructure.

## Troubleshooting

### CDK Deployment Fails

```bash
# Ensure CDK is bootstrapped
cd infrastructure
npx cdk bootstrap

# Check AWS credentials
aws sts get-caller-identity
```

### Lambda Timeout

The Bridge Lambda has a 120-second timeout. If queries consistently timeout:
- Check network connectivity to AWS MCP endpoint
- Verify target account role trust policy
- Enable Lambda provisioned concurrency to avoid cold starts

### Gateway Authentication Errors

If clients receive 401/403 errors:
- Verify Cognito User Pool ID and Client ID in Gateway config
- Check JWT token expiration (1 hour default)
- Ensure user is in the correct Cognito group

### Cross-Account Access Denied

If AssumeRole fails:
- Verify target role exists in member account
- Check trust policy includes central account and Lambda role ARN
- Confirm Organization ID conditions match

## References

- [AWS MCP Server Documentation](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html)
- [AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)
- [AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/home.html)
- [Bedrock Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html)

## License

This project is licensed under the MIT License.
