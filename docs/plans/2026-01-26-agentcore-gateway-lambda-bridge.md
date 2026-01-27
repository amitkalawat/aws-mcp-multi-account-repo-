# AgentCore Gateway with Lambda Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restructure the repository into two separate implementations (Direct MCP Proxy and AgentCore Gateway) and implement the full AgentCore stack: Runtime Agent + Gateway + Lambda Bridge for AWS MCP Server access.

**Architecture:** CentralOpsAgent runs on AgentCore Runtime, calls Gateway using Workload Identity tokens. Gateway invokes Lambda Bridge with SigV4. Lambda assumes cross-account roles and calls AWS MCP Server with SigV4 signing.

**Tech Stack:** Python 3.12 (Runtime + Lambda), boto3, bedrock-agentcore SDK, **AWS CDK (TypeScript)**, AgentCore Gateway, AWS MCP Server

---

## Full Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              AGENTCORE RUNTIME                                   │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │  CentralOpsAgent                                                          │  │
│  │  - Bedrock Claude for natural language                                    │  │
│  │  - Tool: query_aws_resources → calls Gateway                              │  │
│  │  - Gets Workload Access Token automatically                               │  │
│  └───────────────────────────────┬───────────────────────────────────────────┘  │
└──────────────────────────────────┼──────────────────────────────────────────────┘
                                   │ Authorization: Bearer <workload_token>
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              AGENTCORE GATEWAY                                   │
│  ┌─────────────────────────┐         ┌───────────────────────────────────────┐  │
│  │  Inbound Auth:          │         │  Outbound Auth:                       │  │
│  │  - No auth (internal)   │         │  - SigV4 (service role → Lambda)      │  │
│  │  - OR Workload Identity │         │  - Automatic via Gateway role         │  │
│  └─────────────────────────┘         └───────────────────────────────────────┘  │
└──────────────────────────────────────────┬──────────────────────────────────────┘
                                           │ lambda:InvokeFunction (SigV4)
                                           ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              BRIDGE LAMBDA                                       │
│  1. Parse request (tool_name, account_id, arguments)                            │
│  2. STS AssumeRole → target account credentials                                 │
│  3. Call AWS MCP Server with SigV4 (target account creds)                       │
└──────────────────────────────────────────┬──────────────────────────────────────┘
                                           │ SigV4 (target account)
                                           ▼
                          ┌────────────────────────────────────┐
                          │         AWS MCP SERVER             │
                          │  https://aws-mcp.us-east-1.api.aws │
                          └────────────────┬───────────────────┘
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    ▼                                             ▼
         ┌──────────────────┐                          ┌──────────────────┐
         │  Member Account  │                          │  Member Account  │
         │  CentralOpsRole  │                          │  CentralOpsRole  │
         └──────────────────┘                          └──────────────────┘
```

---

## Authentication Flow

| Hop | From → To | Auth Method | How It Works |
|-----|-----------|-------------|--------------|
| 1 | Client → Runtime | **JWT (Cognito)** | Client authenticates via Cognito, sends Bearer token |
| 2 | Runtime → Gateway | Workload Identity | Runtime auto-gets token via AgentCore Identity |
| 3 | Gateway → Lambda | SigV4 | Gateway's service role invokes Lambda (automatic) |
| 4 | Lambda → MCP Server | SigV4 | Lambda uses assumed role credentials |

**Key insight**: Gateway-to-Lambda auth is **automatic**. Runtime uses JWT authorizer for inbound client requests, with Cognito (or external IdP) as the identity provider.

---

## Phase 1: Repository Restructure

### Task 1: Create Directory Structure for Both Approaches ✅ COMPLETED

**Files:**
- Create: `direct-proxy/` (move existing code)
- Create: `agentcore-gateway/` (new implementation)

Commit: `847134c` - "refactor: restructure repo for dual architecture approach"

---

### Task 2: Update Root README for Dual Architecture

**Files:**
- Modify: `README.md`

**Step 1: Read current README**

Run: Read `README.md` to understand current structure

**Step 2: Update README with dual approach**

Replace `README.md` with content explaining both approaches:
- Direct MCP Proxy (`direct-proxy/`)
- AgentCore Gateway (`agentcore-gateway/`)
- Comparison table
- Quick Start sections for both

**Step 3: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: update README for dual architecture approach

Explain both implementation options with comparison table.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2: AgentCore Gateway Infrastructure (CDK)

### Task 3: Initialize CDK Project

**Files:**
- Create: `agentcore-gateway/infrastructure/` CDK project

**Step 1: Initialize CDK TypeScript project**

```bash
cd agentcore-gateway/infrastructure
npx cdk init app --language typescript
```

**Step 2: Install dependencies**

```bash
npm install @aws-cdk/aws-cognito @aws-cdk/aws-lambda @aws-cdk/aws-iam @aws-cdk/aws-logs
```

**Step 3: Update package.json with project metadata**

**Step 4: Commit**

```bash
git add agentcore-gateway/infrastructure/
git commit -m "$(cat <<'EOF'
feat(gateway): initialize CDK TypeScript project

