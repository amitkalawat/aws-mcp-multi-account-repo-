# AgentCore Gateway Integration Guide

## Overview

This document explores how to integrate our multi-account AWS operations agent with **Amazon Bedrock AgentCore Gateway**. It addresses the key challenges, limitations, and provides workarounds to make the architecture work with Gateway's current capabilities.

> **Related Document:** See [ARCHITECTURE.md](./ARCHITECTURE.md) for the base architecture using direct MCP proxy.

---

## The Core Challenge

### Why Can't We Simply Use Gateway with AWS MCP Server?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         THE PROBLEM                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  AWS MCP Server requires:          AgentCore Gateway supports:              │
│  ─────────────────────────         ───────────────────────────              │
│  ✅ SigV4 authentication           ❌ SigV4 for MCP targets                 │
│                                    ✅ OAuth (client credentials)            │
│                                    ✅ No auth (not recommended)             │
│                                                                             │
│  RESULT: Gateway cannot directly call AWS MCP Server                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Gateway Outbound Authentication Compatibility Matrix

| Target Type | No Auth | Gateway IAM Role (SigV4) | OAuth (Client Creds) | OAuth (Auth Code) | API Key |
|-------------|---------|--------------------------|----------------------|-------------------|---------|
| **Lambda function** | ❌ | ✅ **Yes** | ❌ | ❌ | ❌ |
| **MCP server** | ✅ | ❌ **No** | ✅ | ❌ | ❌ |
| **API Gateway stage** | ❌ | ✅ | ❌ | ❌ | ✅ |
| **OpenAPI schema** | ❌ | ❌ | ✅ | ✅ | ✅ |
| **Smithy schema** | ❌ | ✅ | ✅ | ✅ | ❌ |

**Key Insight:** Lambda functions support IAM/SigV4, but MCP servers don't. This is our path forward.

---

## Known Challenges with AgentCore Gateway

### 1. MCP Authorization Specification Gaps

| Challenge | Description | Impact |
|-----------|-------------|--------|
| **RFC 8707 Not Supported** | Most identity providers don't implement Resource Indicators | Token scoping issues |
| **Dynamic Client Registration** | MCP expects anonymous DCR; enterprises avoid it | Security vs compliance tension |
| **Single Auth Mode** | Runtime supports IAM OR JWT, not both | Need multiple runtime versions |

### 2. Tool Discovery at Scale

| Challenge | Description | Workaround |
|-----------|-------------|------------|
| **Tool Overload** | Too many tools → agent hallucinations | Use semantic search, limit tool sets |
| **Sync Delays** | Large tool sets take minutes to sync | Pre-sync during deployment |
| **Schema Changes** | Need to call `SynchronizeGatewayTargets` | Automate in CI/CD pipeline |

### 3. Protocol Requirements

