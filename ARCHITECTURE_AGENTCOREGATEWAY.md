# Multi-Account AWS Operations Agent with AgentCore Gateway

## Overview

This document describes the architecture using **AgentCore Gateway** with a **Lambda-based bridge** to call the AWS MCP Server. Since Gateway supports **SigV4 for Lambda targets**, this is simpler than using OAuth for MCP server targets.

> **Implementation Status**: Fully implemented with AWS CDK (TypeScript). See `agentcore-gateway/` for the complete working code and `agentcore-gateway/README.md` for deployment instructions.

---

## The Problem

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AGENTCORE GATEWAY TARGET AUTH SUPPORT                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Target Type      │ No Auth │ SigV4 │ OAuth │ API Key                       │
│  ─────────────────┼─────────┼───────┼───────┼─────────                       │
│  Lambda function  │   ❌    │  ✅   │  ❌   │   ❌     ◄── USE THIS          │
│  MCP Server       │   ✅    │  ❌   │  ✅   │   ❌                            │
│  API Gateway      │   ❌    │  ✅   │  ❌   │   ✅                            │
│                                                                             │
│  AWS MCP Server requires SigV4 → Cannot use MCP target directly             │
│  Lambda supports SigV4 → Use Lambda as bridge!                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Solution: Lambda Bridge

Deploy a **Lambda function** that:
1. Is invoked by AgentCore Gateway via SigV4 (automatic with service role)
2. Assumes IAM roles for target accounts
3. Calls AWS MCP Server with SigV4

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         CENTRAL OPERATIONS ACCOUNT                           │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                      AGENTCORE GATEWAY                                 │  │
│  │                                                                        │  │
│  │  ┌──────────────────┐         ┌─────────────────────────────────────┐  │  │
│  │  │  Inbound Auth    │         │  Lambda Target                      │  │  │
│  │  │  (JWT/Cognito)   │         │  (SigV4 via service role)           │  │  │
│  │  └────────┬─────────┘         └──────────────┬──────────────────────┘  │  │
│  │           │                                  │                         │  │
│  └───────────┼──────────────────────────────────┼─────────────────────────┘  │
│              │                                  │                            │
│              │ User Request                     │ SigV4 (automatic)          │
│              ▼                                  ▼                            │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                    BRIDGE LAMBDA                                        │ │
│  │                                                                         │ │
│  │  ┌─────────────────┐    ┌──────────────────┐    ┌───────────────────┐  │ │
│  │  │ Parse request   │───▶│ AssumeRole for   │───▶│ Call AWS MCP      │  │ │
│  │  │                 │    │ Target Account   │    │ Server (SigV4)    │  │ │
│  │  └─────────────────┘    └──────────────────┘    └─────────┬─────────┘  │ │
│  │                                                           │            │ │
│  └───────────────────────────────────────────────────────────┼────────────┘ │
│                                                              │              │
│                                                              ▼              │
│                                          ┌────────────────────────────────┐ │
│                                          │      AWS MCP SERVER            │ │
│                                          │  https://aws-mcp.us-east-1...  │ │
│                                          │  (SigV4 authenticated)         │ │
│                                          └────────────────────────────────┘ │
│                                                              │              │
└──────────────────────────────────────────────────────────────┼──────────────┘
                                                               │
                    ┌──────────────────────────────────────────┘
                    │ Cross-Account AssumeRole
                    ▼
     ┌──────────────────────────────────────────────────────────────────┐
     │                      MEMBER ACCOUNTS                             │
     │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
     │  │ Account 1  │  │ Account 2  │  │ Account 3  │  │ Account N  │  │
     │  │ TargetRole │  │ TargetRole │  │ TargetRole │  │ TargetRole │  │
     │  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
     └──────────────────────────────────────────────────────────────────┘
