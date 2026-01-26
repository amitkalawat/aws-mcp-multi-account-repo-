# Multi-Account AWS Operations Agent

Centralized agent for querying AWS resources across multiple accounts using AWS MCP Server.

## Two Implementation Approaches

This repository contains two complete implementations:

| Approach | Directory | Best For |
|----------|-----------|----------|
| **Direct MCP Proxy** | `direct-proxy/` | Local development, single agent, simpler setup |
| **AgentCore Gateway** | `agentcore-gateway/` | Production, managed infrastructure, enterprise |

### Direct MCP Proxy (`direct-proxy/`)

Agent bundles `mcp-proxy-for-aws` to handle SigV4 signing locally.

```
Agent → mcp-proxy-for-aws → AWS MCP Server → Member Accounts
```

**Pros:** Simple, no extra AWS resources, works locally
**Cons:** Proxy bundled with agent, no centralized auth

[→ Direct Proxy Documentation](direct-proxy/README.md)

### AgentCore Gateway (`agentcore-gateway/`)

Full AgentCore stack: Runtime Agent + Gateway + Lambda Bridge.
Infrastructure managed with AWS CDK (TypeScript).

```
Runtime (Agent) → Gateway → Lambda → AWS MCP Server → Member Accounts
```

**Pros:** Managed infrastructure, auto-scaling, production-ready
**Cons:** More AWS resources, Lambda cold starts

[→ AgentCore Gateway Documentation](agentcore-gateway/README.md)

## Quick Start

### Direct Proxy (Development)

```bash
cd direct-proxy
./scripts/verify_prerequisites.sh
source .venv/bin/activate
pytest tests/ -v
python3 scripts/test_integration.py
```

### AgentCore Gateway (Production)

```bash
cd agentcore-gateway
./scripts/deploy.sh
```

## Architecture Comparison

| Feature | Direct Proxy | AgentCore Stack |
|---------|--------------|-----------------|
| SigV4 for MCP | Via bundled proxy | Via Lambda |
| Agent Runtime | Local/Container | AgentCore Runtime |
| Auth | AWS credentials | JWT + Workload Identity |
| Infrastructure | None | CDK (TypeScript) |
| Cold Start | No | Yes (mitigatable) |
| Managed Infrastructure | No | Yes |
| Cross-Account | STS AssumeRole | STS AssumeRole |
| Best Environment | Local/Container | AWS Production |

## Key Constraint: AWS MCP Server Requires SigV4

The AWS MCP Server **only supports SigV4 authentication**, but AgentCore Gateway **doesn't support SigV4 for MCP targets**. Our solutions work around this:

- **Direct Proxy**: Bundle `mcp-proxy-for-aws` in agent container
- **Gateway**: Use Lambda target (supports SigV4) as bridge to AWS MCP Server

## Prerequisites

- AWS Organizations with 2-10 member accounts
- Central operations account for deploying the agent
- IAM roles in each member account (deployed via StackSet)
- Bedrock model access (Claude 3.5 Sonnet)

## Example Queries

```
"List all EC2 instances in the production account"
"Show me S3 buckets across all accounts"
"What Lambda functions exist in staging?"
"Describe EKS clusters in account 222222222222"
"How many RDS instances are running in each account?"
```

## Project Structure

```
├── README.md                              # This file
├── direct-proxy/                          # Direct MCP Proxy implementation
│   ├── agent/                             # Agent code with MCP client
│   ├── infrastructure/                    # Account registry, IAM templates
│   ├── scripts/                           # Setup and test scripts
│   └── tests/                             # Unit tests
├── agentcore-gateway/                     # AgentCore Gateway implementation
│   ├── agent/                             # Runtime agent code
│   ├── infrastructure/                    # CDK TypeScript stack
│   ├── lambda/                            # Lambda bridge function
│   ├── scripts/                           # Deployment scripts
│   └── tests/                             # Unit tests
├── ARCHITECTURE.md                        # Direct proxy architecture details
├── ARCHITECTURE_AGENTCOREGATEWAY.md       # Gateway + Lambda architecture
└── ARCHITECTURE_SECURITY.md               # Enterprise IdP integration
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