CDK infrastructure for AgentCore Gateway stack.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Create Lambda Bridge Handler with Tests

**Files:**
- Create: `agentcore-gateway/lambda/handler.py`
- Create: `agentcore-gateway/tests/test_handler.py`

**Step 1: Write the failing test**

```python
# agentcore-gateway/tests/test_handler.py
"""Tests for Lambda bridge handler."""
import json
import pytest
from unittest.mock import patch, MagicMock


def test_list_accounts_action():
    """Test list_accounts action returns configured accounts."""
    with patch.dict('os.environ', {'TARGET_ACCOUNTS': '[{"id":"222222222222","name":"Production"}]'}):
        from lambda_code.handler import handler

        event = {'body': json.dumps({'action': 'list_accounts'})}
        result = handler(event, None)

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert len(body) == 1
        assert body[0]['id'] == '222222222222'


def test_unknown_action_returns_400():
    """Test unknown action returns 400 error."""
    with patch.dict('os.environ', {'TARGET_ACCOUNTS': '[]'}):
        from lambda_code.handler import handler

        event = {'body': json.dumps({'action': 'invalid_action'})}
        result = handler(event, None)

        assert result['statusCode'] == 400
        body = json.loads(result['body'])
        assert 'error' in body


@patch('lambda_code.handler.call_aws_mcp')
def test_query_action_calls_mcp(mock_call_mcp):
    """Test query action calls AWS MCP Server."""
    mock_call_mcp.return_value = {'result': {'content': [{'text': 'test'}]}}

    with patch.dict('os.environ', {'TARGET_ACCOUNTS': '[]'}):
        from lambda_code.handler import handler

        event = {'body': json.dumps({
            'action': 'query',
            'tool_name': 'ec2_describe_instances',
            'account_id': '222222222222',
            'arguments': {}
        })}
        result = handler(event, None)

        assert result['statusCode'] == 200
        mock_call_mcp.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `cd agentcore-gateway && PYTHONPATH=. pytest tests/test_handler.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write the implementation**

Create `agentcore-gateway/lambda/handler.py` with:
- `get_credentials()`: STS AssumeRole with caching
- `call_aws_mcp()`: SigV4 signed calls to MCP Server
- `handler()`: Lambda entry point handling list_accounts, query, query_all

**Step 4: Run test to verify it passes**

**Step 5: Commit**

```bash
git add agentcore-gateway/lambda/handler.py agentcore-gateway/tests/test_handler.py
git commit -m "$(cat <<'EOF'
feat(gateway): implement Lambda bridge handler

- Handle list_accounts, query, query_all actions
- SigV4 signing for AWS MCP Server calls
- Credential caching with 5-minute refresh buffer

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Create CDK Cognito Stack

**Files:**
- Create: `agentcore-gateway/infrastructure/lib/cognito-stack.ts`

**Step 1: Write the Cognito stack**

```typescript
// agentcore-gateway/infrastructure/lib/cognito-stack.ts
import * as cdk from 'aws-cdk-lib';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import { Construct } from 'constructs';

