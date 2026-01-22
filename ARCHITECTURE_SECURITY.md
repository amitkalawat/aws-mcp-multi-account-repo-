# Identity Provider Integration for Multi-Account Operations Agent

## Overview

This document explores integration patterns for connecting the multi-account operations agent to enterprise identity providers (Okta, Azure AD, AWS Identity Center). The goal is to leverage existing SSO infrastructure rather than creating separate authentication silos.

---

## End-to-End User Flow

### Complete Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    END USER FLOW                                            │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

     ┌──────────┐                                                                              
     │   User   │                                                                              
     └────┬─────┘                                                                              
          │                                                                                    
          │ ① Login (OAuth/OIDC)                                                               
          ▼                                                                                    
┌──────────────────┐         ┌─────────────────────────────────────────────────────────────┐  
│  Enterprise IdP  │◀───────▶│  Cognito User Pool (federated)                             │  
│  (Okta/Azure AD) │  OIDC   │  OR direct OIDC from IdP                                   │  
└──────────────────┘         └────────────────────┬────────────────────────────────────────┘  
                                                  │                                            
                                                  │ ② JWT Access Token                        
                                                  ▼                                            
                             ┌─────────────────────────────────────────────────────────────┐  
                             │                    CHATBOT UI                               │  
                             │  (Web App / Slack Bot / Teams Bot / CLI)                    │  
                             └────────────────────┬────────────────────────────────────────┘  
                                                  │                                            
                                                  │ ③ User Query + JWT Bearer Token           
                                                  │    "List EC2 instances in prod account"   
                                                  ▼                                            
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                              AGENTCORE RUNTIME                                              │
│  ┌───────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                           MAIN AGENT                                                  │  │
│  │                                                                                       │  │
│  │  ④ Validate JWT (inbound auth)                                                        │  │
│  │  ⑤ Extract user identity + groups from claims                                         │  │
│  │  ⑥ Process query with LLM (Bedrock Claude)                                            │  │
│  │  ⑦ Determine: needs AWS resource data → call Gateway                                  │  │
│  │                                                                                       │  │
│  └───────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                  │                                          │
│                                                  │ ⑧ MCP Request + User Context             │
│                                                  │    (Workload Identity Token)             │
│                                                  ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                         AGENTCORE GATEWAY                                             │  │
│  │                                                                                       │  │
│  │  ⑨ Validate workload identity                                                         │  │
│  │  ⑩ Route to Lambda target (SigV4)                                                     │  │
│  │                                                                                       │  │
│  └───────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                  │                                          │
└──────────────────────────────────────────────────┼──────────────────────────────────────────┘
                                                   │                                           
                                                   │ ⑪ Invoke Lambda (SigV4)                   
                                                   ▼                                           
                             ┌─────────────────────────────────────────────────────────────┐  
                             │                  LAMBDA BRIDGE                              │  
                             │                                                             │  
                             │  ⑫ Extract user context (account access authorization)      │  
                             │  ⑬ AssumeRole to target account                             │  
                             │  ⑭ Call AWS MCP Server (SigV4)                              │  
                             │                                                             │  
                             └────────────────────┬────────────────────────────────────────┘  
                                                  │                                            
                                                  │ ⑮ SigV4 (target account creds)            
                                                  ▼                                            
                             ┌─────────────────────────────────────────────────────────────┐  
                             │                  AWS MCP SERVER                             │  
                             │           https://aws-mcp.us-east-1.api.aws                 │  
                             │                                                             │  
                             │  ⑯ Execute AWS API (ec2:DescribeInstances)                  │  
                             │  ⑰ Return results                                           │  
                             │                                                             │  
                             └────────────────────┬────────────────────────────────────────┘  
                                                  │                                            
                                                  │ ⑱ Results flow back                       
                                                  ▼                                            
                             ┌─────────────────────────────────────────────────────────────┐  
                             │  ⑲ Main Agent formats response                              │  
                             │  ⑳ Return to Chatbot UI → User                              │  
                             └─────────────────────────────────────────────────────────────┘  
