# Multi-Account AWS Operations Agent Architecture

## Overview

Build a centralized **read-only** operations agent running on **AWS Bedrock AgentCore Runtime** that uses the **AWS Managed MCP Server** to query AWS resources (EC2, S3, RDS, Lambda, ECS, EKS) across **2-10 member accounts** from a single central operations account. Leverages **AWS Organizations** for StackSet-based role deployment.

> **Important**: AgentCore Gateway does NOT support SigV4 for outbound MCP calls. Therefore, this architecture uses **direct MCP proxy** (`mcp-proxy-for-aws`) bundled within the agent, bypassing Gateway for AWS MCP Server communication.

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         CENTRAL OPERATIONS ACCOUNT                           │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                      BEDROCK AGENTCORE RUNTIME                         │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │  │
│  │  │                         AGENT CONTAINER                          │  │  │
│  │  │                                                                  │  │  │
│  │  │  ┌────────────────┐      ┌─────────────────────────────────┐    │  │  │
│  │  │  │  Agent Logic   │      │      mcp-proxy-for-aws          │    │  │  │
│  │  │  │  (Python)      │─────▶│      (bundled in container)     │    │  │  │
│  │  │  │                │      │                                 │    │  │  │
│  │  │  │  1. List accts │      │  - Handles SigV4 signing        │    │  │  │
│  │  │  │  2. AssumeRole │      │  - Uses temp creds from env     │    │  │  │
│  │  │  │  3. Set creds  │      │  - Calls AWS MCP Server         │    │  │  │
│  │  │  │  4. Query MCP  │      │                                 │    │  │  │
│  │  │  └───────┬────────┘      └──────────────┬──────────────────┘    │  │  │
│  │  │          │                              │                       │  │  │
│  │  └──────────┼──────────────────────────────┼───────────────────────┘  │  │
│  │             │                              │                          │  │
│  └─────────────┼──────────────────────────────┼──────────────────────────┘  │
│                │                              │                              │
│                │ STS AssumeRole               │ HTTPS + SigV4                │
│                ▼                              ▼                              │
│  ┌─────────────────────────┐    ┌────────────────────────────────────────┐  │
│  │  CentralOpsAgentRole    │    │         AWS MCP SERVER                 │  │
│  │  (IAM Execution Role)   │    │    https://aws-mcp.us-east-1.api.aws   │  │
│  │                         │    │                                        │  │
│  │  - sts:AssumeRole       │    │    - 15,000+ AWS APIs                  │  │
│  │  - aws-mcp:*            │    │    - Documentation & SOPs              │  │
│  │  - bedrock:InvokeModel  │    │    - Requires SigV4 auth               │  │
│  └───────────┬─────────────┘    └────────────────────────────────────────┘  │
│              │                                                               │
└──────────────┼───────────────────────────────────────────────────────────────┘
               │
               │ STS AssumeRole (cross-account)
               │
     ┌─────────┴─────────┬─────────────────────┬─────────────────────┐
     ▼                   ▼                     ▼                     ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ MEMBER ACCT 1│  │ MEMBER ACCT 2│  │ MEMBER ACCT 3│  │ MEMBER ACCT N│
│              │  │              │  │              │  │              │
│ CentralOps   │  │ CentralOps   │  │ CentralOps   │  │ CentralOps   │
│ TargetRole   │  │ TargetRole   │  │ TargetRole   │  │ TargetRole   │
│ (Read-Only)  │  │ (Read-Only)  │  │ (Read-Only)  │  │ (Read-Only)  │
│              │  │              │  │              │  │              │
│ ┌──────────┐ │  │ ┌──────────┐ │  │ ┌──────────┐ │  │ ┌──────────┐ │
│ │EC2,S3,   │ │  │ │EC2,S3,   │ │  │ │EC2,S3,   │ │  │ │EC2,S3,   │ │
│ │RDS,Lambda│ │  │ │RDS,Lambda│ │  │ │RDS,Lambda│ │  │ │RDS,Lambda│ │
│ │ECS,EKS   │ │  │ │ECS,EKS   │ │  │ │ECS,EKS   │ │  │ │ECS,EKS   │ │
│ └──────────┘ │  │ └──────────┘ │  │ └──────────┘ │  │ └──────────┘ │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
```

---

## Why Not AgentCore Gateway?

| Feature | AgentCore Gateway | Direct MCP Proxy |
|---------|-------------------|------------------|
| SigV4 for MCP targets | ❌ **Not supported** | ✅ Supported |
| OAuth for MCP targets | ✅ Supported | N/A |
| AWS MCP Server compatible | ❌ No (requires SigV4) | ✅ Yes |
| Dynamic credential switching | ❌ Limited | ✅ Full control |

**Conclusion**: AgentCore Gateway cannot call AWS MCP Server because it requires SigV4 authentication, which Gateway doesn't support for MCP targets. We must use `mcp-proxy-for-aws` directly.

---

## Requirements Summary

| Requirement | Value |
|-------------|-------|
| Member Accounts | 2-10 (static configuration) |
| Access Level | **Read-only** |
| AWS Organizations | Yes (StackSet deployment) |
| Target Services | EC2, S3, RDS, Lambda, ECS, EKS |
| MCP Proxy | `mcp-proxy-for-aws` (bundled in agent) |

---

## Credential Flow (Step-by-Step)

```
User Query: "List all EC2 instances in account 222222222222"

┌─────────────────────────────────────────────────────────────────────────┐
│ Step 1: Agent receives query                                            │
│         Agent identifies target account: 222222222222                   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 2: Agent calls STS AssumeRole                                      │
│         RoleArn: arn:aws:iam::222222222222:role/CentralOpsTargetRole   │
│         Returns: AccessKeyId, SecretAccessKey, SessionToken             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 3: Agent sets temporary credentials as environment variables       │
│         AWS_ACCESS_KEY_ID=ASIA...                                       │
│         AWS_SECRET_ACCESS_KEY=...                                       │
│         AWS_SESSION_TOKEN=...                                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 4: Agent invokes mcp-proxy-for-aws                                 │
│         Proxy reads credentials from environment                        │
│         Proxy signs request with SigV4 using account 222's creds       │
│         Proxy sends request to AWS MCP Server                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 5: AWS MCP Server executes ec2:DescribeInstances                   │
│         API runs in context of account 222222222222                     │
│         Results returned to agent                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 6: Agent formats and returns results to user                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Authentication Options: IAM Roles vs AWS Identity Center (SSO)