```

---

## Why Lambda?

| Aspect | Lambda Target | MCP Server Target |
|--------|---------------|-------------------|
| **Gateway Auth** | SigV4 (automatic) | OAuth only |
| **Setup Complexity** | Simple (IAM role) | Complex (OAuth provider) |
| **No Extra Auth Config** | ✅ | ❌ |
| **Cold Start** | Yes (mitigate with provisioned) | N/A |

---

## Implementation

> **Note**: The implementation uses AWS CDK (TypeScript) instead of CloudFormation YAML.
> The examples below show the architectural concepts; see `agentcore-gateway/infrastructure/lib/` for the actual CDK code.

### Project Structure

```
agentcore-gateway/
├── agent/
│   ├── central_ops_agent.py         # Agent code (Bedrock Converse API)
│   ├── Dockerfile                   # Container for AgentCore Runtime
│   └── requirements.txt
├── infrastructure/
│   ├── bin/infrastructure.ts        # CDK app entry point
│   ├── lib/
│   │   ├── cognito-stack.ts         # Cognito User Pool
│   │   ├── lambda-stack.ts          # Bridge Lambda function
│   │   ├── roles-stack.ts           # Gateway and Runtime IAM roles
│   │   ├── member-account-stack.ts  # Member account target role
│   │   ├── ecr-stack.ts             # ECR repository for agent container
│   │   ├── gateway-stack.ts         # AgentCore Gateway and Lambda target
│   │   └── runtime-stack.ts         # AgentCore Runtime and endpoint
│   └── config/accounts.json         # Account configuration (gitignored)
├── lambda/
│   └── handler.py                   # Bridge Lambda code
└── tests/
```

---

### Bridge Lambda Implementation

**File: `lambda/handler.py`**

```python
import os
import json
import boto3
from datetime import datetime, timezone, timedelta
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import urllib.request

AWS_MCP_ENDPOINT = "https://aws-mcp.us-east-1.api.aws/mcp"
TARGET_ROLE_NAME = "CentralOpsTargetRole"

# Simple in-memory cache (persists across warm invocations)
credential_cache = {}


def get_credentials(account_id: str) -> dict:
    """Get or refresh credentials for target account."""
    cache_key = account_id
    now = datetime.now(timezone.utc)

    if cache_key in credential_cache:
        creds = credential_cache[cache_key]
        if now + timedelta(minutes=5) < creds['expiration']:
            return creds

    sts = boto3.client('sts')
    response = sts.assume_role(
        RoleArn=f"arn:aws:iam::{account_id}:role/{TARGET_ROLE_NAME}",
        RoleSessionName=f"Bridge-{account_id}",
        DurationSeconds=3600
    )

    creds = {
        'access_key_id': response['Credentials']['AccessKeyId'],
        'secret_access_key': response['Credentials']['SecretAccessKey'],
        'session_token': response['Credentials']['SessionToken'],
        'expiration': response['Credentials']['Expiration']
    }
    credential_cache[cache_key] = creds
    return creds


