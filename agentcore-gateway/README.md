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
- DynamoDB-based account registry for dynamic account management
- Simple Lambda bridge - no account configuration required in Lambda

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
|                      +------- Query accounts |                                 |
|                      v                       | Workload Identity Token         |
|              +---------------+               v                                 |
|              |   DynamoDB    |      +------------------+                       |
|              | (Account      |      | AgentCore        |                       |
|              |  Registry)    |      | Gateway          |                       |
|              +---------------+      +--------+---------+                       |
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

### Data Flow

1. **Agent queries DynamoDB** to get list of accounts and map friendly names to account IDs
2. **Agent calls Gateway** with `query` tool, passing `account_id`, `tool_name`, and `arguments`
3. **Gateway invokes Lambda** with SigV4 (automatic via service role)
4. **Lambda assumes target role** in the specified account using STS AssumeRole
5. **Lambda calls AWS MCP Server** with the assumed credentials
6. **MCP Server executes** the AWS CLI command and returns results

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
│   ├── Dockerfile                         # Container for AgentCore Runtime
│   ├── .bedrock_agentcore.yaml            # Runtime configuration
│   └── requirements.txt                   # Python dependencies
├── lambda/
│   └── handler.py                         # Lambda Bridge function
├── infrastructure/
│   ├── bin/
│   │   └── infrastructure.ts              # CDK app entry point
│   ├── lib/
│   │   ├── cognito-stack.ts               # Cognito User Pool
│   │   ├── dynamodb-stack.ts              # DynamoDB table for account mappings
│   │   ├── lambda-stack.ts                # Bridge Lambda function
│   │   ├── roles-stack.ts                 # Gateway and Runtime IAM roles
│   │   ├── member-account-stack.ts        # Member account target role
│   │   ├── ecr-stack.ts                   # ECR repository for agent container
│   │   ├── gateway-stack.ts               # AgentCore Gateway and Lambda target
│   │   └── runtime-stack.ts               # AgentCore Runtime and endpoint
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

### 1. Deploy Infrastructure

```bash
cd agentcore-gateway/infrastructure

# Install dependencies
npm install

# Bootstrap CDK (first time only)
npx cdk bootstrap

# Deploy all stacks (Cognito, Lambda, Roles, ECR, Gateway)
npx cdk deploy --all \
  -c region=us-west-2 \
  -c centralAccountId=YOUR_ACCOUNT_ID

# Note: AWS MCP Server is only available in us-east-1
# The Lambda signs requests to us-east-1 regardless of deployment region
```

The CDK deployment creates:
1. **DynamoDB** - Account mappings table (agent queries this for account list)
2. **Cognito** - User Pool and Client for JWT authentication
3. **Lambda** - Bridge function for AWS MCP Server access
4. **Roles** - Gateway and Runtime IAM roles
5. **ECR** - Repository for agent container
6. **Gateway** - AgentCore Gateway with Lambda target

### 2. Configure Account Mappings

After deployment, populate the DynamoDB accounts table. The agent queries this table to get the list of accounts and map account names to IDs.

```bash
# Set region (same as deployment region)
REGION="us-east-1"
TABLE_NAME="central-ops-accounts-dev"

# Example: Add production account
aws dynamodb put-item --table-name $TABLE_NAME --region $REGION --item '{
  "account_id": {"S": "222222222222"},
  "name": {"S": "Production"},
  "environment": {"S": "prod"},
  "description": {"S": "Production AWS account"},
  "enabled": {"BOOL": true}
}'

# Example: Add staging account
aws dynamodb put-item --table-name $TABLE_NAME --region $REGION --item '{
  "account_id": {"S": "333333333333"},
  "name": {"S": "Staging"},
  "environment": {"S": "staging"},
  "description": {"S": "Staging AWS account"},
  "enabled": {"BOOL": true}
}'

# List all accounts in the table
aws dynamodb scan --table-name $TABLE_NAME --region $REGION \
  --query 'Items[*].{AccountID:account_id.S,Name:name.S,Environment:environment.S}' \
  --output table
```

### 4. Deploy Runtime (Optional)

To deploy the AgentCore Runtime with the containerized agent:

```bash
# Build and push agent container
cd ../agent
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com
docker build -t central-ops-agent .
docker tag central-ops-agent:latest $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/central-ops-agent-dev:latest
docker push $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/central-ops-agent-dev:latest

# Deploy Runtime stack
cd ../infrastructure
npx cdk deploy CentralOps-Runtime-dev -c region=us-west-2 -c deployRuntime=true
```

### 5. Deploy Member Account Roles

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

### Lambda Configuration

The Lambda Bridge is a simple pass-through function that:
1. Receives query requests with `account_id`, `tool_name`, and `arguments`
2. Assumes the target role in the specified account
3. Calls AWS MCP Server with the assumed credentials