```

---

### Step-by-Step Flow

| Step | Component | Action |
|------|-----------|--------|
| ① | User → IdP | User clicks "Login", redirected to Okta/Azure AD |
| ② | IdP → Chatbot | IdP returns JWT access token (via Cognito or direct) |
| ③ | Chatbot → Runtime | User sends query with JWT in Authorization header |
| ④ | Main Agent | Validates JWT against configured authorizer |
| ⑤ | Main Agent | Extracts `sub`, `email`, `groups` from JWT claims |
| ⑥ | Main Agent | Sends query to Bedrock Claude for processing |
| ⑦ | Main Agent | LLM determines AWS data needed, prepares MCP call |
| ⑧ | Runtime → Gateway | Agent calls Gateway with Workload Identity Token |
| ⑨ | Gateway | Validates workload identity from Runtime |
| ⑩ | Gateway | Routes request to Lambda target |
| ⑪ | Gateway → Lambda | Invokes Lambda with SigV4 (service role) |
| ⑫ | Lambda | Checks user's groups against allowed accounts |
| ⑬ | Lambda | Calls STS AssumeRole for target account |
| ⑭ | Lambda → MCP | Calls AWS MCP Server with target account creds |
| ⑮ | Lambda | Signs request with SigV4 |
| ⑯ | AWS MCP Server | Executes `ec2:DescribeInstances` in target account |
| ⑰-⑳ | Return path | Results flow back through all layers to user |

---

### Authentication at Each Layer

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AUTHENTICATION CHAIN                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Layer                    │ Auth Method           │ Identity                │
│  ─────────────────────────┼───────────────────────┼───────────────────────  │
│  User → Chatbot           │ OAuth/OIDC (IdP)      │ User (human)            │
│  Chatbot → Runtime        │ JWT Bearer Token      │ User (human)            │
│  Runtime → Gateway        │ Workload Identity     │ Agent (service)         │
│  Gateway → Lambda         │ SigV4 (service role)  │ Gateway (service)       │
│  Lambda → AWS MCP         │ SigV4 (assumed role)  │ Target Account Role     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### User Context Propagation

The user's identity must flow through the system for authorization and audit:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    USER CONTEXT FLOW                                        │
└─────────────────────────────────────────────────────────────────────────────┘

  JWT Token (from IdP)
  ┌─────────────────────────────────────────┐
  │ {                                       │
  │   "sub": "user123",                     │
  │   "email": "alice@company.com",         │
  │   "groups": ["aws-ops-production"],     │
  │   "iss": "https://company.okta.com",    │
  │   "aud": "multi-account-agent",         │
  │   "exp": 1737550800                     │
  │ }                                       │
  └─────────────────────────────────────────┘
           │
           │ ① Chatbot sends JWT to Runtime
           ▼
  ┌─────────────────────────────────────────┐
  │ Main Agent extracts:                    │
  │   user_id = "user123"                   │
  │   groups = ["aws-ops-production"]       │
  │                                         │
  │ Stores in session context               │
  └─────────────────────────────────────────┘
           │
           │ ② Agent calls Gateway with user context
           │    X-Amzn-Bedrock-AgentCore-Runtime-User-Id: user123
           ▼
  ┌─────────────────────────────────────────┐
  │ Gateway passes context to Lambda        │
  │ (via request headers or payload)        │
  └─────────────────────────────────────────┘
           │
           │ ③ Lambda receives user context
           ▼
  ┌─────────────────────────────────────────┐
  │ Lambda authorizes:                      │
  │   if "aws-ops-production" in groups:    │
  │       allow access to prod accounts     │
  │   else:                                 │
  │       deny                              │
  └─────────────────────────────────────────┘
           │
           │ ④ CloudTrail logs include user context
           ▼
  ┌─────────────────────────────────────────┐
  │ CloudTrail Event:                       │
  │   userIdentity.sessionContext:          │
  │     sessionIssuer: CentralOpsTargetRole │
  │   requestParameters:                    │
  │     (user123 visible in role session)   │
  └─────────────────────────────────────────┘
```

---

### Main Agent Implementation (Runtime)

**File: `agent/main_agent.py`**

