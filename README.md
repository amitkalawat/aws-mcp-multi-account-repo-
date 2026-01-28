# Multi-Account AWS Operations Agent

Centralized agent for querying AWS resources across multiple accounts using AWS MCP Server, deployed on AWS Bedrock AgentCore.

## Why?

**AWS MCP Server** is a recently launched managed service that exposes 15,000+ AWS APIs through the Model Context Protocol (MCP). It enables AI agents to interact with AWS services using natural language - querying resources, searching documentation, and retrieving operational SOPs.

**The Problem:** Most organizations run multiple AWS accounts (dev, staging, prod, security, shared services). Operations teams typically work from a central account and need visibility across all accounts for monitoring, compliance, and incident response. Manually switching contexts or running scripts across accounts is tedious.

**This Solution:** We built an AI agent that can query any registered AWS account from a single interface. Using cross-account IAM role assumption with organization-scoped trust policies, the agent securely accesses member accounts without storing credentials.

**Why AgentCore?**
- **AgentCore Runtime** provides managed infrastructure for hosting AI agents with built-in scaling, monitoring, and JWT authentication
- **AgentCore Gateway** acts as a unified tool layer, allowing agents to access enterprise tools (including AWS MCP Server via Lambda bridge) through a single authenticated endpoint

The result: Ask questions like "List EC2 instances in production" or "Search AWS docs for Lambda best practices" and get answers across your entire AWS organization.

## Architecture

```
                    ┌──────────┐
                    │   User   │
                    │ (Browser)│
                    └────┬─────┘
                         │ HTTPS
                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CENTRAL OPERATIONS ACCOUNT                          │
│                                                                             │
│                    ┌────────────┐         ┌──────────┐                      │
│                    │ CloudFront │ ──────▶ │    S3    │                      │
│                    │   (CDN)    │         │ (React)  │                      │
│                    └─────┬──────┘         └──────────┘                      │
│                          │                                                  │
│                          │ ID Token                                         │
│                          ▼                                                  │
│  ┌──────────┐      ┌─────────────┐    ID Token    ┌───────────┐            │
│  │ Cognito  │◀────▶│  AgentCore  │ ─────────────▶ │ AgentCore │            │
│  │ User Pool│ OAuth│   Runtime   │                │  Gateway  │            │
│  └──────────┘      │   (Agent)   │                └─────┬─────┘            │
│                    └──────┬──────┘                      │                   │
│                           │                             │ SigV4             │
│                           │ Query accounts              │                   │
│                           ▼                             ▼                   │
│                    ┌─────────────┐               ┌───────────┐             │
│                    │  DynamoDB   │               │  Lambda   │             │
│                    │ (Accounts)  │               │  Bridge   │             │
│                    └─────────────┘               └─────┬─────┘             │
│                                                        │                    │
│       Same Cognito pool authenticates Runtime & Gateway│ SigV4             │
│                                                        ▼                    │
│                                                 ┌───────────┐              │
│                                                 │ AWS MCP   │              │
│                                                 │ Server    │              │
└─────────────────────────────────────────────────┴─────┬─────┴──────────────┘
                                                        │
                                    STS AssumeRole      │
                    ┌───────────────────────────────────┘
                    ▼
        ┌───────────────────────────────────────────────┐
        │              MEMBER ACCOUNTS                   │
        │  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
        │  │  Prod   │  │ Staging │  │   Dev   │  ...   │
        │  │  Role   │  │  Role   │  │  Role   │        │
        │  └─────────┘  └─────────┘  └─────────┘        │
        └───────────────────────────────────────────────┘
```

Full AgentCore stack with 7 CDK stacks: Cognito, DynamoDB, Lambda, Roles, ECR, Gateway, Runtime.
Infrastructure fully automated - single command deploys everything.

**Features:**
- Managed infrastructure with auto-scaling
- JWT authentication via Cognito
- Dynamic account management via DynamoDB
- React frontend with streaming responses

## Quick Start

### Prerequisites

- AWS CLI configured with appropriate permissions
- Node.js 18+ and npm
- Python 3.11+ with virtual environment
- Docker (for agent container builds)

### Deploy Infrastructure

```bash
cd agentcore-gateway/infrastructure
npm install
npx cdk bootstrap  # First time only
npx cdk deploy --all --region us-east-1
```