This architecture supports two authentication methods for cross-account access.

> ### ⚠️ Important: AgentCore Runtime Compatibility
>
> | Method | AgentCore Runtime | Local Development |
> |--------|-------------------|-------------------|
> | **IAM Roles (AssumeRole)** | ✅ **Required** | ✅ Works |
> | **Identity Center (SSO)** | ❌ **Not supported** | ✅ Works |
>
> **If you're deploying to AgentCore Runtime, you MUST use IAM Roles.**
>
> Identity Center (SSO) requires interactive browser login and local token caching,
> which are not available in AgentCore's managed runtime environment.

---

### Option A: IAM Roles (Required for AgentCore Runtime)

Uses traditional STS AssumeRole with IAM roles in each account. **This is the only option for production deployments on AgentCore Runtime.**

```
Central Account                    Target Account
┌─────────────────┐               ┌─────────────────┐
│ CentralOps      │  AssumeRole   │ CentralOps      │
│ AgentRole       │──────────────▶│ TargetRole      │
│                 │               │                 │
│ Trust: bedrock- │               │ Trust: Central  │
│ agentcore.aws   │               │ AgentRole ARN   │
└─────────────────┘               └─────────────────┘
```

**When to use:**
- ✅ Agent runs in AgentCore Runtime (REQUIRED)
- ✅ Agent runs in Lambda, ECS, or any AWS managed service
- ✅ No human user context needed
- ✅ Pure machine-to-machine authentication
- ✅ Production deployments

---

### Option B: AWS Identity Center (SSO) - Local Development Only

> ⚠️ **This option is for LOCAL DEVELOPMENT and TESTING only.**
> It will NOT work in AgentCore Runtime.

Uses Identity Center permission sets and SSO credentials for cross-account access.

**Why SSO doesn't work in AgentCore Runtime:**

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SSO REQUIREMENTS vs AGENTCORE                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  SSO Requires:                    AgentCore Provides:                   │
│  ─────────────                    ───────────────────                   │
│  ✅ Browser for login             ❌ No browser access                  │
│  ✅ ~/.aws/sso/cache/ directory   ❌ No persistent filesystem           │
│  ✅ Human to authenticate         ❌ Runs as managed service            │
│  ✅ Token refresh by user         ❌ No human in the loop               │
│                                                                         │
│  RESULT: SSO cannot work in AgentCore Runtime                           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**When to use SSO:**
- 🧪 Running agent locally on your laptop for development
- 🧪 Testing cross-account access before deploying to AgentCore
- 🧪 Want user identity in CloudTrail during testing
- 🧪 Already using Identity Center for all AWS access

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AWS IDENTITY CENTER                              │
│  ┌────────────────┐    ┌────────────────┐    ┌────────────────┐        │
│  │ Permission Set │    │ Permission Set │    │ Permission Set │        │
│  │ "CentralOps    │    │ "CentralOps    │    │ "CentralOps    │        │
│  │  ReadOnly"     │    │  ReadOnly"     │    │  ReadOnly"     │        │
│  └───────┬────────┘    └───────┬────────┘    └───────┬────────┘        │
│          │                     │                     │                  │
│          ▼                     ▼                     ▼                  │
│   Account 222           Account 333           Account 444              │
│   (Production)          (Staging)             (Development)            │
└─────────────────────────────────────────────────────────────────────────┘
           │                     │                     │
           └─────────────────────┼─────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  SSO User Session       │
                    │  (via aws sso login)    │
                    │                         │
                    │  accessToken cached at  │
                    │  ~/.aws/sso/cache/      │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  sso.get_role_credentials│
                    │  (per account/role)     │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │  Temporary IAM Creds    │
                    │  for Target Account     │
                    └─────────────────────────┘
```

**When to use:**
- Agent runs locally or on EC2 with user context
- Want centralized identity management
- Using Identity Center for all AWS access
- Need audit trail tied to human identity

---

### Identity Center Credential Flow (Detailed)

```
Step 1: User authenticates via SSO
┌─────────────────────────────────────────────────────────────────────────┐
│  $ aws sso login --profile my-sso-profile                              │
│                                                                         │
│  - Opens browser for Identity Center login                              │
│  - User authenticates (username/password + MFA)                         │
│  - Access token cached at ~/.aws/sso/cache/<hash>.json                 │
│  - Token valid for 1-12 hours (configurable)                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
Step 2: Agent reads cached SSO token
┌─────────────────────────────────────────────────────────────────────────┐
│  Token file contains:                                                   │
│  {                                                                      │
│    "accessToken": "eyJ...<bearer-token>...",                           │
│    "expiresAt": "2025-01-22T12:00:00Z",                                │
│    "region": "us-east-1",                                              │
│    "startUrl": "https://my-org.awsapps.com/start"                      │
│  }                                                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
Step 3: List available accounts and roles
┌─────────────────────────────────────────────────────────────────────────┐
│  sso_client.list_accounts(accessToken=token)                           │
│  sso_client.list_account_roles(accessToken=token, accountId=acct_id)   │
│                                                                         │
│  Returns: List of accounts + permission sets user can access            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
Step 4: Get credentials for target account
┌─────────────────────────────────────────────────────────────────────────┐
│  sso_client.get_role_credentials(                                       │
│      accessToken=token,                                                 │
│      accountId="222222222222",                                          │
│      roleName="CentralOpsReadOnly"    # Permission set name            │
│  )                                                                      │
│                                                                         │
│  Returns:                                                               │
│  {                                                                      │
│    "accessKeyId": "ASIA...",                                           │
│    "secretAccessKey": "...",                                           │
│    "sessionToken": "...",                                              │
│    "expiration": 1234567890                                            │
│  }                                                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
Step 5: Use credentials for MCP calls (same as IAM flow)
┌─────────────────────────────────────────────────────────────────────────┐
│  Set environment variables → mcp-proxy-for-aws → AWS MCP Server        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### Identity Center Setup