export interface CognitoStackProps extends cdk.StackProps {
  environment: string;
}

export class CognitoStack extends cdk.Stack {
  public readonly userPool: cognito.UserPool;
  public readonly userPoolClient: cognito.UserPoolClient;
  public readonly discoveryUrl: string;

  constructor(scope: Construct, id: string, props: CognitoStackProps) {
    super(scope, id, props);

    this.userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: `central-ops-${props.environment}`,
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      autoVerify: { email: true },
      passwordPolicy: {
        minLength: 12,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
      },
    });

    this.userPoolClient = new cognito.UserPoolClient(this, 'UserPoolClient', {
      userPool: this.userPool,
      userPoolClientName: `central-ops-client-${props.environment}`,
      generateSecret: false,
      authFlows: {
        userPassword: true,
        userSrp: true,
      },
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
      refreshTokenValidity: cdk.Duration.days(30),
    });

    this.discoveryUrl = `https://cognito-idp.${this.region}.amazonaws.com/${this.userPool.userPoolId}/.well-known/openid-configuration`;

    // Outputs
    new cdk.CfnOutput(this, 'UserPoolId', { value: this.userPool.userPoolId });
    new cdk.CfnOutput(this, 'UserPoolClientId', { value: this.userPoolClient.userPoolClientId });
    new cdk.CfnOutput(this, 'DiscoveryUrl', { value: this.discoveryUrl });
  }
}
```

**Step 2: Synthesize to verify**

Run: `cd agentcore-gateway/infrastructure && npx cdk synth CognitoStack`
Expected: Valid CloudFormation template output

**Step 3: Commit**

```bash
git add agentcore-gateway/infrastructure/lib/cognito-stack.ts
git commit -m "$(cat <<'EOF'
feat(cdk): add Cognito stack for JWT authentication

User pool for Runtime inbound JWT authentication.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Create CDK Lambda Stack

**Files:**
- Create: `agentcore-gateway/infrastructure/lib/lambda-stack.ts`

**Step 1: Write the Lambda stack**

```typescript
// agentcore-gateway/infrastructure/lib/lambda-stack.ts
import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import * as path from 'path';

export interface LambdaStackProps extends cdk.StackProps {
  environment: string;
  targetAccounts: string; // JSON string
  organizationId?: string;
}

export class LambdaStack extends cdk.Stack {
  public readonly bridgeLambda: lambda.Function;
  public readonly bridgeLambdaRole: iam.Role;

  constructor(scope: Construct, id: string, props: LambdaStackProps) {
    super(scope, id, props);

    // Lambda execution role
    this.bridgeLambdaRole = new iam.Role(this, 'BridgeLambdaRole', {
      roleName: `CentralOpsBridgeRole-${props.environment}`,
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });

    // Cross-account assume role policy
    const assumeRolePolicy = new iam.PolicyStatement({
      actions: ['sts:AssumeRole'],
      resources: ['arn:aws:iam::*:role/CentralOpsTargetRole'],
    });
    if (props.organizationId) {
      assumeRolePolicy.addCondition('StringEquals', {
        'aws:PrincipalOrgID': props.organizationId,
      });
    }
    this.bridgeLambdaRole.addToPolicy(assumeRolePolicy);

    // AWS MCP access policy
    this.bridgeLambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: ['aws-mcp:InvokeMcp', 'aws-mcp:CallReadOnlyTool'],
      resources: ['*'],
    }));

    // Lambda function
    this.bridgeLambda = new lambda.Function(this, 'BridgeLambda', {
      functionName: `aws-mcp-bridge-${props.environment}`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../lambda')),
      role: this.bridgeLambdaRole,
      timeout: cdk.Duration.seconds(120),
      memorySize: 256,
      environment: {
        TARGET_ACCOUNTS: props.targetAccounts,
        TARGET_ROLE_NAME: 'CentralOpsTargetRole',
      },
      logRetention: logs.RetentionDays.TWO_WEEKS,
    });

    // Outputs
    new cdk.CfnOutput(this, 'LambdaArn', { value: this.bridgeLambda.functionArn });
    new cdk.CfnOutput(this, 'LambdaRoleArn', { value: this.bridgeLambdaRole.roleArn });
  }
}
```