```python
import json
import boto3
from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.identity import get_workload_access_token

app = BedrockAgentCoreApp()

# Gateway endpoint
GATEWAY_URL = "https://gateway-id.bedrock-agentcore.us-east-1.amazonaws.com"

@app.entrypoint
def handler(payload, context):
    """Main agent entrypoint - receives user query with JWT context."""
    
    # ④⑤ Extract user context from inbound JWT (validated by Runtime)
    user_claims = context.authorizer_claims  # Populated by Runtime JWT authorizer
    user_id = user_claims.get('sub')
    user_email = user_claims.get('email')
    user_groups = user_claims.get('groups', [])
    
    user_query = payload.get('prompt', '')
    
    # ⑥ Process with LLM
    response = process_with_llm(user_query, user_id, user_groups)
    
    return {"response": response}


def process_with_llm(query: str, user_id: str, user_groups: list) -> str:
    """Process query with Bedrock Claude, calling Gateway for AWS data."""
    
    bedrock = boto3.client('bedrock-runtime')
    
    tools = [{
        "name": "query_aws_resources",
        "description": "Query AWS resources in a specific account",
        "input_schema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
                "tool_name": {"type": "string"},
                "arguments": {"type": "object"}
            },
            "required": ["account_id", "tool_name"]
        }
    }]
    
    messages = [{"role": "user", "content": query}]
    
    response = bedrock.converse(
        modelId="anthropic.claude-3-5-sonnet-20241022-v2:0",
        messages=messages,
        toolConfig={"tools": tools}
    )
    
    # ⑦ Handle tool calls
    while response.get("stopReason") == "tool_use":
        tool_results = []
        
        for block in response["output"]["message"]["content"]:
            if "toolUse" in block:
                tool = block["toolUse"]
                
                if tool["name"] == "query_aws_resources":
                    # ⑧ Call Gateway with user context
                    result = call_gateway(
                        tool["input"],
                        user_id=user_id,
                        user_groups=user_groups
                    )
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool["toolUseId"],
                            "content": [{"text": json.dumps(result)}]
                        }
                    })
        
        messages.append(response["output"]["message"])
        messages.append({"role": "user", "content": tool_results})
        
        response = bedrock.converse(
            modelId="anthropic.claude-3-5-sonnet-20241022-v2:0",
            messages=messages,
            toolConfig={"tools": tools}
        )
    
    return response["output"]["message"]["content"][0]["text"]


def call_gateway(tool_input: dict, user_id: str, user_groups: list) -> dict:
    """Call AgentCore Gateway with user context."""
    
    # Get workload identity token for Gateway auth
    workload_token = get_workload_access_token()
    
    # ⑧ Prepare request with user context
    request_body = {
        "action": "query",
        "account_id": tool_input["account_id"],
        "tool_name": tool_input["tool_name"],
        "arguments": tool_input.get("arguments", {}),
        # Pass user context for authorization in Lambda
        "user_context": {
            "user_id": user_id,
            "groups": user_groups
        }
    }
    
    # Call Gateway (Gateway handles routing to Lambda)
    import urllib.request
    req = urllib.request.Request(
        f"{GATEWAY_URL}/tools/call",
        data=json.dumps(request_body).encode(),
        headers={
            "Authorization": f"Bearer {workload_token}",
            "Content-Type": "application/json",
            "X-Amzn-Bedrock-AgentCore-Runtime-User-Id": user_id
        }
    )
    
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


if __name__ == "__main__":
    app.run()
```

---

### Lambda Bridge with User Authorization

**File: `lambda/handler.py`**