#### 1. Create Permission Set in Identity Center

```
Permission Set Name: CentralOpsReadOnly
Session Duration: 1 hour
Managed Policies:
  - arn:aws:iam::aws:policy/ReadOnlyAccess (or custom)

Custom Policy (scoped):
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "ec2:Describe*",
      "s3:List*", "s3:GetBucket*", "s3:GetObject",
      "rds:Describe*",
      "lambda:List*", "lambda:Get*",
      "ecs:Describe*", "ecs:List*",
      "eks:Describe*", "eks:List*",
      "cloudwatch:GetMetricData", "cloudwatch:ListMetrics",
      "logs:DescribeLogGroups", "logs:GetLogEvents"
    ],
    "Resource": "*"
  }]
}
```

#### 2. Assign Permission Set to Accounts

In Identity Center console:
1. Go to **AWS Accounts**
2. Select target accounts (Production, Staging, Development)
3. Assign **Users/Groups** → Select your user or group
4. Assign **Permission Sets** → Select `CentralOpsReadOnly`

#### 3. Configure AWS CLI Profile

**File: `~/.aws/config`**

```ini
[profile central-ops-sso]
sso_session = my-org-sso
sso_account_id = 111111111111
sso_role_name = CentralOpsReadOnly

[sso-session my-org-sso]
sso_start_url = https://my-org.awsapps.com/start
sso_region = us-east-1
sso_registration_scopes = sso:account:access
```

#### 4. Login and Cache Token

```bash
# Login (opens browser)
aws sso login --profile central-ops-sso

# Verify
aws sts get-caller-identity --profile central-ops-sso
```

---

### Identity Center Account Manager (Code)

**File: `agent/sso_account_manager.py`**

```python
import boto3
import json
import os
import glob
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class SSOCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: int
    account_id: str
    role_name: str


class SSOAccountManager:
    """
    Manages cross-account access using AWS Identity Center (SSO).

    Requires: User has run 'aws sso login' and has valid cached token.
    """

    SSO_CACHE_DIR = os.path.expanduser("~/.aws/sso/cache")
    DEFAULT_ROLE_NAME = "CentralOpsReadOnly"

    def __init__(self, start_url: str = None, region: str = "us-east-1"):
        self.start_url = start_url
        self.region = region
        self.sso_client = boto3.client('sso', region_name=region)
        self.access_token = self._get_cached_token()
        self.credential_cache: Dict[str, SSOCredentials] = {}

    def _get_cached_token(self) -> str:
        """
        Read the SSO access token from the CLI cache.

        The token is cached after 'aws sso login' at ~/.aws/sso/cache/
        """
        cache_files = glob.glob(os.path.join(self.SSO_CACHE_DIR, "*.json"))

        for cache_file in cache_files:
            try:
                with open(cache_file) as f:
                    data = json.load(f)

                # Skip if not an SSO token file
                if "accessToken" not in data:
                    continue

                # Check if token matches our start URL (if specified)
                if self.start_url and data.get("startUrl") != self.start_url:
                    continue

                # Check if token is expired
                expires_at = data.get("expiresAt")
                if expires_at:
                    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    if datetime.now(timezone.utc) >= expiry:
                        continue

                return data["accessToken"]

            except (json.JSONDecodeError, KeyError):
                continue

        raise RuntimeError(
            "No valid SSO token found. Run 'aws sso login --profile <your-sso-profile>' first."
        )

    def list_accounts(self) -> List[Dict]:
        """List all AWS accounts accessible via SSO."""
        accounts = []
        paginator = self.sso_client.get_paginator('list_accounts')

        for page in paginator.paginate(accessToken=self.access_token):
            for account in page.get('accountList', []):
                accounts.append({
                    "id": account['accountId'],
                    "name": account.get('accountName', 'Unknown'),
                    "email": account.get('emailAddress', '')
                })

        return accounts

    def list_roles(self, account_id: str) -> List[str]:
        """List available roles (permission sets) for an account."""
        roles = []
        paginator = self.sso_client.get_paginator('list_account_roles')

        for page in paginator.paginate(
            accessToken=self.access_token,
            accountId=account_id
        ):
            for role in page.get('roleList', []):
                roles.append(role['roleName'])

        return roles

    def get_credentials(
        self,
        account_id: str,
        role_name: str = None
    ) -> SSOCredentials:
        """
        Get temporary credentials for a target account via SSO.

        This replaces STS AssumeRole when using Identity Center.
        """
        role_name = role_name or self.DEFAULT_ROLE_NAME
        cache_key = f"{account_id}:{role_name}"

        # Check cache
        if cache_key in self.credential_cache:
            creds = self.credential_cache[cache_key]
            if not self._is_expired(creds):
                return creds

        # Get credentials via SSO
        response = self.sso_client.get_role_credentials(
            accessToken=self.access_token,
            accountId=account_id,
            roleName=role_name
        )

        role_creds = response['roleCredentials']
        creds = SSOCredentials(
            access_key_id=role_creds['accessKeyId'],
            secret_access_key=role_creds['secretAccessKey'],
            session_token=role_creds['sessionToken'],
            expiration=role_creds['expiration'],
            account_id=account_id,
            role_name=role_name
        )

        self.credential_cache[cache_key] = creds
        return creds

    def set_environment_credentials(
        self,
        account_id: str,
        role_name: str = None
    ) -> None:
        """Set AWS credentials as environment variables for MCP proxy."""
        creds = self.get_credentials(account_id, role_name)

        os.environ['AWS_ACCESS_KEY_ID'] = creds.access_key_id
        os.environ['AWS_SECRET_ACCESS_KEY'] = creds.secret_access_key
        os.environ['AWS_SESSION_TOKEN'] = creds.session_token

    def _is_expired(self, creds: SSOCredentials) -> bool:
        """Check if credentials are expired (with 5-min buffer)."""
        buffer_ms = 5 * 60 * 1000  # 5 minutes in milliseconds
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return now_ms + buffer_ms >= creds.expiration

    def refresh_token_if_needed(self) -> bool:
        """
        Check if SSO token is still valid.

        Returns False if token is expired (user needs to re-login).
        """
        try:
            # Simple check: try to list accounts
            self.sso_client.list_accounts(
                accessToken=self.access_token,
                maxResults=1
            )
            return True
        except self.sso_client.exceptions.UnauthorizedException:
            return False
```