**Step 2: Synthesize to verify**

Run: `cd agentcore-gateway/infrastructure && npx cdk synth LambdaStack`
Expected: Valid CloudFormation template output

**Step 3: Commit**

```bash
git add agentcore-gateway/infrastructure/lib/lambda-stack.ts
git commit -m "$(cat <<'EOF'
feat(cdk): add Lambda stack for bridge function

Lambda with cross-account role assumption and MCP access.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Create CDK Gateway Roles Stack

**Files:**
- Create: `agentcore-gateway/infrastructure/lib/roles-stack.ts`

**Step 1: Write the roles stack**

```typescript
// agentcore-gateway/infrastructure/lib/roles-stack.ts
import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Construct } from 'constructs';

export interface RolesStackProps extends cdk.StackProps {
  environment: string;
  bridgeLambda: lambda.IFunction;
}

export class RolesStack extends cdk.Stack {
  public readonly gatewayRole: iam.Role;
  public readonly runtimeRole: iam.Role;

  constructor(scope: Construct, id: string, props: RolesStackProps) {
    super(scope, id, props);

    // Gateway Service Role
    this.gatewayRole = new iam.Role(this, 'GatewayServiceRole', {
      roleName: `CentralOpsGatewayRole-${props.environment}`,
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
    });

    this.gatewayRole.addToPolicy(new iam.PolicyStatement({
      actions: ['lambda:InvokeFunction'],
      resources: [props.bridgeLambda.functionArn],
    }));

    // Runtime Execution Role
    this.runtimeRole = new iam.Role(this, 'RuntimeExecutionRole', {
      roleName: `CentralOpsRuntimeRole-${props.environment}`,
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
    });

    // Bedrock access
    this.runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
      resources: [`arn:aws:bedrock:${this.region}::foundation-model/anthropic.claude-*`],
    }));

    // AgentCore Identity access
    this.runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:GetWorkloadAccessToken', 'bedrock-agentcore:GetWorkloadAccessTokenForJWT'],
      resources: [
        `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default`,
        `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default/workload-identity/*`,
      ],
    }));

    // Gateway invoke access
    this.runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:InvokeGateway'],
      resources: [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:gateway/*`],
    }));

    // CloudWatch Logs access
    this.runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
      resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*`],
    }));

    // Outputs
    new cdk.CfnOutput(this, 'GatewayRoleArn', { value: this.gatewayRole.roleArn });
    new cdk.CfnOutput(this, 'RuntimeRoleArn', { value: this.runtimeRole.roleArn });
  }
}
```

**Step 2: Synthesize to verify**

**Step 3: Commit**

```bash
git add agentcore-gateway/infrastructure/lib/roles-stack.ts
git commit -m "$(cat <<'EOF'
feat(cdk): add Gateway and Runtime roles stack

IAM roles for AgentCore Gateway and Runtime execution.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Create CDK Member Account Stack

**Files:**
- Create: `agentcore-gateway/infrastructure/lib/member-account-stack.ts`

**Step 1: Write the member account stack**

```typescript
// agentcore-gateway/infrastructure/lib/member-account-stack.ts
import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface MemberAccountStackProps extends cdk.StackProps {
  centralAccountId: string;
  bridgeLambdaRoleArn: string;
}

export class MemberAccountStack extends cdk.Stack {
  public readonly targetRole: iam.Role;

  constructor(scope: Construct, id: string, props: MemberAccountStackProps) {
    super(scope, id, props);

    this.targetRole = new iam.Role(this, 'CentralOpsTargetRole', {
      roleName: 'CentralOpsTargetRole',
      assumedBy: new iam.ArnPrincipal(props.bridgeLambdaRoleArn),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('ReadOnlyAccess'),
      ],
    });

    // AWS MCP access
    this.targetRole.addToPolicy(new iam.PolicyStatement({
      actions: ['aws-mcp:InvokeMcp', 'aws-mcp:CallReadOnlyTool'],
      resources: ['*'],
    }));

    // Add condition for central account
    const cfnRole = this.targetRole.node.defaultChild as iam.CfnRole;
    cfnRole.addPropertyOverride('AssumeRolePolicyDocument.Statement.0.Condition', {
      StringEquals: {
        'aws:PrincipalAccount': props.centralAccountId,
      },
    });

    // Outputs
    new cdk.CfnOutput(this, 'TargetRoleArn', { value: this.targetRole.roleArn });
  }
}
```

**Step 2: Commit**

```bash
git add agentcore-gateway/infrastructure/lib/member-account-stack.ts
git commit -m "$(cat <<'EOF'
feat(cdk): add member account target role stack

Read-only role for member accounts, deployable via StackSet.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Create CDK Main App Entry Point

**Files:**
- Modify: `agentcore-gateway/infrastructure/bin/infrastructure.ts`
- Create: `agentcore-gateway/infrastructure/config/accounts.json`

**Step 1: Update main CDK app**

```typescript
// agentcore-gateway/infrastructure/bin/infrastructure.ts
#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { CognitoStack } from '../lib/cognito-stack';
import { LambdaStack } from '../lib/lambda-stack';
import { RolesStack } from '../lib/roles-stack';
import * as fs from 'fs';
import * as path from 'path';

const app = new cdk.App();

const environment = app.node.tryGetContext('environment') || 'dev';
const region = app.node.tryGetContext('region') || 'us-east-1';

// Load account configuration
const configPath = path.join(__dirname, '../config/accounts.json');
let targetAccounts = '[]';
if (fs.existsSync(configPath)) {
  const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
  targetAccounts = JSON.stringify(config.accounts.filter((a: any) => a.role !== 'central'));
}

const env = { region };

// Cognito Stack
const cognitoStack = new CognitoStack(app, `CentralOps-Cognito-${environment}`, {
  environment,
  env,
});

// Lambda Stack
const lambdaStack = new LambdaStack(app, `CentralOps-Lambda-${environment}`, {
  environment,
  targetAccounts,
  env,
});

// Roles Stack (depends on Lambda)
const rolesStack = new RolesStack(app, `CentralOps-Roles-${environment}`, {
  environment,
  bridgeLambda: lambdaStack.bridgeLambda,
  env,
});
rolesStack.addDependency(lambdaStack);
```

**Step 2: Create accounts template**

```json
{
  "accounts": [
    {
      "id": "111111111111",
      "name": "Central Operations",
      "environment": "ops",
      "role": "central"
    },
    {
      "id": "222222222222",
      "name": "Production",
      "environment": "prod",
      "role": "workload"
    }
  ]
}
```

**Step 3: Commit**

```bash
git add agentcore-gateway/infrastructure/
git commit -m "$(cat <<'EOF'
feat(cdk): add main CDK app entry point

Orchestrates all stacks with environment configuration.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3: AgentCore Runtime Agent

### Task 10: Create CentralOpsAgent

**Files:**
- Create: `agentcore-gateway/agent/central_ops_agent.py`
- Create: `agentcore-gateway/tests/test_central_ops_agent.py`

(Same as before - Python agent code with Bedrock Claude integration)

**Step 1: Write failing test**
**Step 2: Write implementation**
**Step 3: Run tests**
**Step 4: Commit**

---

### Task 11: Create Agent Requirements

**Files:**
- Create: `agentcore-gateway/agent/requirements.txt`

```text
boto3>=1.35.0
bedrock-agentcore>=0.1.0
```

**Commit message:** "feat(runtime): add agent requirements"

---

### Task 12: Create AgentCore Configuration (with JWT Authorizer)

**Files:**
- Create: `agentcore-gateway/agent/.bedrock_agentcore.yaml`

(Same as before - YAML config with JWT authorizer)

---

### Task 13: Create Deployment Script

**Files:**
- Create: `agentcore-gateway/scripts/deploy.sh`

**Step 1: Write deployment script using CDK**

```bash
#!/bin/bash
# agentcore-gateway/scripts/deploy.sh
# Deploy AgentCore Gateway + Runtime infrastructure using CDK

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="${SCRIPT_DIR}/../infrastructure"
AGENT_DIR="${SCRIPT_DIR}/../agent"

# Configuration
ENVIRONMENT="${ENVIRONMENT:-dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI not found"
        exit 1
    fi

    if ! command -v npx &> /dev/null; then
        log_error "Node.js/npx not found - required for CDK"
        exit 1
    fi

    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS credentials not valid"
        exit 1
    fi

    log_info "Prerequisites OK"
}

install_cdk_deps() {
    log_info "Installing CDK dependencies..."
    cd "${INFRA_DIR}"
    npm install
    cd - > /dev/null
}

bootstrap_cdk() {
    log_info "Bootstrapping CDK (if needed)..."
    cd "${INFRA_DIR}"
    npx cdk bootstrap --context environment="${ENVIRONMENT}" --context region="${AWS_REGION}" || true
    cd - > /dev/null
}

deploy_stacks() {
    log_info "Deploying CDK stacks..."
    cd "${INFRA_DIR}"
    npx cdk deploy --all \
        --context environment="${ENVIRONMENT}" \
        --context region="${AWS_REGION}" \
        --require-approval never
    cd - > /dev/null
}

get_outputs() {
    log_info "Getting stack outputs..."

    COGNITO_USER_POOL_ID=$(aws cloudformation describe-stacks \
        --stack-name "CentralOps-Cognito-${ENVIRONMENT}" \
        --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
        --output text --region "${AWS_REGION}")

    COGNITO_CLIENT_ID=$(aws cloudformation describe-stacks \
        --stack-name "CentralOps-Cognito-${ENVIRONMENT}" \
        --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' \
        --output text --region "${AWS_REGION}")

    COGNITO_DISCOVERY_URL=$(aws cloudformation describe-stacks \
        --stack-name "CentralOps-Cognito-${ENVIRONMENT}" \
        --query 'Stacks[0].Outputs[?OutputKey==`DiscoveryUrl`].OutputValue' \
        --output text --region "${AWS_REGION}")

    LAMBDA_ARN=$(aws cloudformation describe-stacks \
        --stack-name "CentralOps-Lambda-${ENVIRONMENT}" \
        --query 'Stacks[0].Outputs[?OutputKey==`LambdaArn`].OutputValue' \
        --output text --region "${AWS_REGION}")

    GATEWAY_ROLE_ARN=$(aws cloudformation describe-stacks \
        --stack-name "CentralOps-Roles-${ENVIRONMENT}" \
        --query 'Stacks[0].Outputs[?OutputKey==`GatewayRoleArn`].OutputValue' \
        --output text --region "${AWS_REGION}")

    RUNTIME_ROLE_ARN=$(aws cloudformation describe-stacks \
        --stack-name "CentralOps-Roles-${ENVIRONMENT}" \
        --query 'Stacks[0].Outputs[?OutputKey==`RuntimeRoleArn`].OutputValue' \
        --output text --region "${AWS_REGION}")
}

print_gateway_commands() {
    log_info "Gateway and Runtime CLI Commands"
    log_warn "Run these commands manually after CDK deployment:"
    echo ""
    echo "# 1. Create Gateway"
    echo "aws bedrock-agentcore-control create-gateway \\"
    echo "  --gateway-name central-ops-gateway-${ENVIRONMENT} \\"
    echo "  --role-arn ${GATEWAY_ROLE_ARN}"
    echo ""
    echo "# 2. Add Lambda target to Gateway"
    echo "aws bedrock-agentcore-control create-gateway-target \\"
    echo "  --gateway-identifier central-ops-gateway-${ENVIRONMENT} \\"
    echo "  --name bridge-lambda \\"
    echo "  --target-configuration '{\"lambdaTargetConfiguration\": {\"lambdaArn\": \"${LAMBDA_ARN}\"}}'"
    echo ""
    echo "# 3. Deploy Runtime Agent with JWT auth"
    echo "cd ${AGENT_DIR}"
    echo "agentcore deploy --execution-role ${RUNTIME_ROLE_ARN}"
    echo ""
}

print_summary() {
    echo ""
    log_info "=========================================="
    log_info "Deployment Summary"
    log_info "=========================================="
    log_info "Environment: ${ENVIRONMENT}"
    log_info "Region: ${AWS_REGION}"
    echo ""
    log_info "CDK Stacks:"
    log_info "  Cognito:  CentralOps-Cognito-${ENVIRONMENT}"
    log_info "  Lambda:   CentralOps-Lambda-${ENVIRONMENT}"
    log_info "  Roles:    CentralOps-Roles-${ENVIRONMENT}"
    echo ""
    log_info "Resources:"
    log_info "  Cognito Pool:    ${COGNITO_USER_POOL_ID}"
    log_info "  Cognito Client:  ${COGNITO_CLIENT_ID}"
    log_info "  Discovery URL:   ${COGNITO_DISCOVERY_URL}"
    log_info "  Lambda ARN:      ${LAMBDA_ARN}"
    log_info "  Gateway Role:    ${GATEWAY_ROLE_ARN}"
    log_info "  Runtime Role:    ${RUNTIME_ROLE_ARN}"
    log_info "=========================================="
}

main() {
    check_prerequisites
    install_cdk_deps
    bootstrap_cdk
    deploy_stacks
    get_outputs
    print_gateway_commands
    print_summary
}

main "$@"
```

**Step 2: Make executable**

**Step 3: Commit**

---

### Task 14: Create Gateway README

**Files:**
- Create: `agentcore-gateway/README.md`

(Updated to reference CDK instead of CloudFormation)

---

### Task 15: Create Direct Proxy README

**Files:**
- Create: `direct-proxy/README.md`

(Same as before)

---

### Task 16: Final Verification

**Steps:**
1. Verify directory structure
2. Run Direct Proxy tests
3. Run AgentCore Gateway tests
4. Synthesize all CDK stacks: `cd agentcore-gateway/infrastructure && npx cdk synth`
5. Verify git status is clean

---

## Summary

After completing this plan, you will have:

### Repository Structure
```
aws-mcp-multi-account-repo/
├── direct-proxy/           # Local/container deployment
│   ├── agent/
│   ├── tests/
│   ├── scripts/
│   └── infrastructure/
├── agentcore-gateway/      # Full AgentCore stack
│   ├── agent/              # CentralOpsAgent (Runtime)
│   ├── lambda/             # Bridge Lambda (Python)
│   ├── infrastructure/     # CDK TypeScript project
│   │   ├── bin/
│   │   ├── lib/
│   │   │   ├── cognito-stack.ts
│   │   │   ├── lambda-stack.ts
│   │   │   ├── roles-stack.ts
│   │   │   └── member-account-stack.ts
│   │   └── config/
│   ├── tests/
│   └── scripts/
└── README.md               # Comparison of approaches
```

### AgentCore Stack Components
1. **Cognito Stack (CDK)** - User Pool for JWT authentication
2. **Lambda Stack (CDK)** - Bridge Lambda with IAM role
3. **Roles Stack (CDK)** - Gateway and Runtime IAM roles
4. **Member Account Stack (CDK)** - Target role for StackSet deployment
5. **CentralOpsAgent** - Bedrock Claude agent with tool calling

### Authentication Chain
```
Client → Runtime (JWT/Cognito) → Gateway (Workload ID) → Lambda (SigV4) → MCP (SigV4)
```

## Total: 16 tasks, ~16 commits

---

## Sources

- [AgentCore Runtime Authentication](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)
- [AgentCore Gateway Authorization](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-using-auth.html)
- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/v2/guide/home.html)