```python
import os
import json
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import urllib.request

AWS_MCP_ENDPOINT = "https://aws-mcp.us-east-1.api.aws/mcp"
TARGET_ROLE_NAME = "CentralOpsTargetRole"

# Group-to-account mapping
ACCOUNT_ACCESS = {
    "aws-ops-admin": ["*"],
    "aws-ops-production": ["111111111111", "222222222222"],
    "aws-ops-nonprod": ["333333333333", "444444444444"],
}

credential_cache = {}


def authorize_request(user_groups: list, account_id: str) -> bool:
    """⑫ Check if user's groups allow access to account."""
    for group in user_groups:
        allowed = ACCOUNT_ACCESS.get(group, [])
        if "*" in allowed or account_id in allowed:
            return True
    return False


def get_credentials(account_id: str, user_id: str) -> dict:
    """⑬ AssumeRole with user context in session name."""
    # Include user_id in session name for CloudTrail attribution
    session_name = f"Agent-{user_id[:20]}-{account_id}"
    
    sts = boto3.client('sts')
    response = sts.assume_role(
        RoleArn=f"arn:aws:iam::{account_id}:role/{TARGET_ROLE_NAME}",
        RoleSessionName=session_name,
        DurationSeconds=3600
    )
    return response['Credentials']


def call_aws_mcp(tool_name: str, arguments: dict, creds: dict) -> dict:
    """⑭⑮ Call AWS MCP Server with SigV4."""
    session = boto3.Session(
        aws_access_key_id=creds['AccessKeyId'],
        aws_secret_access_key=creds['SecretAccessKey'],
        aws_session_token=creds['SessionToken']
    )
    
    mcp_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments}
    }
    
    request = AWSRequest(
        method='POST',
        url=AWS_MCP_ENDPOINT,
        data=json.dumps(mcp_request),
        headers={'Content-Type': 'application/json'}
    )
    SigV4Auth(session.get_credentials(), 'aws-mcp', 'us-east-1').add_auth(request)
    
    req = urllib.request.Request(
        AWS_MCP_ENDPOINT,
        data=request.body.encode(),
        headers=dict(request.headers)
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def handler(event, context):
    """Lambda handler - receives request from Gateway."""
    body = json.loads(event.get('body', '{}'))
    
    # Extract user context (passed from Main Agent)
    user_context = body.get('user_context', {})
    user_id = user_context.get('user_id', 'unknown')
    user_groups = user_context.get('groups', [])
    
    account_id = body.get('account_id')
    action = body.get('action')
    
    # ⑫ Authorization check
    if action == 'query' and not authorize_request(user_groups, account_id):
        return {
            'statusCode': 403,
            'body': json.dumps({
                'error': f'User not authorized for account {account_id}',
                'user_groups': user_groups
            })
        }
    
    if action == 'list_accounts':
        # Return only accounts user can access
        allowed = []
        all_accounts = json.loads(os.environ.get('TARGET_ACCOUNTS', '[]'))
        for acc in all_accounts:
            if authorize_request(user_groups, acc['id']):
                allowed.append(acc)
        return {'statusCode': 200, 'body': json.dumps(allowed)}
    
    elif action == 'query':
        # ⑬ Get credentials with user attribution
        creds = get_credentials(account_id, user_id)
        
        # ⑭⑮⑯ Call AWS MCP Server
        result = call_aws_mcp(
            tool_name=body['tool_name'],
            arguments=body.get('arguments', {}),
            creds=creds
        )
        return {'statusCode': 200, 'body': json.dumps(result, default=str)}
    
    return {'statusCode': 400, 'body': json.dumps({'error': 'Unknown action'})}
```

---

### Runtime Configuration (JWT Authorizer)

**File: `.bedrock_agentcore.yaml`**

```yaml
name: multi-account-ops-agent
entrypoint: agent/main_agent.py

runtime:
  execution_role: arn:aws:iam::111111111111:role/MainAgentRole
  
  # Inbound JWT authorization (from Chatbot)
  authorizer:
    type: customJWTAuthorizer
    discovery_url: https://company.okta.com/.well-known/openid-configuration
    allowed_audiences:
      - multi-account-agent
    allowed_clients:
      - 0oa1234567890abcdef

  # Allow Authorization header to pass through
  request_header_allowlist:
    - Authorization
```

---

### Chatbot Integration Example

**File: `chatbot/client.py`**

```python
import requests

class MultiAccountAgentClient:
    """Chatbot client for calling the Main Agent."""
    
    def __init__(self, runtime_url: str):
        self.runtime_url = runtime_url
        self.access_token = None
    
    def login(self, id_token: str):
        """Store token after OAuth login flow."""
        self.access_token = id_token
    
    def query(self, prompt: str) -> str:
        """Send query to Main Agent with JWT auth."""
        response = requests.post(
            f"{self.runtime_url}/invoke",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            },
            json={"prompt": prompt}
        )
        return response.json().get("response")


# Usage
client = MultiAccountAgentClient("https://runtime-id.bedrock-agentcore.us-east-1.amazonaws.com")
client.login(okta_access_token)  # From OAuth flow

response = client.query("List all EC2 instances in the production account")
print(response)
```

---

## Enterprise Context

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TYPICAL ENTERPRISE SETUP                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐                                                        │
│  │  Enterprise IdP │  (Okta / Azure AD / Ping / etc.)                       │
│  │  ───────────────│                                                        │
│  │  • User Directory                                                        │
│  │  • Groups/Roles                                                          │
│  │  • MFA Policies                                                          │
│  │  • SAML/OIDC                                                             │
│  └────────┬────────┘                                                        │
│           │                                                                 │
│           │ Federation                                                      │
│           ▼                                                                 │
│  ┌─────────────────┐                                                        │
│  │ AWS Identity    │                                                        │
│  │ Center (SSO)    │                                                        │
│  │  ───────────────│                                                        │
│  │  • Permission Sets                                                       │
│  │  • Account Assignments                                                   │
│  │  • Synced Groups                                                         │
│  └────────┬────────┘                                                        │
│           │                                                                 │
│           │ SSO Access                                                      │
│           ▼                                                                 │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  AWS Accounts (via Organizations)                                  │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │    │
│  │  │ Central  │  │Production│  │ Staging  │  │   Dev    │           │    │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘           │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Integration Options