---

### Comparison: IAM Roles vs Identity Center

| Aspect | IAM Roles (AssumeRole) | Identity Center (SSO) |
|--------|------------------------|----------------------|
| **AgentCore Runtime** | ✅ **Supported** | ❌ **Not supported** |
| **Lambda / ECS** | ✅ Supported | ❌ Not supported |
| **Local Development** | ✅ Supported | ✅ Supported |
| **Initial Auth** | Service role or IAM user | `aws sso login` (browser) |
| **Token Location** | STS returns directly | `~/.aws/sso/cache/` |
| **Cross-Account API** | `sts.assume_role()` | `sso.get_role_credentials()` |
| **Role Definition** | IAM Role per account | Permission Set (centralized) |
| **Trust Policy** | Explicit per role | Managed by Identity Center |
| **Session Duration** | 1-12 hours | 1-12 hours |
| **MFA** | Optional (per role) | Centralized in Identity Center |
| **Audit Trail** | CloudTrail (role ARN) | CloudTrail (user identity) |
| **Best For** | **Production** (AgentCore, Lambda, ECS) | **Local dev/testing only** |

---

### Choosing the Right Approach

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    WHERE IS THE AGENT RUNNING?                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐
        │  AWS Managed      │           │  Local / EC2 /    │
        │  (AgentCore,      │           │  User Context     │
        │   Lambda, ECS)    │           │                   │
        └─────────┬─────────┘           └─────────┬─────────┘
                  │                               │
                  ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐
        │  Use IAM Roles    │           │  Use Identity     │
        │  (AssumeRole)     │           │  Center (SSO)     │
        │                   │           │                   │
        │  - Service role   │           │  - User identity  │
        │  - No human login │           │  - Browser login  │
        │  - Auto creds     │           │  - Cached token   │
        └───────────────────┘           └───────────────────┘
```

**Use IAM Roles when:** ✅ **Required for AgentCore Runtime**
- Agent runs in AgentCore Runtime (the ONLY option for production)
- Agent runs in Lambda, ECS, or any AWS managed service
- No human user context available
- Fully automated, no interactive login possible

**Use Identity Center when:** 🧪 **Local Development Only**
- Running agent locally on your laptop for development/testing
- Want user identity in audit logs during testing
- Already using Identity Center for all AWS access
- Need to test before deploying to AgentCore

> ⚠️ **Important**: Identity Center (SSO) **cannot** be used in AgentCore Runtime because:
> 1. No browser available for interactive login
> 2. No local filesystem to cache SSO tokens
> 3. AgentCore runs as a managed service without human context

---

### Hybrid Approach (For Development → Production Workflow)

> This pattern lets you develop locally with SSO, then deploy to AgentCore with IAM roles
> without changing your agent code.

Support both methods with a factory pattern:

**File: `agent/credential_provider.py`**

```python
import os
from abc import ABC, abstractmethod
from typing import Dict, List

# Import both managers
from account_manager import AccountManager  # IAM Roles
from sso_account_manager import SSOAccountManager  # Identity Center


class CredentialProvider(ABC):
    """Abstract base for credential providers."""

    @abstractmethod
    def list_accounts(self) -> List[Dict]:
        pass

    @abstractmethod
    def set_environment_credentials(self, account_id: str) -> None:
        pass


class IAMCredentialProvider(CredentialProvider):
    """Uses IAM AssumeRole for cross-account access."""

    def __init__(self, registry_path: str = None):
        self.manager = AccountManager(registry_path)

    def list_accounts(self) -> List[Dict]:
        return self.manager.list_accounts()

    def set_environment_credentials(self, account_id: str) -> None:
        self.manager.set_environment_credentials(account_id)


class SSOCredentialProvider(CredentialProvider):
    """Uses Identity Center for cross-account access."""

    def __init__(self, start_url: str = None, region: str = "us-east-1"):
        self.manager = SSOAccountManager(start_url, region)

    def list_accounts(self) -> List[Dict]:
        return self.manager.list_accounts()

    def set_environment_credentials(self, account_id: str) -> None:
        self.manager.set_environment_credentials(account_id)


def get_credential_provider() -> CredentialProvider:
    """
    Factory to get the appropriate credential provider.

    Priority:
    1. If SSO token exists and valid → Use SSO
    2. If running in AWS service context → Use IAM
    3. Fall back to IAM with registry file
    """
    # Check for SSO token
    sso_cache = os.path.expanduser("~/.aws/sso/cache")
    if os.path.exists(sso_cache) and os.listdir(sso_cache):
        try:
            provider = SSOCredentialProvider()
            # Verify token is valid
            if provider.manager.refresh_token_if_needed():
                print("Using Identity Center (SSO) credentials")
                return provider
        except RuntimeError:
            pass  # No valid SSO token, fall through

    # Fall back to IAM roles
    print("Using IAM role credentials")
    return IAMCredentialProvider()
```

---

## Implementation Plan

### Phase 1: Infrastructure Setup

#### 1.1 Central Account IAM Role

**File: `infrastructure/central-account.yaml`**

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: Central Operations Agent IAM infrastructure

Parameters:
  OrganizationId:
    Type: String
    Description: AWS Organization ID (o-xxxxxxxxxx)

Resources:
  CentralOpsAgentRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: CentralOpsAgentRole
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: bedrock-agentcore.amazonaws.com
            Action: sts:AssumeRole
      Policies:
        - PolicyName: CrossAccountAssumeRole
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Sid: AssumeTargetRoles
                Effect: Allow
                Action: sts:AssumeRole
                Resource: arn:aws:iam::*:role/CentralOpsTargetRole
                Condition:
                  StringEquals:
                    aws:PrincipalOrgID: !Ref OrganizationId
        - PolicyName: AWSMCPServerAccess
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - aws-mcp:InvokeMcp
                  - aws-mcp:CallReadOnlyTool
                Resource: '*'
        - PolicyName: BedrockAccess
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - bedrock:InvokeModel
                  - bedrock:InvokeModelWithResponseStream
                Resource:
                  - arn:aws:bedrock:*::foundation-model/anthropic.*

  # S3 bucket for agent artifacts
  AgentArtifactsBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub central-ops-agent-${AWS::AccountId}
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - ServerSideEncryptionByDefault:
              SSEAlgorithm: AES256

Outputs:
  RoleArn:
    Value: !GetAtt CentralOpsAgentRole.Arn
    Export:
      Name: CentralOpsAgentRoleArn
  ArtifactsBucket:
    Value: !Ref AgentArtifactsBucket
```