No environment variables are required - account management is handled by the agent via DynamoDB.

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

After deployment, test the Gateway directly:

```bash
# Set region (stacks are deployed to us-east-1 by default)
REGION="us-east-1"

# Get stack outputs
GATEWAY_URL=$(aws cloudformation describe-stacks --stack-name CentralOps-Gateway-dev \
  --region $REGION --query 'Stacks[0].Outputs[?OutputKey==`GatewayUrl`].OutputValue' --output text)
POOL_ID=$(aws cloudformation describe-stacks --stack-name CentralOps-Cognito-dev \
  --region $REGION --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' --output text)
CLIENT_ID=$(aws cloudformation describe-stacks --stack-name CentralOps-Cognito-dev \
  --region $REGION --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' --output text)

# Create test user (first time)
aws cognito-idp admin-create-user --user-pool-id $POOL_ID --username test@example.com \
  --temporary-password TempPass123! --message-action SUPPRESS --region $REGION
aws cognito-idp admin-set-user-password --user-pool-id $POOL_ID --username test@example.com \
  --password TestPass123! --permanent --region $REGION

# Get Cognito ID token
TOKEN=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id $CLIENT_ID \
  --auth-parameters USERNAME=test@example.com,PASSWORD=TestPass123! \
  --region $REGION \
  --query 'AuthenticationResult.IdToken' --output text)

# Test Gateway - query AWS MCP Server (list regions)
curl -s -X POST "$GATEWAY_URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"bridge-lambda___query","arguments":{"account_id":"YOUR_ACCOUNT_ID","tool_name":"aws___list_regions","arguments":{}}}}' | jq .

# Test Gateway - query AWS CLI command (list S3 buckets)
curl -s -X POST "$GATEWAY_URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"bridge-lambda___query","arguments":{"account_id":"YOUR_ACCOUNT_ID","tool_name":"aws___call_aws","arguments":{"cli_command":"aws s3 ls"}}}}' | jq .
```

## CDK Stacks

### DynamoDBStack
- Account mappings table (`central-ops-accounts-{env}`)
- Agent queries this table to get account list and map names to IDs
- GSI for querying accounts by environment
- Point-in-time recovery enabled

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
- Runtime execution role (for Bedrock, Gateway, ECR, and Identity access)

### MemberAccountStack
- Target role for cross-account access (deploy in each member account)
- ReadOnlyAccess managed policy
- AWS MCP access permissions (`InvokeMcp`, `CallReadOnlyTool`, `CallReadWriteTool`)

### EcrStack
- ECR repository for agent container images
- Lifecycle policy to retain 5 most recent images

### GatewayStack
- AgentCore Gateway with MCP protocol
- Lambda target with tool schema definitions
- JWT authorizer configuration (Cognito)

### RuntimeStack (conditional)
- AgentCore Runtime with containerized agent
- Runtime endpoint for invocations
- Environment variables: `GATEWAY_URL`, `MODEL_ID`, `ACCOUNTS_TABLE_NAME`
- Runtime role has DynamoDB read access for account lookups
- Deployed when `-c deployRuntime=true` is passed

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

### AWS MCP Server Issues

- **Region**: AWS MCP Server is only available in `us-east-1`. The Lambda signs requests to this region regardless of deployment region.
- **CLI Command Format**: `aws___call_aws` requires `cli_command` parameter starting with "aws" (e.g., `"aws lambda list-functions"`)
- **Session Initialization**: MCP protocol requires `initialize` before `tools/call` - the Lambda handles this automatically

### CDK BedrockAgentCore Issues

- **CDK Version**: Requires `aws-cdk-lib` version 2.236.0+ for `aws-bedrockagentcore` module
- **protocolConfiguration**: Must be a string (`"HTTP"`), not an object
- **Gateway attributes**: Use `attrGatewayIdentifier` (not `attrGatewayId`)

### JWT Authentication Issues

- **Cognito ID tokens**: Only configure `allowedAudience` in Gateway authorizer (ID tokens have `aud` but not `client_id` claim)
- **Access tokens**: If using access tokens, configure `allowedClients` instead
- **Both configured**: If both `allowedAudience` AND `allowedClients` are set, BOTH must validate

### Lambda Gateway Target Format

When Gateway invokes Lambda, the event format is:
- **event**: Tool arguments directly (e.g., `{"account_id": "123", "tool_name": "aws___list_regions"}`)
- **context.client_context.custom**: Contains `bedrockAgentCoreToolName` with format `targetname___toolname`

## References

- [AWS MCP Server Documentation](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html)
- [AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)
- [AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/home.html)
- [Bedrock Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html)

## License

This project is licensed under the MIT License.
