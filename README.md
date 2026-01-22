# Multi-Account AWS Operations Agent

A centralized **read-only** operations agent that queries AWS resources (EC2, S3, RDS, Lambda, ECS, EKS) across **2-10 member accounts** using the **AWS MCP Server** and **Bedrock AgentCore**.

## Problem

Querying AWS resources across multiple accounts typically requires:
- Switching between accounts/profiles manually
- Running separate CLI commands per account
- No unified view of infrastructure

This agent provides a **natural language interface** to query resources across all your AWS accounts from a single place.

## Example Queries

```
"List all EC2 instances in the production account"
"Show me S3 buckets across all accounts"
"What Lambda functions exist in staging?"
"Describe EKS clusters in account 222222222222"
"How many RDS instances are running in each account?"
```

## Architecture Options

This repo provides **three architecture patterns** depending on your requirements:

| Architecture | Best For | Complexity |
|--------------|----------|------------|
| [Direct Proxy](ARCHITECTURE.md) | Single agent, simplest setup | Low |
| [AgentCore Gateway + Lambda](ARCHITECTURE_AGENTCOREGATEWAY.md) | Centralized auth, multi-agent | Medium |
| [Enterprise IdP Integration](ARCHITECTURE_SECURITY.md) | Okta/Azure AD SSO, group-based access | Medium-High |

### Quick Comparison

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Option 1: Direct Proxy (ARCHITECTURE.md)                                   │
│  ─────────────────────────────────────────                                  │
│  Agent Container ──► mcp-proxy-for-aws ──► AWS MCP Server                   │
│                                                                             │
│  ✓ Simplest setup                                                           │
│  ✓ No extra components                                                      │
│  ✗ No centralized auth                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  Option 2: Gateway + Lambda (ARCHITECTURE_AGENTCOREGATEWAY.md)              │
│  ─────────────────────────────────────────────────────────────              │
│  Agent ──► AgentCore Gateway ──► Lambda Bridge ──► AWS MCP Server           │
│                                                                             │
│  ✓ Centralized Gateway                                                      │
│  ✓ SigV4 auth (no OAuth complexity)                                         │
│  ✗ Lambda cold starts                                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  Option 3: Enterprise IdP (ARCHITECTURE_SECURITY.md)                        │
│  ─────────────────────────────────────────────────────                      │
│  User ──► Okta/Azure AD ──► Runtime ──► Gateway ──► Lambda ──► AWS MCP      │
│                                                                             │
│  ✓ SSO with enterprise IdP                                                  │
│  ✓ Group-based account access                                               │
│  ✓ Full audit trail with user identity                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Constraint: AWS MCP Server Requires SigV4

The AWS MCP Server **only supports SigV4 authentication**, but AgentCore Gateway **doesn't support SigV4 for MCP targets**. Our solutions work around this:

- **Direct Proxy**: Bundle `mcp-proxy-for-aws` in agent container
- **Gateway**: Use Lambda target (supports SigV4) as bridge to AWS MCP Server

## Prerequisites

- AWS Organizations with 2-10 member accounts
- Central operations account for deploying the agent
- IAM roles in each member account (deployed via StackSet)
- Bedrock model access (Claude 3.5 Sonnet)

## Quick Start

### 1. Deploy Member Account Roles (StackSet)

```bash
# From management account
aws cloudformation create-stack-set \
  --stack-set-name central-ops-target-roles \
  --template-body file://infrastructure/member-account-role.yaml \
  --parameters ParameterKey=CentralAccountId,ParameterValue=111111111111 \
  --permission-model SERVICE_MANAGED \
  --auto-deployment Enabled=true

aws cloudformation create-stack-instances \
  --stack-set-name central-ops-target-roles \
  --deployment-targets OrganizationalUnitIds=ou-xxxx-xxxxxxxx \
  --regions us-east-1
```

### 2. Configure Account Registry

```bash
cp infrastructure/account-registry.template.json infrastructure/account-registry.json
# Edit with your actual account IDs
```

### 3. Choose Your Architecture

**Option A: Direct Proxy (Simplest)**
```bash
cd agent
docker build -t multi-account-agent .
# Deploy to AgentCore Runtime
```

**Option B: Gateway + Lambda**
```bash
# Deploy Lambda
aws cloudformation deploy \
  --stack-name ops-bridge-lambda \
  --template-file infrastructure/bridge-lambda.yaml \
  --capabilities CAPABILITY_NAMED_IAM

# Create Gateway with Lambda target
aws bedrock-agentcore-control create-gateway ...
```

See detailed instructions in each architecture doc.

## Project Structure

```
├── README.md                              # This file
├── ARCHITECTURE.md                        # Direct proxy architecture
├── ARCHITECTURE_AGENTCOREGATEWAY.md       # Gateway + Lambda architecture  
├── ARCHITECTURE_SECURITY.md               # Enterprise IdP integration
└── infrastructure/
    └── account-registry.template.json     # Account configuration template
```

## Security

- **Read-only access**: All IAM roles use read-only permissions
- **Cross-account**: Uses STS AssumeRole with Organization conditions
- **Audit**: CloudTrail logs all API calls with user attribution
- **Authorization**: Group-based access control (with enterprise IdP)

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Direct proxy pattern with `mcp-proxy-for-aws` |
| [ARCHITECTURE_AGENTCOREGATEWAY.md](ARCHITECTURE_AGENTCOREGATEWAY.md) | AgentCore Gateway with Lambda bridge |
| [ARCHITECTURE_SECURITY.md](ARCHITECTURE_SECURITY.md) | Enterprise IdP integration (Okta, Azure AD, Identity Center) |

## References

- [AWS MCP Server Documentation](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html)
- [mcp-proxy-for-aws](https://github.com/aws/mcp-proxy-for-aws)
- [Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)

## License

This project is licensed under the MIT License.
