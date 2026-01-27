# Direct MCP Proxy - Multi-Account AWS Operations Agent

Lightweight agent implementation using **mcp-proxy-for-aws** subprocess calls to interact with AWS MCP Server directly, without AgentCore Runtime or Gateway.

## Overview

This approach runs the agent locally (or in any compute environment like EC2, ECS, Lambda) and uses subprocess calls to the `mcp-proxy-for-aws` CLI tool to communicate with AWS MCP Server. The proxy handles SigV4 authentication automatically using your AWS credentials.

**Key Features:**
- Simple subprocess-based MCP communication
- No infrastructure deployment required (besides IAM roles)
- Credential caching for efficient cross-account operations
- Works anywhere Python runs with AWS credentials

## Architecture

```
                         LOCAL / COMPUTE ENVIRONMENT
+--------------------------------------------------------------------------------+
|                                                                                |
|    +------------------+     subprocess      +------------------+               |
|    | Python Agent     | ------------------> | mcp-proxy-for-   |               |
|    | (MCPClient)      |     JSON-RPC        | aws (uvx)        |               |
|    +------------------+                     +--------+---------+               |
|             |                                        |                         |
|             | STS AssumeRole                         | SigV4 (automatic)       |
|             v                                        v                         |
|    +------------------+                     +------------------+               |
|    | AccountManager   |                     | AWS MCP Server   |               |
|    | (credential      |                     | (aws-mcp.us-east-1               |
|    |  caching)        |                     |  .api.aws)       |               |
|    +--------+---------+                     +--------+---------+               |
|             |                                        |                         |
+-------------+----------------------------------------+--------------------------+
              |                                        |
              |  Assumed credentials                   | MCP tool calls
              v                                        v
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

### How It Works

1. **Agent** calls `MCPClient.call_tool()` with a tool name and arguments
2. **MCPClient** spawns `mcp-proxy-for-aws` as a subprocess with the JSON-RPC request
3. **Proxy** signs the request with SigV4 using current AWS credentials
4. **AWS MCP Server** executes the tool and returns results
5. For cross-account operations, **AccountManager** assumes roles and sets environment credentials before MCP calls

## Prerequisites

- **Python 3.12+** - For running the agent and tests
- **uv** - Package manager and tool runner (for `uvx` command)
- **AWS CLI** - For credential management
- **Valid AWS credentials** - With appropriate permissions
- **mcp-proxy-for-aws** - Installed via `uvx` (no explicit install needed)

### Required IAM Permissions

The executing identity needs these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "aws-mcp:InvokeMcp",
        "aws-mcp:CallReadOnlyTool"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::*:role/CentralOpsTargetRole"
    }
  ]
}
```

### Verify Prerequisites

```bash
./scripts/verify_prerequisites.sh
```

This checks:
1. AWS CLI is installed
2. uv package manager is installed
3. AWS credentials are valid
4. Python 3.11+ is available

## Project Structure

```
direct-proxy/
├── README.md                           # This file
├── agent/
│   ├── __init__.py
│   ├── mcp_client.py                   # MCP proxy wrapper (subprocess calls)
│   └── account_manager.py              # Credential caching and role assumption
├── infrastructure/
│   ├── account-registry.json           # Account config (gitignored, has real IDs)
│   └── account-registry.template.json  # Template for account configuration
├── scripts/
│   ├── verify_prerequisites.sh         # Check all prerequisites
│   ├── test_integration.py             # Full integration test suite
│   └── test_mcp_connection.py          # Basic MCP connection test
└── tests/
    ├── __init__.py
    ├── test_mcp_client.py              # MCPClient unit tests
    └── test_account_manager.py         # AccountManager unit tests
```

## Quick Start

### 1. Set Up Python Environment

```bash
cd direct-proxy

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install boto3 pytest
```

### 2. Configure AWS Credentials

```bash
# Option 1: AWS CLI profile
aws configure

# Option 2: SSO login
aws sso login --profile your-profile

# Verify credentials work
aws sts get-caller-identity
```

### 3. Configure Account Registry

```bash
# Copy template
cp infrastructure/account-registry.template.json infrastructure/account-registry.json

# Edit with your actual account IDs
```

The account registry format:

```json
{
  "accounts": [
    {
      "id": "111111111111",
      "name": "Central Operations",
      "environment": "operations",
      "role": "central"
    },
    {
      "id": "222222222222",
      "name": "Production",
      "environment": "production",
      "role": "workload"
    }
  ]
}
```

### 4. Test MCP Connection

```bash
# Quick connection test
python3 scripts/test_mcp_connection.py

# Full integration test
python3 scripts/test_integration.py
```

### 5. Use the MCP Client

```python
from agent.mcp_client import MCPClient
from agent.account_manager import AccountManager

# Initialize clients
mcp = MCPClient()
accounts = AccountManager("infrastructure/account-registry.json")

# List available tools
tools = mcp.list_tools()
print(f"Available tools: {len(tools)}")

# Call a tool (uses current credentials)
result = mcp.call_tool("aws_ec2_DescribeInstances", {"region": "us-east-1"})

# For cross-account operations
for account in accounts.list_accounts():
    accounts.set_environment_credentials(account["id"])
    result = mcp.call_tool("aws_ec2_DescribeInstances", {"region": "us-east-1"})
    print(f"Account {account['name']}: {result}")
```