### Option 1: AgentCore Gateway + External IdP (OIDC)

AgentCore Gateway supports JWT authentication from any OIDC-compliant provider.

```
┌──────────────┐     OIDC      ┌──────────────────┐     JWT      ┌─────────────┐
│   User       │──────────────▶│  Okta/Azure AD   │─────────────▶│  AgentCore  │
│              │  (login)      │                  │  (token)     │  Gateway    │
└──────────────┘               └──────────────────┘              └──────┬──────┘
                                                                        │
                                                                        ▼
                                                                 ┌─────────────┐
                                                                 │   Lambda    │
                                                                 │   Bridge    │
                                                                 └─────────────┘
```

**Gateway JWT Authorizer Configuration:**

```json
{
  "customJWTAuthorizer": {
    "discoveryUrl": "https://your-org.okta.com/.well-known/openid-configuration",
    "allowedAudiences": ["api://multi-account-agent"],
    "allowedClients": ["0oa1234567890abcdef"]
  }
}
```

| IdP | Discovery URL Pattern |
|-----|----------------------|
| **Okta** | `https://{domain}.okta.com/.well-known/openid-configuration` |
| **Azure AD** | `https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration` |
| **Ping Identity** | `https://{domain}.pingidentity.com/.well-known/openid-configuration` |
| **AWS Cognito** | `https://cognito-idp.{region}.amazonaws.com/{pool-id}/.well-known/openid-configuration` |

**Pros:**
- Direct integration with enterprise IdP
- No intermediate Cognito needed
- User identity flows through to CloudTrail

**Cons:**
- Requires IdP app registration
- Token validation at Gateway only (not at Lambda)

---

### Option 2: AWS Identity Center as Federation Hub

Use Identity Center as the central point, federated from enterprise IdP.

```
┌──────────────┐    SAML/SCIM    ┌──────────────────┐
│  Okta /      │────────────────▶│  AWS Identity    │
│  Azure AD    │  (federation)   │  Center          │
└──────────────┘                 └────────┬─────────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    │                     │                     │
                    ▼                     ▼                     ▼
            ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
            │ Permission   │      │ Permission   │      │ Permission   │
            │ Set: Admin   │      │ Set: ReadOnly│      │ Set: Ops     │
            └──────────────┘      └──────────────┘      └──────────────┘
                    │                     │                     │
                    └─────────────────────┼─────────────────────┘
                                          │
                                          ▼
                              ┌─────────────────────┐
                              │  Agent uses SSO     │
                              │  credentials via    │
                              │  sso.get_role_creds │
                              └─────────────────────┘
```

**How it works:**
1. Enterprise IdP federates to AWS Identity Center (SAML 2.0)
2. Groups sync via SCIM provisioning
3. Permission Sets map to AWS accounts
4. Agent retrieves SSO credentials programmatically

**Identity Center Permission Set for Agent:**

```json
{
  "Name": "MultiAccountOpsAgent",
  "Description": "Read-only access for operations agent",
  "SessionDuration": "PT1H",
  "ManagedPolicies": [],
  "InlinePolicy": {
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "s3:List*", "s3:GetBucket*",
        "rds:Describe*",
        "lambda:List*", "lambda:Get*",
        "ecs:Describe*", "ecs:List*",
        "eks:Describe*", "eks:List*"
      ],
      "Resource": "*"
    }]
  }
}
```

**Pros:**
- Leverages existing SSO infrastructure
- Centralized permission management
- Group-based access control
- Audit trail tied to user identity

**Cons:**
- Requires interactive login (browser) for token refresh
- Not suitable for fully automated agents in AgentCore Runtime
- Best for local development / human-in-the-loop scenarios

---

### Option 3: Cognito as OIDC Broker (Federated)

Use Cognito User Pool federated to enterprise IdP, then connect to Gateway.

```
┌──────────────┐                ┌──────────────────┐                ┌─────────────┐
│  Okta /      │◀──────────────▶│  Cognito User    │◀──────────────▶│  AgentCore  │
│  Azure AD    │   OIDC/SAML    │  Pool            │   JWT          │  Gateway    │
└──────────────┘  (federation)  └──────────────────┘                └─────────────┘
```

