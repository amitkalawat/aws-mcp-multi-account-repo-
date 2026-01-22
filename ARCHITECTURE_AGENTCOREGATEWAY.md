# Multi-Account AWS Operations Agent with AgentCore Gateway

## Overview

This document describes an alternative architecture using **AgentCore Gateway** with a **Lambda-based bridge** to call the AWS MCP Server. Since Gateway supports **SigV4 for Lambda targets**, this is simpler than using OAuth for MCP server targets.

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

### Project Structure

```
aws-mcp-multi-account-gateway/
├── infrastructure/
│   ├── gateway.yaml                 # AgentCore Gateway
│   ├── bridge-lambda.yaml           # Bridge Lambda function
│   ├── cognito.yaml                 # Cognito for inbound auth
│   └── member-account-role.yaml     # StackSet for member roles
├── lambda/
│   └── handler.py                   # Bridge Lambda code
└── scripts/
    └── deploy.sh
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
    """Lambda handler for Gateway invocations."""
    body = json.loads(event.get('body', '{}'))
    action = body.get('action')
    accounts = json.loads(os.environ.get('TARGET_ACCOUNTS', '[]'))

    if action == 'list_accounts':
        return {'statusCode': 200, 'body': json.dumps(accounts)}

    elif action == 'query':
        result = call_aws_mcp(
            tool_name=body['tool_name'],
            arguments=body.get('arguments', {}),
            account_id=body['account_id'],
            region=body.get('region', 'us-east-1')
        )
        return {'statusCode': 200, 'body': json.dumps(result, default=str)}

    elif action == 'query_all':
        results = {}
        for acc in accounts:
            try:
                result = call_aws_mcp(
                    tool_name=body['tool_name'],
                    arguments=body.get('arguments', {}),
                    account_id=acc['id'],
                    region=body.get('region', 'us-east-1')
                )
                results[acc['id']] = {'status': 'success', 'data': result}
            except Exception as e:
                results[acc['id']] = {'status': 'error', 'error': str(e)}
        return {'statusCode': 200, 'body': json.dumps(results, default=str)}

    return {'statusCode': 400, 'body': json.dumps({'error': 'Unknown action'})}
```

---

### Infrastructure: Bridge Lambda

**File: `infrastructure/bridge-lambda.yaml`**

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: Bridge Lambda for AWS MCP Server access

Parameters:
  TargetAccounts:
    Type: String
    Description: JSON array of target accounts
  OrganizationId:
    Type: String

Resources:
  BridgeLambdaRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: BridgeLambdaRole
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
        - PolicyName: CrossAccountAssume
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action: sts:AssumeRole
                Resource: arn:aws:iam::*:role/CentralOpsTargetRole
                Condition:
                  StringEquals:
                    aws:PrincipalOrgID: !Ref OrganizationId
        - PolicyName: AWSMCPAccess
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action: aws-mcp:*
                Resource: '*'

  BridgeLambda:
    Type: AWS::Lambda::Function
    Properties:
      FunctionName: aws-mcp-bridge
      Runtime: python3.12
      Handler: handler.handler
      Role: !GetAtt BridgeLambdaRole.Arn
      Timeout: 120
      MemorySize: 256
      Environment:
        Variables:
          TARGET_ACCOUNTS: !Ref TargetAccounts
      Code:
        ZipFile: |
          # Inline code or use S3 bucket for deployment

Outputs:
  LambdaArn:
    Value: !GetAtt BridgeLambda.Arn
```

---

### Infrastructure: AgentCore Gateway

**File: `infrastructure/gateway.yaml`**

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: AgentCore Gateway with Lambda Bridge

Parameters:
  CognitoUserPoolId:
    Type: String
  CognitoClientId:
    Type: String
  BridgeLambdaArn:
    Type: String

Resources:
  GatewayServiceRole:
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
        - PolicyName: InvokeBridgeLambda
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action: lambda:InvokeFunction
                Resource: !Ref BridgeLambdaArn

Outputs:
  GatewayRoleArn:
    Value: !GetAtt GatewayServiceRole.Arn
```

---

### Infrastructure: Cognito (Inbound Auth Only)

**File: `infrastructure/cognito.yaml`**

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: Cognito for Gateway inbound authentication

Resources:
  UserPool:
    Type: AWS::Cognito::UserPool
    Properties:
      UserPoolName: CentralOpsUserPool
      Policies:
        PasswordPolicy:
          MinimumLength: 8

  UserClient:
    Type: AWS::Cognito::UserPoolClient
    Properties:
      UserPoolId: !Ref UserPool
      ClientName: UserClient
      GenerateSecret: false
      ExplicitAuthFlows:
        - ALLOW_USER_PASSWORD_AUTH
        - ALLOW_REFRESH_TOKEN_AUTH

Outputs:
  UserPoolId:
    Value: !Ref UserPool
  UserClientId:
    Value: !Ref UserClient
  DiscoveryUrl:
    Value: !Sub "https://cognito-idp.${AWS::Region}.amazonaws.com/${UserPool}/.well-known/openid-configuration"
```

---

## Deployment

### 1. Deploy Cognito

```bash
aws cloudformation deploy \
  --stack-name central-ops-cognito \
  --template-file infrastructure/cognito.yaml
```

### 2. Deploy Bridge Lambda

```bash
aws cloudformation deploy \
  --stack-name central-ops-bridge \
  --template-file infrastructure/bridge-lambda.yaml \
  --parameter-overrides \
    TargetAccounts='[{"id":"222222222222","name":"Production"},{"id":"333333333333","name":"Staging"}]' \
    OrganizationId=o-xxxxxxxxxx \
  --capabilities CAPABILITY_NAMED_IAM
```

### 3. Create Gateway with Lambda Target

```bash
# Create Gateway
aws bedrock-agentcore-control create-gateway \
  --gateway-name central-ops-gateway \
  --role-arn $GATEWAY_ROLE_ARN \
  --authorizer-configuration '{
    "customJWTAuthorizer": {
      "discoveryUrl": "'$DISCOVERY_URL'",
      "allowedClients": ["'$USER_CLIENT_ID'"]
    }
  }'

# Add Lambda as target
aws bedrock-agentcore-control create-gateway-target \
  --gateway-identifier central-ops-gateway \
  --name bridge-lambda \
  --target-configuration '{
    "lambdaTargetConfiguration": {
      "lambdaArn": "'$BRIDGE_LAMBDA_ARN'"
    }
  }'
```

---

## Comparison: All Three Approaches

| Aspect | Direct Proxy | MCP Server + OAuth | **Lambda Bridge** |
|--------|--------------|--------------------|--------------------|
| **Complexity** | Low | High | **Medium** |
| **OAuth Setup** | None | Required | **None** |
| **Gateway Auth to Target** | N/A | OAuth | **SigV4 (auto)** |
| **Cold Start** | No | No | **Yes** |
| **Extra Components** | Bundled proxy | OAuth provider + MCP server | **Lambda only** |
| **Best For** | Single agent | Complex auth needs | **Gateway + simplicity** |

---

## References

- [AgentCore Gateway Outbound Auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-outbound-auth.html)
- [AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html)