| Requirement | Details |
|-------------|---------|
| **MCP Versions** | Only 2025-06-18 and 2025-03-26 supported |
| **Transport** | Stateless streamable-HTTP only |
| **URL Encoding** | Server URLs must be URL-encoded |
| **User-Agent** | MCP Python SDK missing headers (Issue #1664) |

---

## Solution Architectures

We present three approaches to integrate with AgentCore Gateway, each with trade-offs.

### Solution 1: Lambda Wrapper for AWS Operations (Recommended)

**Concept:** Create Lambda functions that call AWS APIs directly (with STS AssumeRole for cross-account). Expose these Lambdas through Gateway.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AGENTCORE RUNTIME                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                              AGENT                                    │  │
│  │  ┌─────────────────┐                                                  │  │
│  │  │  Agent Logic    │                                                  │  │
│  │  │  (Strands/      │                                                  │  │
│  │  │   LangGraph)    │                                                  │  │
│  │  └────────┬────────┘                                                  │  │
│  │           │                                                           │  │
│  └───────────┼───────────────────────────────────────────────────────────┘  │
│              │ MCP over HTTP (OAuth or IAM)                                 │
│              ▼                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                     AGENTCORE GATEWAY                                 │  │
│  │                                                                       │  │
│  │   Tools:                                                              │  │
│  │   ├── list_accounts          (Lambda target)                         │  │
│  │   ├── describe_ec2_instances (Lambda target)                         │  │
│  │   ├── list_s3_buckets        (Lambda target)                         │  │
│  │   ├── describe_rds_instances (Lambda target)                         │  │
│  │   ├── list_lambda_functions  (Lambda target)                         │  │
│  │   └── ... more operations                                            │  │
│  │                                                                       │  │
│  │   Outbound Auth: Gateway IAM Role (SigV4) ──────────┐                │  │
│  └───────────────────────────────────────────────────────┼──────────────┘  │
│                                                          │                  │
└──────────────────────────────────────────────────────────┼──────────────────┘
                                                           │
                        ┌──────────────────────────────────▼─────────────────┐
                        │              AWS LAMBDA FUNCTIONS                  │
                        │                                                    │
                        │  ┌────────────────────────────────────────────┐   │
                        │  │  Each Lambda:                              │   │
                        │  │  1. Receives tool call from Gateway        │   │
                        │  │  2. Calls STS AssumeRole (cross-account)   │   │
                        │  │  3. Executes AWS API with temp creds       │   │
                        │  │  4. Returns results                        │   │
                        │  └────────────────────────────────────────────┘   │
                        │                         │                          │
                        └─────────────────────────┼──────────────────────────┘
                                                  │ STS AssumeRole
                                                  ▼
                        ┌─────────────────────────────────────────────────────┐
                        │              MEMBER AWS ACCOUNTS                    │
                        │  ┌─────────┐  ┌─────────┐  ┌─────────┐             │
                        │  │ Account │  │ Account │  │ Account │             │
                        │  │   A     │  │   B     │  │   C     │             │
                        │  └─────────┘  └─────────┘  └─────────┘             │
                        └─────────────────────────────────────────────────────┘
```

**Pros:**
- ✅ Uses Gateway's managed infrastructure
- ✅ Centralized tool discovery and management
- ✅ IAM-based auth (no OAuth complexity)
- ✅ Works with cross-account access

**Cons:**
- ❌ Need to implement each AWS operation as a Lambda
- ❌ More Lambda functions to maintain
- ❌ Doesn't use AWS MCP Server's 15,000+ APIs directly

---

### Solution 2: Hybrid - Gateway + Direct MCP Proxy

**Concept:** Use Gateway for custom tools and orchestration, but call AWS MCP Server directly from the agent using `mcp-proxy-for-aws`.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AGENTCORE RUNTIME                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                              AGENT                                    │  │
│  │  ┌─────────────────┐      ┌─────────────────────────────────┐        │  │
│  │  │  Agent Logic    │      │     mcp-proxy-for-aws           │        │  │
│  │  │                 │─────▶│     (bundled in agent)          │────────┼──┼──▶ AWS MCP Server
│  │  │                 │      │                                 │        │  │    (SigV4)
│  │  └────────┬────────┘      └─────────────────────────────────┘        │  │
│  │           │                                                           │  │
│  └───────────┼───────────────────────────────────────────────────────────┘  │
│              │ MCP over HTTP                                                │
│              ▼                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                     AGENTCORE GATEWAY                                 │  │
│  │                                                                       │  │
│  │   Custom Tools Only:                                                  │  │
│  │   ├── list_accounts          (Lambda target)                         │  │
│  │   ├── switch_account         (Lambda target)                         │  │
│  │   ├── get_account_metadata   (Lambda target)                         │  │
│  │   └── aggregate_results      (Lambda target)                         │  │
│  │                                                                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Pros:**
- ✅ Full access to AWS MCP Server's 15,000+ APIs
- ✅ Gateway handles custom orchestration tools
- ✅ Best of both worlds

**Cons:**
- ❌ Two integration paths to maintain
- ❌ Agent code more complex
- ❌ Credential management in two places

---

### Solution 3: MCP Server Wrapper Lambda

**Concept:** Create a Lambda that wraps the AWS MCP Server, handling SigV4 internally. Expose this Lambda through Gateway as an MCP server target.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AGENTCORE GATEWAY                                   │
│                                                                             │
│   MCP Server Target:                                                        │
│   └── aws-mcp-wrapper (Lambda → MCP server interface)                      │
│                                                                             │
│   Outbound Auth: Gateway IAM Role                                           │
└───────────────────────────────────────────────────────────────────────────┬─┘
                                                                            │
                        ┌───────────────────────────────────────────────────▼─┐
                        │          MCP WRAPPER LAMBDA                         │
                        │                                                     │
                        │  1. Receives MCP request from Gateway               │
                        │  2. Parses tool name and arguments                  │
                        │  3. Calls STS AssumeRole (if cross-account)        │
                        │  4. Calls AWS MCP Server with SigV4                 │
                        │  5. Returns MCP-formatted response                  │
                        │                                                     │
                        └───────────────────────────────────────────────────┬─┘
                                                                            │
                        ┌───────────────────────────────────────────────────▼─┐
                        │          AWS MCP SERVER                             │
                        │          https://aws-mcp.us-east-1.api.aws/mcp     │
                        │                                                     │
                        │          (SigV4 authenticated)                      │
                        └─────────────────────────────────────────────────────┘
```

**Pros:**
- ✅ Single Gateway integration
- ✅ Proxies all AWS MCP Server capabilities
- ✅ Centralized credential management

**Cons:**
- ❌ Lambda cold starts add latency
- ❌ Need to handle MCP protocol translation
- ❌ Lambda timeout limits for long operations

---

## Recommended Approach: Solution 1 (Lambda Wrapper)

For production deployments, we recommend **Solution 1** because:

1. **Simplicity**: Each AWS operation is a discrete Lambda function
2. **Maintainability**: Clear separation of concerns
3. **Security**: IAM roles for all authentication
4. **Scalability**: Lambda scales automatically
5. **Gateway Benefits**: Full tool discovery, semantic search, unified auth

---

## Implementation Details

### Step 1: Create Gateway with IAM Authorization

```python
# scripts/create_gateway.py
import boto3

def create_gateway_with_iam_auth():
    client = boto3.client('bedrock-agentcore', region_name='us-east-1')

    # Create gateway with IAM authorization
    response = client.create_gateway(
        name='central-ops-gateway',
        description='Multi-account AWS operations gateway',
        protocolType='MCP',
        authorizerConfiguration={
            'awsIamAuthorizer': {}  # Use IAM/SigV4 for inbound auth
        }
    )

    return response['gatewayId']
```

### Step 2: Create Lambda Functions for AWS Operations

**File: `lambda/aws_operations/ec2_operations.py`**

```python
import boto3
import json
from typing import Dict, Any

# Tool schema for Gateway
TOOL_SCHEMA = {
    "name": "describe_ec2_instances",
    "description": "Describe EC2 instances in a target AWS account",
    "inputSchema": {
        "type": "object",
        "properties": {
            "account_id": {
                "type": "string",
                "description": "Target AWS account ID (12 digits)"
            },
            "region": {
                "type": "string",
                "description": "AWS region (default: us-east-1)",
                "default": "us-east-1"
            },
            "instance_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of instance IDs to filter"
            },
            "filters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "Name": {"type": "string"},
                        "Values": {"type": "array", "items": {"type": "string"}}
                    }
                },
                "description": "Optional filters (e.g., instance-state-name)"
            }
        },
        "required": ["account_id"]
    }
}


def assume_role(account_id: str, region: str = 'us-east-1') -> boto3.Session:
    """Assume role in target account and return a boto3 session."""
    sts = boto3.client('sts')

    role_arn = f"arn:aws:iam::{account_id}:role/CentralOpsTargetRole"

    response = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName=f"GatewayOps-{account_id}",
        DurationSeconds=900  # 15 minutes for Lambda
    )

    credentials = response['Credentials']

    return boto3.Session(
        aws_access_key_id=credentials['AccessKeyId'],
        aws_secret_access_key=credentials['SecretAccessKey'],
        aws_session_token=credentials['SessionToken'],
        region_name=region
    )


def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Lambda handler for EC2 describe instances.

    Receives tool call from AgentCore Gateway.
    """
    # Parse input from Gateway
    account_id = event.get('account_id')
    region = event.get('region', 'us-east-1')
    instance_ids = event.get('instance_ids', [])
    filters = event.get('filters', [])

    if not account_id:
        return {
            "error": "account_id is required"
        }

    try:
        # Assume role in target account
        session = assume_role(account_id, region)
        ec2 = session.client('ec2')

        # Build request parameters
        params = {}
        if instance_ids:
            params['InstanceIds'] = instance_ids
        if filters:
            params['Filters'] = filters

        # Describe instances
        response = ec2.describe_instances(**params)

        # Format response
        instances = []
        for reservation in response.get('Reservations', []):
            for instance in reservation.get('Instances', []):
                instances.append({
                    'InstanceId': instance.get('InstanceId'),
                    'InstanceType': instance.get('InstanceType'),
                    'State': instance.get('State', {}).get('Name'),
                    'PrivateIpAddress': instance.get('PrivateIpAddress'),
                    'PublicIpAddress': instance.get('PublicIpAddress'),
                    'LaunchTime': instance.get('LaunchTime', '').isoformat() if instance.get('LaunchTime') else None,
                    'Tags': {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])}
                })

        return {
            "account_id": account_id,
            "region": region,
            "instance_count": len(instances),
            "instances": instances
        }

    except Exception as e:
        return {
            "error": str(e),
            "account_id": account_id,
            "region": region
        }
```

### Step 3: Register Lambda as Gateway Target

```python
# scripts/register_lambda_targets.py
import boto3

def register_ec2_lambda_target(gateway_id: str, lambda_arn: str):
    client = boto3.client('bedrock-agentcore', region_name='us-east-1')

    response = client.create_gateway_target(
        gatewayIdentifier=gateway_id,
        name='describe-ec2-instances',
        targetConfiguration={
            'lambdaConfiguration': {
                'lambdaArn': lambda_arn,
                'toolSchema': {
                    'inlinePayload': [{
                        'name': 'describe_ec2_instances',
                        'description': 'Describe EC2 instances in a target AWS account',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {
                                'account_id': {
                                    'type': 'string',
                                    'description': 'Target AWS account ID'
                                },
                                'region': {
                                    'type': 'string',
                                    'description': 'AWS region',
                                    'default': 'us-east-1'
                                }
                            },
                            'required': ['account_id']
                        }
                    }]
                },
                'credentialProviderConfigurations': [{
                    'credentialProviderType': 'GATEWAY_IAM_ROLE'
                }]
            }
        }
    )

    return response['targetId']
```

### Step 4: Agent Integration with Gateway

**File: `agent/gateway_agent.py`**

```python
import boto3
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client


class GatewayOpsAgent:
    """
    Operations agent that uses AgentCore Gateway for tool access.

    All AWS operations are exposed as Lambda-backed tools in the Gateway.
    """

    SYSTEM_PROMPT = """You are a centralized operations agent for querying AWS resources across multiple accounts.

CAPABILITIES:
- Query EC2, S3, RDS, Lambda, ECS, EKS resources (READ-ONLY)
- Access multiple AWS accounts from a central operations account
- Aggregate data across accounts

AVAILABLE TOOLS (via Gateway):
- describe_ec2_instances: Get EC2 instances in an account
- list_s3_buckets: List S3 buckets in an account
- describe_rds_instances: Get RDS instances in an account
- list_lambda_functions: List Lambda functions in an account
- list_ecs_clusters: List ECS clusters in an account
- describe_eks_clusters: Get EKS cluster details

Always specify the account_id parameter for cross-account operations."""

    def __init__(self, gateway_url: str, region: str = 'us-east-1'):
        self.gateway_url = gateway_url
        self.region = region

    def _create_mcp_client(self):
        """Create MCP client with IAM authentication to Gateway."""
        mcp_factory = lambda: aws_iam_streamablehttp_client(
            endpoint=self.gateway_url,
            aws_region=self.region,
            aws_service="bedrock-agentcore"
        )
        return MCPClient(mcp_factory)

    def run(self, query: str) -> str:
        """Execute a query using Gateway-backed tools."""
        mcp_client = self._create_mcp_client()

        model = BedrockModel(
            model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
            temperature=0.0
        )

        with mcp_client:
            agent = Agent(
                model=model,
                tools=[mcp_client],
                system_prompt=self.SYSTEM_PROMPT
            )

            response = agent(query)
            return str(response)


# Example usage
if __name__ == "__main__":
    gateway_url = "https://gateway-xxxx.bedrock-agentcore.us-east-1.amazonaws.com"

    agent = GatewayOpsAgent(gateway_url)

    result = agent.run("List all EC2 instances in account 222222222222")
    print(result)
```

---

## Lambda Functions to Implement

For complete coverage of our target services, implement these Lambdas:

| Lambda Function | AWS Service | Operation |
|-----------------|-------------|-----------|
| `describe_ec2_instances` | EC2 | DescribeInstances |
| `describe_ec2_vpcs` | EC2 | DescribeVpcs |
| `describe_ec2_security_groups` | EC2 | DescribeSecurityGroups |
| `list_s3_buckets` | S3 | ListBuckets |
| `get_s3_bucket_info` | S3 | GetBucketLocation, GetBucketTagging |
| `describe_rds_instances` | RDS | DescribeDBInstances |
| `describe_rds_clusters` | RDS | DescribeDBClusters |
| `list_lambda_functions` | Lambda | ListFunctions |
| `get_lambda_function` | Lambda | GetFunction |
| `list_ecs_clusters` | ECS | ListClusters, DescribeClusters |
| `list_ecs_services` | ECS | ListServices, DescribeServices |
| `describe_eks_clusters` | EKS | ListClusters, DescribeCluster |
| `list_cloudwatch_alarms` | CloudWatch | DescribeAlarms |
| `get_cloudwatch_metrics` | CloudWatch | GetMetricData |

---

## IAM Configuration for Gateway

### Gateway Execution Role

```yaml
# infrastructure/gateway-role.yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: IAM role for AgentCore Gateway

Parameters:
  OrganizationId:
    Type: String

Resources:
  GatewayExecutionRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: CentralOpsGatewayRole
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: bedrock-agentcore.amazonaws.com
            Action: sts:AssumeRole
      Policies:
        - PolicyName: InvokeLambdaTargets
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - lambda:InvokeFunction
                Resource:
                  - !Sub arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:central-ops-*
        - PolicyName: CrossAccountAssumeRole
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action: sts:AssumeRole
                Resource: arn:aws:iam::*:role/CentralOpsTargetRole
                Condition:
                  StringEquals:
                    aws:PrincipalOrgID: !Ref OrganizationId
```

### Lambda Execution Role

```yaml
  LambdaExecutionRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: CentralOpsLambdaRole
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: lambda.amazonaws.com
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
      Policies:
        - PolicyName: CrossAccountAssumeRole
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action: sts:AssumeRole
                Resource: arn:aws:iam::*:role/CentralOpsTargetRole
                Condition:
                  StringEquals:
                    aws:PrincipalOrgID: !Ref OrganizationId
```

---

## Comparison: Direct MCP Proxy vs Gateway

| Aspect | Direct MCP Proxy | AgentCore Gateway |
|--------|------------------|-------------------|
| **AWS MCP Server Access** | ✅ Full 15,000+ APIs | ⚠️ Via Lambda wrappers |
| **Tool Management** | ❌ Manual | ✅ Centralized discovery |
| **Authentication** | ✅ SigV4 to MCP | ✅ IAM to Gateway |
| **Scaling** | Manual | ✅ Managed |
| **Semantic Search** | ❌ No | ✅ Built-in |
| **Multi-Agent** | ⚠️ Complex | ✅ Shared tools |
| **Latency** | Lower | Higher (Lambda cold starts) |
| **Maintenance** | MCP proxy updates | Lambda + Gateway |

---

## When to Use Each Approach

### Use Direct MCP Proxy (ARCHITECTURE.md) When:
- Need access to ALL AWS MCP Server APIs
- Latency is critical
- Single agent deployment
- Simpler architecture preferred

### Use AgentCore Gateway When:
- Multiple agents share tools
- Need centralized tool management
- Want semantic tool discovery
- Building enterprise-scale platform
- Prefer managed infrastructure

---

## References

- [AgentCore Gateway Documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)
- [Gateway Outbound Auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-outbound-auth.html)
- [MCP Server Targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-MCPservers.html)
- [Lambda Targets](https://dev.to/aws-heroes/amazon-bedrock-agentcore-gateway-part-3-exposing-existing-aws-lambda-function-via-mcp-and-gateway-2ga)
- [MCP Proxy for AWS](https://github.com/aws/mcp-proxy-for-aws)
- [IAM Auth for Gateway](https://dev.classmethod.jp/en/articles/agentcore-runtime-gateway-iam-auth/)
- [Run MCP Servers with Lambda](https://github.com/awslabs/run-model-context-protocol-servers-with-aws-lambda)
- [Transform MCP Architecture with Gateway](https://aws.amazon.com/blogs/machine-learning/transform-your-mcp-architecture-unite-mcp-servers-through-agentcore-gateway/)