**Cognito Federation Setup:**

```yaml
# CloudFormation
CognitoUserPool:
  Type: AWS::Cognito::UserPool
  Properties:
    UserPoolName: MultiAccountAgentPool

OktaIdentityProvider:
  Type: AWS::Cognito::UserPoolIdentityProvider
  Properties:
    UserPoolId: !Ref CognitoUserPool
    ProviderName: Okta
    ProviderType: OIDC
    ProviderDetails:
      client_id: "0oa1234567890"
      client_secret: "{{resolve:secretsmanager:okta-client-secret}}"
      authorize_scopes: "openid profile email"
      oidc_issuer: "https://your-org.okta.com"
    AttributeMapping:
      email: email
      username: sub
```

**Pros:**
- Cognito handles token exchange
- Can add Cognito-specific features (MFA, custom auth flows)
- Works with Gateway JWT authorizer

**Cons:**
- Extra hop (IdP → Cognito → Gateway)
- Cognito becomes another component to manage
- Token claims may need mapping

---

### Option 4: Direct SAML to IAM (AssumeRoleWithSAML)

For machine-to-machine flows, use SAML assertion directly with STS.

```
┌──────────────┐    SAML       ┌──────────────────┐
│  Okta /      │──────────────▶│  STS             │
│  Azure AD    │  assertion    │  AssumeRoleWith  │
└──────────────┘               │  SAML            │
                               └────────┬─────────┘
                                        │
                                        ▼
                               ┌──────────────────┐
                               │  IAM Role with   │
                               │  SAML trust      │
                               └──────────────────┘
```

**IAM Role Trust Policy:**

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::111111111111:saml-provider/Okta"
    },
    "Action": "sts:AssumeRoleWithSAML",
    "Condition": {
      "StringEquals": {
        "SAML:aud": "https://signin.aws.amazon.com/saml"
      }
    }
  }]
}
```

**Pros:**
- Direct federation, no intermediate services
- Works for service accounts in IdP

**Cons:**
- SAML assertions are short-lived
- Requires IdP to issue assertions programmatically
- More complex than OIDC for API access

---

### Option 5: Hybrid - Gateway (OIDC) + Lambda (Identity Center)

Combine Gateway authentication with Identity Center for cross-account access.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│  ┌──────────┐   OIDC    ┌──────────┐   JWT    ┌──────────┐                  │
│  │  User    │──────────▶│  Okta    │─────────▶│ Gateway  │                  │
│  └──────────┘           └──────────┘          └────┬─────┘                  │
│                                                    │                        │
│                                                    ▼                        │
│                                             ┌──────────────┐                │
│                                             │    Lambda    │                │
│                                             │    Bridge    │                │
│                                             └──────┬───────┘                │
│                                                    │                        │
│         ┌──────────────────────────────────────────┼────────────────────┐   │
│         │                                          │                    │   │
│         ▼                                          ▼                    │   │
│  ┌─────────────────┐                    ┌─────────────────────┐         │   │
│  │ Option A:       │                    │ Option B:           │         │   │
│  │ IAM AssumeRole  │                    │ Identity Center     │         │   │
│  │ (service role)  │                    │ (user context)      │         │   │
│  └─────────────────┘                    └─────────────────────┘         │   │
│                                                                         │   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Lambda can choose:**
- **Option A**: Use IAM AssumeRole (service identity) - simpler, no user context
- **Option B**: Use Identity Center credentials (user identity) - requires token propagation

---

## Detailed: Okta Integration

### Setup Steps

1. **Create Okta Application**
   - Type: OIDC - Web Application
   - Grant types: Authorization Code, Refresh Token
   - Redirect URI: Your application callback

2. **Configure Okta Authorization Server**
   - Create custom scopes: `agent:read`, `agent:admin`
   - Add claims for group membership

3. **Configure Gateway**
   ```json
   {
     "customJWTAuthorizer": {
       "discoveryUrl": "https://your-org.okta.com/oauth2/default/.well-known/openid-configuration",
       "allowedAudiences": ["api://multi-account-agent"],
       "allowedClients": ["0oa1234567890abcdef"],
       "allowedScopes": ["agent:read"]
     }
   }
   ```

4. **Map Okta Groups to Permissions**
   ```python
   # In Lambda, extract groups from JWT
   def get_allowed_accounts(jwt_claims):
       groups = jwt_claims.get('groups', [])
       
       if 'aws-ops-admin' in groups:
           return ALL_ACCOUNTS
       elif 'aws-ops-prod' in groups:
           return PROD_ACCOUNTS
       elif 'aws-ops-dev' in groups:
           return DEV_ACCOUNTS
       else:
           return []
   ```

---

## Detailed: Azure AD Integration

### Setup Steps

1. **Register Application in Azure AD**
   - App registrations → New registration
   - Supported account types: Single tenant
   - Redirect URI: Web → Your callback

2. **Configure API Permissions**
   - Add scope: `api://multi-account-agent/Agent.Read`
   - Expose an API with App ID URI