def call_aws_mcp(tool_name: str, arguments: dict, account_id: str, region: str = "us-east-1") -> dict:
    """Call AWS MCP Server with SigV4."""
    creds = get_credentials(account_id)

    mcp_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments}
    }

    session = boto3.Session(
        aws_access_key_id=creds['access_key_id'],
        aws_secret_access_key=creds['secret_access_key'],
        aws_session_token=creds['session_token'],
        region_name=region
    )

    request = AWSRequest(
        method='POST',
        url=AWS_MCP_ENDPOINT,
        data=json.dumps(mcp_request),
        headers={'Content-Type': 'application/json'}
    )
    SigV4Auth(session.get_credentials(), 'aws-mcp', region).add_auth(request)

    req = urllib.request.Request(
        AWS_MCP_ENDPOINT,
        data=request.body.encode(),
        headers=dict(request.headers),
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def handler(event, context):
    """Lambda handler for Gateway invocations.

    Gateway format:
    - event = tool arguments directly (e.g., {"account_id": "123", "tool_name": "aws___list_regions"})
    - context.client_context.custom contains bedrockAgentCoreToolName
    """
    accounts = json.loads(os.environ.get('TARGET_ACCOUNTS', '[]'))

    # Get tool name from Gateway context
    tool_name = None
    if hasattr(context, 'client_context') and context.client_context:
        custom = getattr(context.client_context, 'custom', None)
        if custom and 'bedrockAgentCoreToolName' in custom:
            full_tool_name = custom['bedrockAgentCoreToolName']
            # Strip target prefix (e.g., "bridge-lambda___query" -> "query")
            tool_name = full_tool_name.split('___', 1)[1] if '___' in full_tool_name else full_tool_name

    if tool_name == 'list_accounts':
        return accounts  # Gateway expects direct return, not statusCode wrapper

    elif tool_name == 'query':
        result = call_aws_mcp(
            tool_name=event.get('tool_name'),
            arguments=event.get('arguments', {}),
            account_id=event.get('account_id'),
            region=event.get('region', 'us-east-1')
        )
        return result

    elif tool_name == 'query_all':
        results = {}
        for acc in accounts:
            try:
                result = call_aws_mcp(
                    tool_name=event.get('tool_name'),
                    arguments=event.get('arguments', {}),
                    account_id=acc['id'],
                    region=event.get('region', 'us-east-1')
                )
                results[acc['id']] = {'status': 'success', 'data': result}
            except Exception as e:
                results[acc['id']] = {'status': 'error', 'error': str(e)}
        return results

    return {'error': f'Unknown tool: {tool_name}'}
```

---

### CDK Infrastructure

The infrastructure is implemented in TypeScript CDK. Key stacks:

**`lib/lambda-stack.ts`** - Creates the Bridge Lambda with:
- Cross-account AssumeRole permissions
- AWS MCP access permissions (`aws-mcp:InvokeMcp`, `aws-mcp:CallReadOnlyTool`)
- Python 3.12 runtime with 120s timeout

**`lib/gateway-stack.ts`** - Creates AgentCore Gateway with:
- MCP protocol type
- JWT authorizer (Cognito)
- Lambda target with tool schemas for `list_accounts`, `query`, `query_all`

**`lib/cognito-stack.ts`** - Creates Cognito User Pool with:
- Password auth flow for testing
- OIDC discovery URL for JWT validation

See `agentcore-gateway/infrastructure/lib/` for the complete CDK code.

---

## Deployment

The entire infrastructure is deployed with a single CDK command:

```bash
cd agentcore-gateway/infrastructure

# Install dependencies
npm install

# Bootstrap CDK (first time only)
npx cdk bootstrap

# Deploy all 6 stacks
npx cdk deploy --all -c region=us-west-2 -c centralAccountId=YOUR_ACCOUNT_ID
```

This deploys:
1. **CognitoStack** - User Pool and Client for JWT authentication
2. **LambdaStack** - Bridge Lambda function with cross-account permissions
3. **RolesStack** - Gateway and Runtime IAM roles
4. **EcrStack** - ECR repository for agent container
5. **GatewayStack** - AgentCore Gateway with Lambda target and JWT authorizer
6. **MemberAccountStack** - Target role for cross-account access

See `agentcore-gateway/README.md` for detailed deployment instructions and testing.

---

## Comparison: Implementation Approaches

| Aspect | Direct Proxy | **Lambda Bridge (CDK)** |
|--------|--------------|-------------------------|
| **Infrastructure** | None (IAM only) | 6 CDK stacks (fully automated) |
| **Deployment** | Run anywhere | `npx cdk deploy --all` |
| **OAuth Setup** | None | None (uses Cognito JWT) |
| **Gateway Auth** | N/A | SigV4 (automatic) |
| **Cold Start** | No | Yes (mitigatable) |
| **Managed Infrastructure** | No | Yes (AgentCore) |
| **Multi-tenant** | No | Yes (Cognito users) |
| **Best For** | Local dev, simple | Production, enterprise |

---

## Key Learnings from Implementation

- **CDK Version**: Requires `aws-cdk-lib` version 2.236.0+ for `aws-bedrockagentcore` module
- **JWT Auth**: For Cognito ID tokens, only configure `allowedAudience` (not `allowedClients`) - ID tokens have `aud` claim but not `client_id`
- **Gateway Event Format**: When Gateway invokes Lambda, arguments are in `event` directly, tool name is in `context.client_context.custom['bedrockAgentCoreToolName']`
- **MCP Sessions**: AWS MCP Server requires `initialize` before `tools/call` - Lambda must maintain session IDs
- **Region**: AWS MCP Server is only available in `us-east-1` - Lambda signs requests to this region regardless of deployment region

## References

- [AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)
- [AgentCore Gateway Lambda Targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html)
- [AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html)
- [AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/home.html)