### Build and Deploy Agent

```bash
# Build container
cd agentcore-gateway/agent
docker build -t central-ops-agent .

# Push to ECR (get repo URL from stack outputs)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
docker tag central-ops-agent:latest <account>.dkr.ecr.us-east-1.amazonaws.com/central-ops-agent-dev:latest
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/central-ops-agent-dev:latest

# Deploy Runtime
cd ../infrastructure
npx cdk deploy -c deployRuntime=true CentralOps-Runtime-dev
```

### Deploy Frontend

```bash
cd agentcore-gateway/frontend
cp .env.example .env  # Fill in values from stack outputs
npm install && npm run build
./scripts/deploy.sh
```

## Available Tools

The agent exposes AWS MCP Server tools through the Gateway:

### Account-Specific Tools (require account_id)
- `aws___call_aws` - Execute AWS CLI commands in target account
- `aws___list_regions` - List available AWS regions

### Global Tools (no account_id needed)
- `aws___search_documentation` - Search AWS docs
- `aws___read_documentation` - Read specific doc pages
- `aws___retrieve_agent_sop` - Get AWS task SOPs
- `aws___suggest_aws_commands` - Get CLI help
- `aws___recommend` - Get doc recommendations

## Example Queries

```
"List all EC2 instances in the production account"
"Search AWS documentation for Lambda best practices"
"Get the SOP for setting up a VPC"
"Show me S3 buckets across all accounts"
"How do I use the aws s3 sync command?"
```

## Project Structure

```
├── README.md                              # This file
├── agentcore-gateway/                     # Main implementation
│   ├── agent/                             # Runtime agent code + Dockerfile
│   ├── frontend/                          # React frontend (Vite + TailwindCSS)
│   ├── infrastructure/                    # CDK TypeScript (7 stacks)
│   │   └── lib/                           # DynamoDB, Cognito, Lambda, Roles, ECR, Gateway, Runtime
│   ├── lambda/                            # Lambda bridge for AWS MCP Server
│   └── tests/                             # Unit tests
├── direct-proxy/                          # Alternative: Local development approach
│   └── README.md                          # Direct proxy documentation
├── ARCHITECTURE_AGENTCOREGATEWAY.md       # Gateway + Lambda architecture details
└── ARCHITECTURE_SECURITY.md               # Enterprise IdP integration guide
```

## Adding New Accounts

1. Deploy `CentralOpsTargetRole` in member account:
   ```bash
   aws cloudformation deploy \
     --template-file agentcore-gateway/infrastructure/member-account-role.yaml \
     --stack-name CentralOpsTargetRole \
     --parameter-overrides CentralAccountId=<central-account-id> \
     --capabilities CAPABILITY_NAMED_IAM
   ```

2. Add to DynamoDB registry:
   ```bash
   aws dynamodb put-item \
     --table-name central-ops-accounts-dev \
     --region us-east-1 \
     --item '{"account_id":{"S":"ACCOUNT_ID"},"name":{"S":"Account Name"},"environment":{"S":"prod"},"enabled":{"BOOL":true}}'
   ```

## Security

- **Read-only access**: All IAM roles use read-only permissions
- **Cross-account**: Uses STS AssumeRole with Organization conditions
- **JWT Authentication**: Cognito-based auth for Gateway and Runtime
- **Audit**: CloudTrail logs all API calls with user attribution

## Documentation

| Document | Description |
|----------|-------------|
| [agentcore-gateway/README.md](agentcore-gateway/README.md) | Detailed Gateway setup and configuration |
| [ARCHITECTURE_AGENTCOREGATEWAY.md](ARCHITECTURE_AGENTCOREGATEWAY.md) | Technical architecture deep-dive |
| [ARCHITECTURE_SECURITY.md](ARCHITECTURE_SECURITY.md) | Enterprise IdP integration (Okta, Azure AD) |
| [direct-proxy/README.md](direct-proxy/README.md) | Alternative local development approach |

## Alternative: Direct Proxy

For local development or simpler deployments without AgentCore infrastructure, see the [direct-proxy/](direct-proxy/) implementation which uses `mcp-proxy-for-aws` subprocess calls.

## References

- [AWS MCP Server Documentation](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html)
- [Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)

## License

This project is licensed under the MIT License.
