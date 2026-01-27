# CLAUDE.md

## Project Overview
Multi-account AWS operations agent with two approaches:
- Direct MCP Proxy: uses `mcp-proxy-for-aws` subprocess
- AgentCore Gateway: CDK-deployed Gateway with Lambda bridge (in `agentcore-gateway/`)

## Commands
- `source .venv/bin/activate` - Activate venv before running Python/pytest
- `pytest agentcore-gateway/tests/ -v` - Run agentcore-gateway tests
- `pytest direct-proxy/tests/ -v` - Run direct-proxy tests
- `python3 scripts/test_integration.py` - Run integration tests
- `./scripts/verify_prerequisites.sh` - Check AWS CLI, uv, credentials, Python
- `cd agentcore-gateway/infrastructure && npx cdk deploy --all` - Deploy 7 CDK stacks (deploys to us-east-1)
- `npx cdk deploy -c deployRuntime=true CentralOps-Runtime-dev` - Deploy Runtime (after ECR image push)
- `npx cdk deploy -c deployRuntime=true -c deployFrontend=true CentralOps-Frontend-dev` - Deploy Frontend stack
- `cd agentcore-gateway/frontend && npm run build && ./scripts/deploy.sh` - Build and deploy frontend to S3/CloudFront
- `aws dynamodb scan --table-name central-ops-accounts-dev --region us-east-1` - List registered accounts

## AgentCore Gateway Architecture
- Gateway created via CDK `CfnGateway` (requires aws-cdk-lib 2.236.0+)
- Lambda bridge handles `query` tool calls to AWS MCP Server (simple bridge, no account config)
- DynamoDB table `central-ops-accounts-{env}` stores account registry (agent queries this)
- Cognito JWT authentication for Gateway access
- AWS MCP Server only available in us-east-1 (Lambda signs requests cross-region)

## Key Files
- `agent/mcp_client.py` - MCP proxy wrapper (subprocess calls)
- `agent/account_manager.py` - Credential caching and role assumption
- `agentcore-gateway/infrastructure/` - CDK stacks for Gateway deployment
- `agentcore-gateway/lambda/handler.py` - Lambda bridge for AWS MCP Server
- `agentcore-gateway/infrastructure/lib/dynamodb-stack.ts` - Account registry table

## Gotchas
- **Region mismatch**: Stacks deploy to us-east-1; always use `--region us-east-1` in AWS CLI commands
- **Stale IAM roles**: If CDK fails with "role already exists", delete manually before retry
- **Frontend stack first deploy**: May fail with Lambda role assumption error; delete stack and redeploy
- **Cognito OAuth callback URLs**: Must match Amplify config exactly (trailing `/` matters)
- **Amplify TypeScript**: Use `as const` for responseType; use `type` imports for ReactNode, AuthUser
- **Runtime URL in CDK**: Token doesn't resolve in outputs; construct manually: `https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{RuntimeArn}/invocations`
- **ECR cross-region**: Copy containers with `docker pull/tag/push` between regions
- MCP protocol requires `initialize` before `tools/list` - one-shot calls fail
- IAM role needs `aws-mcp:InvokeMcp`, `aws-mcp:CallReadOnlyTool`, `aws-mcp:CallReadWriteTool`
- macOS Python is externally-managed; always use `.venv` for pip installs
- Tests mock `subprocess.run` for MCP client (see `tests/test_mcp_client.py`)
- CDK BedrockAgentCore: `protocolConfiguration` is string not object, use `attrGatewayIdentifier`
- Gateway JWT auth: configure ONLY `allowedAudience` for Cognito ID tokens (not allowedClients)
- Lambda Gateway targets: arguments in event, tool name in `context.client_context.custom['bedrockAgentCoreToolName']`
- AWS MCP `aws___call_aws`: requires `cli_command` param starting with "aws"

## Deployment
After `cdk deploy --all`, get resource IDs from stack outputs (use `--region us-east-1`):
- `CentralOps-Gateway-dev.GatewayId` - Gateway identifier
- `CentralOps-Gateway-dev.GatewayUrl` - Gateway MCP endpoint
- `CentralOps-Cognito-dev.UserPoolId` - Cognito user pool
- `CentralOps-Cognito-dev.UserPoolClientId` - Cognito client ID
- `CentralOps-Cognito-dev.UserPoolDomainUrl` - Cognito Hosted UI domain
- `CentralOps-DynamoDB-dev.AccountsTableName` - DynamoDB accounts table
- `CentralOps-Frontend-dev.FrontendUrl` - CloudFront URL for frontend
- `CentralOps-Runtime-dev.RuntimeArn` - Runtime ARN for invocation URL

## Adding New Accounts
1. Deploy `CentralOpsTargetRole` in member account (see README for CLI commands)
2. Add to DynamoDB: `aws dynamodb put-item --table-name central-ops-accounts-dev --region us-east-1 --item '{"account_id":{"S":"ACCOUNT_ID"},"name":{"S":"Name"},"environment":{"S":"prod"},"enabled":{"BOOL":true}}'`
3. Test: Query Gateway with new account_id

## Frontend (agentcore-gateway/frontend/)
- React 18 + TypeScript + Vite + TailwindCSS
- Amplify Auth for Cognito OAuth (PKCE flow via Hosted UI)
- Create `.env` from stack outputs before building (VITE_* variables)
- Test user: `aws cognito-idp admin-set-user-password --user-pool-id POOL_ID --username USER --password "Pass123!" --permanent`