## Configuration

### MCPClient Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `server_url` | `https://aws-mcp.us-east-1.api.aws/mcp` | AWS MCP Server endpoint |
| `region` | `us-east-1` | AWS region for metadata |
| `timeout` | `120` | Request timeout in seconds |

### AccountManager Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `registry_path` | `ACCOUNT_REGISTRY` env | Path to account registry JSON |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ACCOUNT_REGISTRY` | Path to account registry JSON file |
| `AWS_ACCESS_KEY_ID` | AWS access key (set by AccountManager) |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key (set by AccountManager) |
| `AWS_SESSION_TOKEN` | AWS session token (set by AccountManager) |

## Testing

### Unit Tests

```bash
cd direct-proxy
source .venv/bin/activate

# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_mcp_client.py -v
pytest tests/test_account_manager.py -v
```

The unit tests mock subprocess calls and boto3 clients, so they run without AWS credentials.

### Integration Tests

```bash
# Requires valid AWS credentials with MCP permissions
python3 scripts/test_integration.py
```

Integration tests verify:
1. AWS identity is valid
2. MCP proxy can connect to AWS MCP Server
3. AccountManager loads registry correctly

## Key Files

### `agent/mcp_client.py` - MCP Proxy Wrapper

The MCPClient class wraps subprocess calls to `mcp-proxy-for-aws`:

```python
class MCPClient:
    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call an MCP tool via subprocess."""

    def list_tools(self) -> list:
        """List available MCP tools."""
```

**Important**: MCP protocol requires `initialize` before `tools/list`. The current implementation is designed for one-shot tool calls. For production use with tool listing, consider maintaining a persistent connection.

### `agent/account_manager.py` - Cross-Account Credential Management

Manages STS role assumption with credential caching:

```python
class AccountManager:
    ROLE_NAME = "CentralOpsTargetRole"
    SESSION_DURATION = 3600  # 1 hour
    REFRESH_BUFFER = timedelta(minutes=5)

    def get_credentials(self, account_id: str) -> AccountCredentials:
        """Get credentials for target account, using cache if valid."""

    def set_environment_credentials(self, account_id: str) -> None:
        """Set AWS credentials as environment variables for MCP proxy."""
```

Credentials are cached and automatically refreshed 5 minutes before expiration.

### `infrastructure/account-registry.json` - Account Configuration

Stores account IDs and metadata. This file is gitignored to prevent exposing real account IDs.

## Comparison with AgentCore Gateway

| Aspect | Direct Proxy | AgentCore Gateway |
|--------|--------------|-------------------|
| **Deployment** | Run anywhere | Managed Runtime |
| **Infrastructure** | Minimal (IAM only) | CDK stacks (Cognito, Lambda, Roles) |
| **Authentication** | AWS credentials | JWT + Workload Identity |
| **Scalability** | Manual | Managed |
| **Client Access** | Direct | API with auth |
| **Multi-tenancy** | No | Yes (Cognito) |
| **Monitoring** | Custom | CloudWatch integration |
| **Complexity** | Low | Medium-High |

### When to Use Direct Proxy

- **Local development and testing** - Quick iteration without deploying infrastructure
- **Single-agent scenarios** - No need for multi-tenant access control
- **Simple deployments** - EC2/ECS/Lambda without AgentCore overhead
- **Cost-sensitive** - No additional AWS services (except IAM)
- **Existing auth** - Already have an auth mechanism in your application

### When to Use AgentCore Gateway

- **Production multi-tenant** - Multiple clients accessing the same agent
- **Managed infrastructure** - Want AWS to handle scaling and availability
- **Enterprise auth** - Need Cognito/OIDC integration
- **Multiple agents** - Deploying and managing multiple agent types
- **Compliance requirements** - Need managed audit trails and access controls

## Gotchas

1. **MCP Protocol Initialization**
   - AWS MCP Server requires `initialize` before `tools/list`
   - One-shot tool calls work without initialization
   - For tool discovery, use the integration test approach

2. **IAM Permissions**
   - Need `aws-mcp:InvokeMcp` and `aws-mcp:CallReadOnlyTool` permissions
   - Cross-account requires `sts:AssumeRole` on target roles
   - Target roles need trust policy for your central account

3. **macOS Python**
   - System Python is externally-managed
   - Always use `.venv` for pip installs

4. **Credential Expiration**
   - Assumed role credentials expire after 1 hour (default)
   - AccountManager refreshes 5 minutes before expiration
   - Long-running agents should handle refresh failures gracefully

## Next Steps

This implementation provides the core MCP client and account management. To build a complete agent:

1. **Add Bedrock Integration** - Use Claude via Bedrock Converse API
2. **Implement Agent Loop** - Parse user queries, call MCP tools, format responses
3. **Add Error Handling** - Retry logic, graceful degradation
4. **Containerize** - Docker image for consistent deployment
5. **Consider AgentCore** - For production multi-tenant scenarios

## References

- [AWS MCP Server Documentation](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html)
- [mcp-proxy-for-aws on PyPI](https://pypi.org/project/mcp-proxy-for-aws/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [AWS STS AssumeRole](https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRole.html)

## License

This project is licensed under the MIT License.