3. **Configure Gateway**
   ```json
   {
     "customJWTAuthorizer": {
       "discoveryUrl": "https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration",
       "allowedAudiences": ["api://multi-account-agent"],
       "allowedClients": ["{client-id}"]
     }
   }
   ```

4. **Use Azure AD Groups**
   - Enable `groups` claim in token configuration
   - Map group IDs to account access in Lambda

---

## Detailed: AWS Identity Center Integration

### For Local Development / Human Users

```python
# agent/identity_center_auth.py
import boto3
import json
import os
import glob
from datetime import datetime, timezone

class IdentityCenterAuth:
    """
    Use Identity Center credentials for cross-account access.
    Requires: aws sso login --profile <profile>
    """
    
    SSO_CACHE_DIR = os.path.expanduser("~/.aws/sso/cache")
    
    def __init__(self, region: str = "us-east-1"):
        self.region = region
        self.sso = boto3.client('sso', region_name=region)
        self.access_token = self._get_cached_token()
    
    def _get_cached_token(self) -> str:
        """Read SSO token from CLI cache."""
        for cache_file in glob.glob(f"{self.SSO_CACHE_DIR}/*.json"):
            with open(cache_file) as f:
                data = json.load(f)
                if "accessToken" in data:
                    expires = datetime.fromisoformat(data["expiresAt"].replace("Z", "+00:00"))
                    if datetime.now(timezone.utc) < expires:
                        return data["accessToken"]
        raise RuntimeError("No valid SSO token. Run: aws sso login")
    
    def list_accounts(self) -> list:
        """List accounts user can access via SSO."""
        accounts = []
        paginator = self.sso.get_paginator('list_accounts')
        for page in paginator.paginate(accessToken=self.access_token):
            accounts.extend(page.get('accountList', []))
        return accounts
    
    def get_credentials(self, account_id: str, role_name: str) -> dict:
        """Get temporary credentials for account via SSO."""
        response = self.sso.get_role_credentials(
            accessToken=self.access_token,
            accountId=account_id,
            roleName=role_name
        )
        return response['roleCredentials']
```

### For AgentCore Runtime (Service Identity)

Identity Center SSO tokens require interactive login, so for AgentCore Runtime:

```python
# Use IAM AssumeRole instead
class ServiceIdentityAuth:
    """
    For AgentCore Runtime - use IAM roles, not SSO.
    """
    
    def __init__(self):
        self.sts = boto3.client('sts')
    
    def get_credentials(self, account_id: str) -> dict:
        response = self.sts.assume_role(
            RoleArn=f"arn:aws:iam::{account_id}:role/CentralOpsTargetRole",
            RoleSessionName=f"AgentCore-{account_id}"
        )
        return response['Credentials']
```

---

## Authorization: Mapping IdP Groups to AWS Accounts

### Group-Based Access Control

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    IdP GROUP → AWS ACCOUNT MAPPING                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  IdP Group              │  AWS Accounts Allowed                             │
│  ───────────────────────┼─────────────────────────────────────────────────  │
│  aws-ops-admin          │  ALL accounts                                     │
│  aws-ops-production     │  Production accounts only                         │
│  aws-ops-nonprod        │  Staging, Dev, Sandbox                            │
│  aws-ops-readonly       │  All accounts (read-only enforced by IAM)         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation in Lambda

```python
# Authorization middleware
ACCOUNT_ACCESS_MAP = {
    "aws-ops-admin": ["*"],
    "aws-ops-production": ["111111111111", "222222222222"],
    "aws-ops-nonprod": ["333333333333", "444444444444", "555555555555"],
    "aws-ops-readonly": ["*"]
}

def authorize_account_access(jwt_claims: dict, requested_account: str) -> bool:
    """Check if user's groups allow access to requested account."""
    user_groups = jwt_claims.get('groups', [])
    
    for group in user_groups:
        allowed = ACCOUNT_ACCESS_MAP.get(group, [])
        if "*" in allowed or requested_account in allowed:
            return True
    
    return False

def handler(event, context):
    # Extract JWT claims (passed by Gateway)
    jwt_claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
    
    body = json.loads(event.get('body', '{}'))
    requested_account = body.get('account_id')
    
    if not authorize_account_access(jwt_claims, requested_account):
        return {
            'statusCode': 403,
            'body': json.dumps({'error': f'Access denied to account {requested_account}'})
        }
    
    # Proceed with request...
```

