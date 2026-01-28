# AgentCore Gateway - Multi-Account AWS Operations Agent

A production-ready agent that queries AWS resources across multiple accounts using **AgentCore Runtime**, **AgentCore Gateway**, and **AWS MCP Server**.

## Architecture

```
                                    ┌─────────────┐
                                    │    USER     │
                                    │  (Browser)  │
                                    └──────┬──────┘
                                           │
                                           ▼ HTTPS
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            CENTRAL OPERATIONS ACCOUNT                            │
│                                                                                  │
│    ┌─────────────────────────────────────────────────────────────────────────┐   │
│    │                           FRONTEND HOSTING                              │   │
│    │                                                                         │   │
│    │              ┌──────────────┐          ┌──────────────┐                 │   │
│    │              │  CloudFront  │ ───────▶ │   S3 Bucket  │                 │   │
│    │              │    (CDN)     │          │  (React App) │                 │   │
│    │              └──────┬───────┘          └──────────────┘                 │   │
│    └─────────────────────┼───────────────────────────────────────────────────┘   │
│                          │                                                       │
│                          ▼ API Call + JWT                                        │
│    ┌─────────────────────────────────────────────────────────────────────────┐   │
│    │                          AGENT LAYER                                    │   │
│    │                                                                         │   │
│    │    ┌────────────┐         ┌───────────────────────────────────────┐     │   │
│    │    │  Cognito   │◀─OAuth─▶│          AgentCore Runtime            │     │   │
│    │    │ User Pool  │         │              (Agent)                  │     │   │
│    │    └────────────┘         │  ┌─────────────────────────────────┐  │     │   │
│    │                           │  │ • Strands Agent + Claude Model  │  │     │   │
│    │                           │  │ • MCP Client for Gateway        │  │     │   │
│    │                           │  │ • Account resolution logic      │  │     │   │
│    │                           │  └─────────────────────────────────┘  │     │   │
│    │                           └───────────────┬───────────────────────┘     │   │
│    └───────────────────────────────────────────┼─────────────────────────────┘   │
│                                                │                                  │
│                        ┌───────────────────────┴───────────────────────┐         │
│                        ▼                                               ▼         │
│    ┌─────────────────────────────────┐       ┌─────────────────────────────────┐ │
│    │           DynamoDB              │       │        AgentCore Gateway        │ │
│    │        (Account Registry)       │       │         (Tool Router)           │ │
│    │  ┌───────────────────────────┐  │       └───────────────┬─────────────────┘ │
│    │  │ account_id │ name │ env   │  │                       │                   │
│    │  │ 1234...    │ Prod │ prod  │  │                       ▼ Invoke            │
│    │  │ 5678...    │ Dev  │ dev   │  │       ┌─────────────────────────────────┐ │
│    │  └───────────────────────────┘  │       │         Lambda Bridge           │ │
│    └─────────────────────────────────┘       │  ┌───────────────────────────┐  │ │
│                                              │  │ • STS AssumeRole          │  │ │
│                                              │  │ • SigV4 Request Signing   │  │ │
│                                              │  │ • MCP Session Management  │  │ │
│                                              │  └───────────────────────────┘  │ │
│                                              └───────────────┬─────────────────┘ │
│                                                              │                   │
│                                                              ▼ SigV4             │
│                                              ┌─────────────────────────────────┐ │
│                                              │        AWS MCP Server           │ │
│                                              │   (15,000+ AWS APIs via MCP)    │ │
│                                              └───────────────┬─────────────────┘ │
└──────────────────────────────────────────────────────────────┼───────────────────┘
                                                               │
                                               STS AssumeRole  │
                       ┌───────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              MEMBER ACCOUNTS                                     │
│                                                                                  │
│     ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐          │
│     │    Production    │   │     Staging      │   │   Development    │   ...    │
│     │  ┌────────────┐  │   │  ┌────────────┐  │   │  ┌────────────┐  │          │
│     │  │ CentralOps │  │   │  │ CentralOps │  │   │  │ CentralOps │  │          │
│     │  │ TargetRole │  │   │  │ TargetRole │  │   │  │ TargetRole │  │          │
│     │  │ (ReadOnly) │  │   │  │ (ReadOnly) │  │   │  │ (ReadOnly) │  │          │
│     │  └────────────┘  │   │  └────────────┘  │   │  └────────────┘  │          │
│     └──────────────────┘   └──────────────────┘   └──────────────────┘          │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## Authentication

All components use the **same Cognito User Pool**:

| Component | Auth Method | Token Validation |
|-----------|-------------|------------------|
| Frontend | Cognito Hosted UI → ID Token | N/A (initiates auth) |
| Runtime | JWT in `Authorization` header | Validates `aud` claim = Client ID |
| Gateway | JWT in `Authorization` header | Validates `aud` claim = Client ID |

The ID token flows: **Frontend → Runtime → Gateway** (passed in request body as `access_token`).

## Request Flow

When a user asks "List S3 buckets in Production account":

```
1. USER → FRONTEND
   User types query in chat UI