#### 1.2 Member Account Role (StackSet)

**File: `infrastructure/member-account-role.yaml`**

Deploy via AWS Organizations StackSet to all member accounts:

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: Cross-account role for Central Operations Agent (Read-Only)

Parameters:
  CentralAccountId:
    Type: String
    Description: Central operations account ID

Resources:
  CentralOpsTargetRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: CentralOpsTargetRole
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              AWS: !Sub arn:aws:iam::${CentralAccountId}:role/CentralOpsAgentRole
            Action: sts:AssumeRole
      Policies:
        - PolicyName: ReadOnlyComputeStorage
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  # EC2
                  - ec2:Describe*
                  - ec2:Get*
                  # S3
                  - s3:List*
                  - s3:GetBucket*
                  - s3:GetObject
                  - s3:GetObjectVersion
                  # RDS
                  - rds:Describe*
                  - rds:List*
                  # Lambda
                  - lambda:List*
                  - lambda:Get*
                  # ECS
                  - ecs:Describe*
                  - ecs:List*
                  # EKS
                  - eks:Describe*
                  - eks:List*
                  # CloudWatch (for metrics/logs)
                  - cloudwatch:GetMetricData
                  - cloudwatch:GetMetricStatistics
                  - cloudwatch:ListMetrics
                  - cloudwatch:DescribeAlarms
                  - logs:DescribeLogGroups
                  - logs:GetLogEvents
                  - logs:FilterLogEvents
                  # Tags
                  - tag:GetResources
                  - tag:GetTagKeys
                  - tag:GetTagValues
                Resource: '*'

Outputs:
  RoleArn:
    Value: !GetAtt CentralOpsTargetRole.Arn
```

#### 1.3 Account Registry

**File: `infrastructure/account-registry.json`**

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
    },
    {
      "id": "333333333333",
      "name": "Staging",
      "environment": "staging",
      "role": "workload"
    },
    {
      "id": "444444444444",
      "name": "Development",
      "environment": "development",
      "role": "workload"
    }
  ]
}
```

---

### Phase 2: Agent Development

#### 2.1 Project Structure

```
aws-mcp-multi-account-repo/
├── ARCHITECTURE.md
├── infrastructure/
│   ├── central-account.yaml
│   ├── member-account-role.yaml
│   └── account-registry.json
├── agent/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── central_ops_agent.py       # Main agent
│   ├── multi_account_mcp.py       # MCP client with cred switching
│   └── account_manager.py         # Account registry and role assumption
├── scripts/
│   ├── deploy_infrastructure.sh
│   └── deploy_agent.py
└── tests/
    ├── test_role_assumption.py
    └── test_mcp_queries.py
```

#### 2.2 Account Manager

**File: `agent/account_manager.py`**

```python
import boto3
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class AccountCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: datetime
    account_id: str


class AccountManager:
    """Manages cross-account role assumption and credential caching."""

    ROLE_NAME = "CentralOpsTargetRole"
    SESSION_DURATION = 3600  # 1 hour
    REFRESH_BUFFER = timedelta(minutes=5)

    def __init__(self, registry_path: str = None):
        self.sts = boto3.client('sts')
        self.credential_cache: Dict[str, AccountCredentials] = {}
        self.accounts = self._load_registry(registry_path)

    def _load_registry(self, path: str = None) -> Dict:
        """Load account registry from file or environment."""
        if path and os.path.exists(path):
            with open(path) as f:
                return json.load(f)

        # Try environment variable
        registry_json = os.environ.get('ACCOUNT_REGISTRY')
        if registry_json:
            return json.loads(registry_json)

        return {"accounts": []}

    def list_accounts(self) -> list:
        """List all available target accounts."""
        return [
            {
                "id": acc["id"],
                "name": acc["name"],
                "environment": acc["environment"]
            }
            for acc in self.accounts.get("accounts", [])
            if acc.get("role") != "central"
        ]

    def get_credentials(self, account_id: str) -> AccountCredentials:
        """Get credentials for target account, using cache if valid."""
        # Check cache
        if account_id in self.credential_cache:
            creds = self.credential_cache[account_id]
            if not self._is_expired(creds):
                return creds

        # Assume role
        role_arn = f"arn:aws:iam::{account_id}:role/{self.ROLE_NAME}"

        response = self.sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=f"CentralOps-{account_id}",
            DurationSeconds=self.SESSION_DURATION
        )

        creds = AccountCredentials(
            access_key_id=response['Credentials']['AccessKeyId'],
            secret_access_key=response['Credentials']['SecretAccessKey'],
            session_token=response['Credentials']['SessionToken'],
            expiration=response['Credentials']['Expiration'],
            account_id=account_id
        )

        self.credential_cache[account_id] = creds
        return creds

    def set_environment_credentials(self, account_id: str) -> None:
        """Set AWS credentials as environment variables for MCP proxy."""
        creds = self.get_credentials(account_id)

        os.environ['AWS_ACCESS_KEY_ID'] = creds.access_key_id
        os.environ['AWS_SECRET_ACCESS_KEY'] = creds.secret_access_key
        os.environ['AWS_SESSION_TOKEN'] = creds.session_token

    def _is_expired(self, creds: AccountCredentials) -> bool:
        """Check if credentials are expired or expiring soon."""
        now = datetime.now(timezone.utc)
        return now + self.REFRESH_BUFFER >= creds.expiration
```