---

## Comparison Matrix

| Aspect | Gateway + Okta | Gateway + Azure AD | Identity Center | Cognito Federation |
|--------|----------------|--------------------|-----------------|--------------------|
| **Setup Complexity** | Medium | Medium | Low (if exists) | High |
| **User Experience** | SSO via IdP | SSO via IdP | SSO via IdP | Extra login step |
| **AgentCore Runtime** | ✅ Works | ✅ Works | ❌ No (needs browser) | ✅ Works |
| **User Identity in Logs** | ✅ JWT sub claim | ✅ JWT sub claim | ✅ SSO user | ✅ Cognito user |
| **Group-Based Access** | ✅ Via claims | ✅ Via claims | ✅ Permission Sets | ⚠️ Requires mapping |
| **Token Refresh** | Auto (OIDC) | Auto (OIDC) | Manual (browser) | Auto |
| **Best For** | Production | Production | Dev/Testing | Legacy apps |

---

## Recommended Architecture

### For Production (AgentCore Runtime)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  Enterprise IdP (Okta/Azure AD)                                             │
│         │                                                                   │
│         │ OIDC                                                              │
│         ▼                                                                   │
│  ┌─────────────────┐                                                        │
│  │ AgentCore       │  ◄── JWT validation (discoveryUrl from IdP)            │
│  │ Gateway         │                                                        │
│  └────────┬────────┘                                                        │
│           │                                                                 │
│           │ SigV4 (service role)                                            │
│           ▼                                                                 │
│  ┌─────────────────┐                                                        │
│  │ Lambda Bridge   │  ◄── Extracts groups from JWT, authorizes              │
│  │                 │  ◄── Uses IAM AssumeRole for cross-account             │
│  └────────┬────────┘                                                        │
│           │                                                                 │
│           │ SigV4 (target account creds)                                    │
│           ▼                                                                 │
│  ┌─────────────────┐                                                        │
│  │ AWS MCP Server  │                                                        │
│  └─────────────────┘                                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### For Local Development

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  Developer Laptop                                                           │
│         │                                                                   │
│         │ aws sso login                                                     │
│         ▼                                                                   │
│  ┌─────────────────┐                                                        │
│  │ AWS Identity    │  ◄── Federated from enterprise IdP                     │
│  │ Center          │                                                        │
│  └────────┬────────┘                                                        │
│           │                                                                 │
│           │ sso.get_role_credentials()                                      │
│           ▼                                                                 │
│  ┌─────────────────┐                                                        │
│  │ Local Agent     │  ◄── Uses SSO creds for each account                   │
│  │ (mcp-proxy)     │                                                        │
│  └────────┬────────┘                                                        │
│           │                                                                 │
│           │ SigV4                                                           │
│           ▼                                                                 │
│  ┌─────────────────┐                                                        │
│  │ AWS MCP Server  │                                                        │
│  └─────────────────┘                                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Security Best Practices

1. **Least Privilege**: Map IdP groups to minimal required AWS permissions
2. **Short Token Lifetime**: Configure IdP for 1-hour access tokens
3. **Audit Logging**: Enable CloudTrail with user identity correlation
4. **MFA**: Require MFA at IdP level for sensitive operations
5. **Group Sync**: Use SCIM for automatic group provisioning to Identity Center
6. **Token Validation**: Validate audience, issuer, and expiration at Gateway
7. **No Hardcoded Secrets**: Use Secrets Manager for IdP client secrets

---

## References

- [AgentCore Gateway JWT Authorization](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)
- [Okta OIDC Configuration](https://developer.okta.com/docs/concepts/oauth-openid/)
- [Azure AD App Registration](https://learn.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app)
- [AWS Identity Center External IdP](https://docs.aws.amazon.com/singlesignon/latest/userguide/manage-your-identity-source-idp.html)
- [SCIM Provisioning to Identity Center](https://docs.aws.amazon.com/singlesignon/latest/userguide/provision-automatically.html)