2. FRONTEND → COGNITO
   User authenticates via Hosted UI (OAuth/PKCE)
   ← Returns ID Token (JWT with aud=client_id)

3. FRONTEND → RUNTIME
   POST /invocations
   Headers: Authorization: Bearer <ID_TOKEN>
   Body: { "prompt": "...", "access_token": "<ID_TOKEN>" }

   Runtime validates JWT (aud claim = Cognito client ID)

4. RUNTIME (Agent) → DYNAMODB
   Agent queries account registry
   ← Returns: [{ account_id: "123...", name: "Production", ... }]

5. RUNTIME (Agent) → GATEWAY
   MCP call via Strands MCPClient
   Headers: Authorization: Bearer <ID_TOKEN>
   Tool: bridge-lambda___query
   Args: { account_id, tool_name: "aws___call_aws", arguments: { cli_command: "aws s3 ls" } }

   Gateway validates JWT (same Cognito pool)

6. GATEWAY → LAMBDA (SigV4 automatic)
   Invokes bridge Lambda with tool arguments

7. LAMBDA → STS
   AssumeRole to target account
   ← Returns temporary credentials

8. LAMBDA → AWS MCP SERVER (SigV4 with assumed creds)
   Executes AWS CLI command in target account
   ← Returns S3 bucket list

9. Response flows back: MCP → Lambda → Gateway → Runtime → Frontend → User
```

## Project Structure

```
agentcore-gateway/
├── frontend/                    # React chat UI
│   ├── src/
│   │   ├── App.tsx              # Main chat component
│   │   ├── api/runtime.ts       # Runtime API with streaming
│   │   └── context/AuthContext  # Cognito auth via Amplify
│   └── scripts/deploy.sh        # S3/CloudFront deployment
├── agent/
│   ├── central_ops_agent.py     # Strands Agent with MCP client
│   └── Dockerfile               # Container for Runtime
├── lambda/
│   └── handler.py               # Bridge to AWS MCP Server
└── infrastructure/              # CDK stacks
    └── lib/
        ├── cognito-stack.ts     # User Pool (shared auth)
        ├── gateway-stack.ts     # AgentCore Gateway
        ├── runtime-stack.ts     # AgentCore Runtime
        ├── lambda-stack.ts      # Bridge Lambda
        ├── dynamodb-stack.ts    # Account registry
        └── frontend-stack.ts    # S3/CloudFront
```

## Quick Start

### 1. Deploy Infrastructure

```bash
cd agentcore-gateway/infrastructure
npm install
npx cdk bootstrap  # First time only
npx cdk deploy --all --region us-east-1
```

### 2. Build & Push Agent Container

```bash
cd ../agent
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1

aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

docker build -t central-ops-agent .
docker tag central-ops-agent:latest $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/central-ops-agent-dev:latest
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/central-ops-agent-dev:latest
```

### 3. Deploy Runtime

```bash
cd ../infrastructure
npx cdk deploy -c deployRuntime=true CentralOps-Runtime-dev
```

### 4. Configure Frontend & Deploy

```bash
cd ../frontend