#### 2.3 Multi-Account MCP Client

**File: `agent/multi_account_mcp.py`**

```python
import asyncio
import subprocess
import json
from typing import Dict, Any, Optional
from account_manager import AccountManager


class MultiAccountMCPClient:
    """MCP client that handles cross-account credential switching."""

    MCP_SERVER_URL = "https://aws-mcp.us-east-1.api.aws/mcp"

    def __init__(self, account_manager: AccountManager):
        self.account_manager = account_manager
        self.current_account: Optional[str] = None

    def switch_account(self, account_id: str) -> None:
        """Switch to a different AWS account for subsequent MCP calls."""
        self.account_manager.set_environment_credentials(account_id)
        self.current_account = account_id
        print(f"Switched to account: {account_id}")

    def call_mcp_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        account_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Call an MCP tool, optionally switching accounts first.

        Args:
            tool_name: The MCP tool to call (e.g., "aws__ec2_describe_instances")
            arguments: Tool arguments
            account_id: Target account ID (switches if different from current)

        Returns:
            Tool execution result
        """
        # Switch account if needed
        if account_id and account_id != self.current_account:
            self.switch_account(account_id)

        # Build MCP request
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        # Call via mcp-proxy-for-aws
        result = self._invoke_mcp_proxy(request)
        return result

    def list_tools(self) -> list:
        """List available MCP tools."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }

        result = self._invoke_mcp_proxy(request)
        return result.get("tools", [])

    def _invoke_mcp_proxy(self, request: Dict) -> Dict:
        """Invoke mcp-proxy-for-aws with the given request."""
        # Run proxy as subprocess
        proc = subprocess.run(
            [
                "uvx", "mcp-proxy-for-aws@latest",
                self.MCP_SERVER_URL,
                "--metadata", "AWS_REGION=us-east-1"
            ],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=120
        )

        if proc.returncode != 0:
            raise RuntimeError(f"MCP proxy error: {proc.stderr}")

        return json.loads(proc.stdout)

    def query_across_accounts(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        account_ids: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Run the same query across multiple accounts and aggregate results.

        Args:
            tool_name: The MCP tool to call
            arguments: Tool arguments
            account_ids: List of account IDs (defaults to all accounts)

        Returns:
            Aggregated results by account
        """
        if account_ids is None:
            account_ids = [acc["id"] for acc in self.account_manager.list_accounts()]

        results = {}
        for account_id in account_ids:
            try:
                result = self.call_mcp_tool(tool_name, arguments, account_id)
                results[account_id] = {"status": "success", "data": result}
            except Exception as e:
                results[account_id] = {"status": "error", "error": str(e)}

        return results
```

#### 2.4 Main Agent

**File: `agent/central_ops_agent.py`**

```python
import os
import json
import boto3
from typing import Optional
from account_manager import AccountManager
from multi_account_mcp import MultiAccountMCPClient

# For AgentCore Runtime
try:
    from bedrock_agentcore import BedrockAgentCoreApp
    AGENTCORE_AVAILABLE = True
except ImportError:
    AGENTCORE_AVAILABLE = False


class CentralOpsAgent:
    """
    Centralized operations agent for querying AWS resources across multiple accounts.

    Uses mcp-proxy-for-aws directly (not AgentCore Gateway) because AWS MCP Server
    requires SigV4 authentication, which Gateway doesn't support for MCP targets.
    """

    SYSTEM_PROMPT = """You are a centralized operations agent for querying AWS resources across multiple accounts.

CAPABILITIES:
- Query EC2, S3, RDS, Lambda, ECS, EKS resources (READ-ONLY)
- Access multiple AWS accounts from a central operations account
- Aggregate data across accounts

AVAILABLE COMMANDS:
1. list_accounts - Show all available target accounts
2. switch_account <account_id> - Switch to a specific account
3. query <service> <operation> - Query resources in current account
4. query_all <service> <operation> - Query across all accounts

WORKFLOW:
1. User asks about resources in an account
2. Switch to that account using switch_account
3. Use AWS MCP tools to query resources
4. Return formatted results

Always specify which account you're querying in your responses."""

    def __init__(self, registry_path: str = None):
        self.account_manager = AccountManager(registry_path)
        self.mcp_client = MultiAccountMCPClient(self.account_manager)
        self.bedrock = boto3.client('bedrock-runtime')

    def list_accounts(self) -> str:
        """List all available target accounts."""
        accounts = self.account_manager.list_accounts()
        return json.dumps(accounts, indent=2)

    def query_account(
        self,
        account_id: str,
        service: str,
        operation: str,
        **kwargs
    ) -> str:
        """Query resources in a specific account."""
        tool_name = f"aws__{service}_{operation}"
        result = self.mcp_client.call_mcp_tool(tool_name, kwargs, account_id)
        return json.dumps(result, indent=2, default=str)

    def query_all_accounts(
        self,
        service: str,
        operation: str,
        **kwargs
    ) -> str:
        """Query resources across all accounts."""
        tool_name = f"aws__{service}_{operation}"
        results = self.mcp_client.query_across_accounts(tool_name, kwargs)
        return json.dumps(results, indent=2, default=str)

    def process_query(self, user_query: str) -> str:
        """
        Process a natural language query using Bedrock Claude.

        The model will:
        1. Parse the user's intent
        2. Determine which account(s) to query
        3. Call appropriate MCP tools
        4. Format and return results
        """
        # Build conversation with tools
        messages = [
            {"role": "user", "content": user_query}
        ]

        # Define available tools for the model
        tools = [
            {
                "name": "list_accounts",
                "description": "List all available AWS accounts",
                "input_schema": {"type": "object", "properties": {}}
            },
            {
                "name": "query_account",
                "description": "Query AWS resources in a specific account",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "12-digit AWS account ID"},
                        "service": {"type": "string", "description": "AWS service (ec2, s3, rds, lambda, ecs, eks)"},
                        "operation": {"type": "string", "description": "Operation (describe_instances, list_buckets, etc.)"}
                    },
                    "required": ["account_id", "service", "operation"]
                }
            },
            {
                "name": "query_all_accounts",
                "description": "Query AWS resources across all accounts",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string"},
                        "operation": {"type": "string"}
                    },
                    "required": ["service", "operation"]
                }
            }
        ]

        # Call Bedrock
        response = self.bedrock.converse(
            modelId="anthropic.claude-3-5-sonnet-20241022-v2:0",
            messages=messages,
            system=[{"text": self.SYSTEM_PROMPT}],
            toolConfig={"tools": tools}
        )

        # Handle tool calls in a loop
        while response.get("stopReason") == "tool_use":
            tool_calls = [
                block for block in response["output"]["message"]["content"]
                if block.get("toolUse")
            ]

            tool_results = []
            for tool_call in tool_calls:
                tool = tool_call["toolUse"]
                tool_name = tool["name"]
                tool_input = tool["input"]

                # Execute tool
                if tool_name == "list_accounts":
                    result = self.list_accounts()
                elif tool_name == "query_account":
                    result = self.query_account(**tool_input)
                elif tool_name == "query_all_accounts":
                    result = self.query_all_accounts(**tool_input)
                else:
                    result = f"Unknown tool: {tool_name}"

                tool_results.append({
                    "toolResult": {
                        "toolUseId": tool["toolUseId"],
                        "content": [{"text": result}]
                    }
                })

            # Continue conversation with tool results
            messages.append(response["output"]["message"])
            messages.append({"role": "user", "content": tool_results})

            response = self.bedrock.converse(
                modelId="anthropic.claude-3-5-sonnet-20241022-v2:0",
                messages=messages,
                system=[{"text": self.SYSTEM_PROMPT}],
                toolConfig={"tools": tools}
            )

        # Extract final text response
        final_content = response["output"]["message"]["content"]
        return next(
            (block["text"] for block in final_content if "text" in block),
            "No response generated"
        )


# AgentCore Runtime entrypoint
if AGENTCORE_AVAILABLE:
    app = BedrockAgentCoreApp()
    agent = CentralOpsAgent()

    @app.entrypoint
    def handler(payload):
        user_query = payload.get("prompt", "")
        result = agent.process_query(user_query)
        return {"response": result}

    if __name__ == "__main__":
        app.run()
else:
    # Local execution
    if __name__ == "__main__":
        agent = CentralOpsAgent(registry_path="infrastructure/account-registry.json")

        # Interactive mode
        print("Central Operations Agent")
        print("Type 'quit' to exit\n")

        while True:
            query = input("Query: ").strip()
            if query.lower() == 'quit':
                break

            response = agent.process_query(query)
            print(f"\n{response}\n")
```

#### 2.5 Dockerfile

**File: `agent/Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install uv for mcp-proxy-for-aws
RUN pip install uv

# Pre-install mcp-proxy-for-aws
RUN uvx mcp-proxy-for-aws@latest --version || true

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent code
COPY *.py .

# Set environment
ENV PYTHONUNBUFFERED=1

# Run agent
CMD ["python", "central_ops_agent.py"]
```

#### 2.6 Requirements

**File: `agent/requirements.txt`**

```
boto3>=1.35.0
bedrock-agentcore>=0.1.0
```

---

### Phase 3: Deployment

#### 3.1 Deploy Infrastructure

**File: `scripts/deploy_infrastructure.sh`**

```bash
#!/bin/bash
set -e

CENTRAL_ACCOUNT_ID="${1:?Usage: $0 <central-account-id> <org-id> <ou-id>}"
ORG_ID="${2:?Usage: $0 <central-account-id> <org-id> <ou-id>}"
OU_ID="${3:?Usage: $0 <central-account-id> <org-id> <ou-id>}"

echo "Deploying central account infrastructure..."
aws cloudformation deploy \
  --stack-name central-ops-agent \
  --template-file infrastructure/central-account.yaml \
  --parameter-overrides OrganizationId=$ORG_ID \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1

echo "Creating StackSet for member account roles..."
aws cloudformation create-stack-set \
  --stack-set-name central-ops-target-roles \
  --template-body file://infrastructure/member-account-role.yaml \
  --parameters ParameterKey=CentralAccountId,ParameterValue=$CENTRAL_ACCOUNT_ID \
  --permission-model SERVICE_MANAGED \
  --auto-deployment Enabled=true,RetainStacksOnAccountRemoval=false \
  --region us-east-1

echo "Deploying to organization units..."
aws cloudformation create-stack-instances \
  --stack-set-name central-ops-target-roles \
  --deployment-targets OrganizationalUnitIds=$OU_ID \
  --regions us-east-1 \
  --operation-preferences FailureToleranceCount=0,MaxConcurrentCount=5

echo "Deployment complete!"
```

#### 3.2 Deploy Agent

**File: `scripts/deploy_agent.py`**

```python
#!/usr/bin/env python3
import boto3
import subprocess
import sys

def deploy_agent():
    """Deploy agent to AgentCore Runtime."""

    # Build and push Docker image
    print("Building Docker image...")
    subprocess.run([
        "docker", "build", "-t", "central-ops-agent", "agent/"
    ], check=True)

    # Get ECR repository
    ecr = boto3.client('ecr')
    account_id = boto3.client('sts').get_caller_identity()['Account']
    region = 'us-east-1'
    repo_name = 'central-ops-agent'

    # Create ECR repo if needed
    try:
        ecr.create_repository(repositoryName=repo_name)
    except ecr.exceptions.RepositoryAlreadyExistsException:
        pass

    # Login and push
    login_cmd = subprocess.run(
        ["aws", "ecr", "get-login-password", "--region", region],
        capture_output=True, text=True, check=True
    )

    subprocess.run([
        "docker", "login", "--username", "AWS", "--password-stdin",
        f"{account_id}.dkr.ecr.{region}.amazonaws.com"
    ], input=login_cmd.stdout, text=True, check=True)

    image_uri = f"{account_id}.dkr.ecr.{region}.amazonaws.com/{repo_name}:latest"
    subprocess.run(["docker", "tag", "central-ops-agent", image_uri], check=True)
    subprocess.run(["docker", "push", image_uri], check=True)

    print(f"Image pushed: {image_uri}")

    # Deploy to AgentCore
    print("Deploying to AgentCore Runtime...")
    # Use agentcore CLI or boto3 bedrock-agentcore client
    # (API calls depend on AgentCore SDK version)

    print("Deployment complete!")

if __name__ == "__main__":
    deploy_agent()
```