# Create .env from stack outputs
cat > .env << EOF
VITE_COGNITO_USER_POOL_ID=$(aws cloudformation describe-stacks --stack-name CentralOps-Cognito-dev --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' --output text --region us-east-1)
VITE_COGNITO_CLIENT_ID=$(aws cloudformation describe-stacks --stack-name CentralOps-Cognito-dev --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' --output text --region us-east-1)
VITE_COGNITO_DOMAIN=$(aws cloudformation describe-stacks --stack-name CentralOps-Cognito-dev --query 'Stacks[0].Outputs[?OutputKey==`UserPoolDomainUrl`].OutputValue' --output text --region us-east-1 | sed 's|https://||')
VITE_RUNTIME_URL=$(aws cloudformation describe-stacks --stack-name CentralOps-Runtime-dev --query 'Stacks[0].Outputs[?OutputKey==`InvocationUrl`].OutputValue' --output text --region us-east-1)?qualifier=DEFAULT
VITE_AWS_REGION=us-east-1
EOF

npm install
npm run build
./scripts/deploy.sh
```

### 5. Add Accounts to Registry

```bash
# Add an account to DynamoDB
aws dynamodb put-item --table-name central-ops-accounts-dev --region us-east-1 --item '{
  "account_id": {"S": "123456789012"},
  "name": {"S": "Production"},
  "environment": {"S": "prod"},
  "enabled": {"BOOL": true}
}'
```

### 6. Deploy Target Role in Member Accounts

Run in each member account:

```bash
CENTRAL_ACCOUNT_ID="YOUR_CENTRAL_ACCOUNT_ID"

aws iam create-role --role-name CentralOpsTargetRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::'$CENTRAL_ACCOUNT_ID':role/CentralOpsBridgeRole-dev"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam attach-role-policy --role-name CentralOpsTargetRole \
  --policy-arn arn:aws:iam::aws:policy/ReadOnlyAccess

aws iam put-role-policy --role-name CentralOpsTargetRole \
  --policy-name MCPAccess --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["aws-mcp:InvokeMcp", "aws-mcp:CallReadOnlyTool", "aws-mcp:CallReadWriteTool"],
      "Resource": "*"
    }]
  }'
```

## Testing

### Create Test User

```bash
POOL_ID=$(aws cloudformation describe-stacks --stack-name CentralOps-Cognito-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' --output text --region us-east-1)

aws cognito-idp admin-create-user --user-pool-id $POOL_ID \
  --username test@example.com --temporary-password TempPass123! \
  --message-action SUPPRESS --region us-east-1

aws cognito-idp admin-set-user-password --user-pool-id $POOL_ID \
  --username test@example.com --password TestPass123! --permanent --region us-east-1
```

### Test Runtime API Directly

```bash
# Get token
CLIENT_ID=$(aws cloudformation describe-stacks --stack-name CentralOps-Cognito-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' --output text --region us-east-1)

TOKEN=$(aws cognito-idp admin-initiate-auth --user-pool-id $POOL_ID --client-id $CLIENT_ID \
  --auth-flow ADMIN_NO_SRP_AUTH \
  --auth-parameters "USERNAME=test@example.com,PASSWORD=TestPass123!" \
  --region us-east-1 --query 'AuthenticationResult.IdToken' --output text)

# Test Runtime
RUNTIME_URL=$(aws cloudformation describe-stacks --stack-name CentralOps-Runtime-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`InvocationUrl`].OutputValue' --output text --region us-east-1)

curl -X POST "$RUNTIME_URL?qualifier=DEFAULT" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: test-session-$(date +%s)-$(uuidgen)" \
  -d '{"prompt": "List S3 buckets in the Central account", "access_token": "'$TOKEN'"}'
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Runtime session ID error | Header must be >= 33 characters |
| "No response received" in frontend | Check browser console; verify `access_token` in request body |
| Gateway 401/403 | Verify Cognito client ID matches `allowedAudience` |
| Cross-account access denied | Check target role trust policy includes Lambda role ARN |
| AWS MCP errors | Ensure `cli_command` starts with "aws" |
| Empty runtime logs | Check Lambda bridge logs: `/aws/lambda/aws-mcp-bridge-dev` |
| CloudFront shows old version | Wait 30s after invalidation |

## Key Commands

```bash
# Check runtime status
aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id centralOpsAgentdev-XXXXX --region us-east-1

# View Lambda logs
aws logs tail "/aws/lambda/aws-mcp-bridge-dev" --region us-east-1 --since 15m

# List registered accounts
aws dynamodb scan --table-name central-ops-accounts-dev --region us-east-1

# Rebuild and deploy frontend
cd frontend && npm run build && ./scripts/deploy.sh
```

## References

- [AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)
- [AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html)
- [Strands Agents SDK](https://github.com/strands-agents/strands-agents)