---

## Project Structure (Final)

```
aws-mcp-multi-account-repo/
├── ARCHITECTURE.md                      # This file
├── infrastructure/
│   ├── central-account.yaml             # Central account IAM + S3
│   ├── member-account-role.yaml         # StackSet for member roles
│   └── account-registry.json            # Account metadata (for IAM mode)
├── agent/
│   ├── Dockerfile                       # Container definition
│   ├── requirements.txt                 # Python dependencies
│   ├── central_ops_agent.py             # Main agent with Bedrock
│   ├── multi_account_mcp.py             # MCP client + cred switching
│   ├── account_manager.py               # IAM role assumption + caching
│   ├── sso_account_manager.py           # Identity Center (SSO) credentials
│   └── credential_provider.py           # Factory for IAM vs SSO
├── scripts/
│   ├── deploy_infrastructure.sh         # CloudFormation deployment
│   └── deploy_agent.py                  # Agent deployment
└── tests/
    ├── test_role_assumption.py          # Test IAM role assumption
    ├── test_sso_credentials.py          # Test SSO credential flow
    └── test_mcp_queries.py
```

---

## Verification Plan

### 1. IAM Role Verification

```bash
# Test role assumption from central account
aws sts assume-role \
  --role-arn arn:aws:iam::222222222222:role/CentralOpsTargetRole \
  --role-session-name test-session

# Verify read-only access
aws ec2 describe-instances  # Should work
aws ec2 terminate-instances --instance-ids i-xxx  # Should fail
```

### 2. Identity Center (SSO) Verification

```bash
# Step 1: Login via SSO
aws sso login --profile central-ops-sso

# Step 2: Verify identity
aws sts get-caller-identity --profile central-ops-sso

# Step 3: List accessible accounts (using boto3)
python3 << 'EOF'
import boto3
import json
import glob
import os

# Find SSO token
cache_dir = os.path.expanduser("~/.aws/sso/cache")
for f in glob.glob(f"{cache_dir}/*.json"):
    with open(f) as fp:
        data = json.load(fp)
        if "accessToken" in data:
            token = data["accessToken"]
            break

# List accounts
sso = boto3.client('sso', region_name='us-east-1')
accounts = sso.list_accounts(accessToken=token)
for acc in accounts['accountList']:
    print(f"{acc['accountId']}: {acc['accountName']}")

# Get credentials for first account
if accounts['accountList']:
    acc_id = accounts['accountList'][0]['accountId']
    roles = sso.list_account_roles(accessToken=token, accountId=acc_id)
    role_name = roles['roleList'][0]['roleName']

    creds = sso.get_role_credentials(
        accessToken=token,
        accountId=acc_id,
        roleName=role_name
    )
    print(f"\nCredentials for {acc_id}/{role_name}:")
    print(f"  AccessKeyId: {creds['roleCredentials']['accessKeyId'][:10]}...")
EOF
```

### 3. MCP Proxy Verification

```bash
# Test MCP proxy with assumed credentials (IAM or SSO)
export AWS_ACCESS_KEY_ID=<from-assume-role-or-sso>
export AWS_SECRET_ACCESS_KEY=<from-assume-role-or-sso>
export AWS_SESSION_TOKEN=<from-assume-role-or-sso>

uvx mcp-proxy-for-aws@latest https://aws-mcp.us-east-1.api.aws/mcp \
  --metadata AWS_REGION=us-east-1
```

### 4. End-to-End Tests

```
"List all available accounts"
"Show EC2 instances in account 222222222222"
"List S3 buckets across all accounts"
"What Lambda functions exist in the production account?"
"Describe EKS clusters in staging"
```

### 5. Security Validation

- Verify CloudTrail logs cross-account API calls
- Confirm no write operations succeed
- Check credential expiration handling
- **For SSO**: Verify user identity appears in CloudTrail (not just role ARN)

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Direct MCP proxy vs Gateway | Gateway doesn't support SigV4 for MCP targets |
| Credential caching | Avoid repeated STS/SSO calls; 1-hour TTL with 5-min buffer |
| Dual auth support (IAM + SSO) | IAM for production/AgentCore; SSO for local dev with user identity |
| Static account registry (IAM) | 2-10 accounts; dynamic discovery overkill for IAM mode |
| Dynamic account list (SSO) | SSO provides account list via API; no registry needed |
| Bundled proxy in container | Ensures consistent proxy version |
| Bedrock Claude for orchestration | Natural language understanding + tool calling |
| Credential provider factory | Auto-detect IAM vs SSO based on environment |

---

## References

### AWS MCP Server
- [AWS MCP Server Documentation](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html)
- [mcp-proxy-for-aws](https://github.com/aws/mcp-proxy-for-aws)

### AWS Bedrock AgentCore
- [AWS Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html)
- [AgentCore Gateway Outbound Auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-outbound-auth.html) - **Confirms no SigV4 for MCP**

### Cross-Account Access (IAM)
- [IAM Cross-Account Access Tutorial](https://docs.aws.amazon.com/IAM/latest/UserGuide/tutorial_cross-account-with-roles.html)
- [AWS Organizations StackSets](https://docs.aws.amazon.com/organizations/latest/userguide/services-that-can-integrate-cloudformation.html)

### AWS Identity Center (SSO)
- [IAM Identity Center Credential Provider](https://docs.aws.amazon.com/sdkref/latest/guide/feature-sso-credentials.html)
- [Configuring SSO with AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html)
- [Getting IAM Identity Center Credentials for SDK](https://docs.aws.amazon.com/singlesignon/latest/userguide/howtogetcredentials.html)
- [SSO Boto3 API Reference](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sso.html)
- [Permission Sets Concept](https://docs.aws.amazon.com/singlesignon/latest/userguide/permissionsetsconcept.html)
