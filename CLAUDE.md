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
- `cd agentcore-gateway/infrastructure && npx cdk deploy --all -c region=us-west-2` - Deploy CDK stacks
- `npx cdk deploy -c deployRuntime=true CentralOps-Runtime-dev` - Deploy Runtime (after ECR image push)

## AgentCore Gateway Architecture
- Gateway created via CDK `CfnGateway` (requires aws-cdk-lib 2.236.0+)
- Lambda bridge handles MCP tool calls to AWS MCP Server
- Cognito JWT authentication for Gateway access
- AWS MCP Server only available in us-east-1 (Lambda signs requests cross-region)

## Key Files
- `agent/mcp_client.py` - MCP proxy wrapper (subprocess calls)
- `agent/account_manager.py` - Credential caching and role assumption
- `agentcore-gateway/infrastructure/` - CDK stacks for Gateway deployment
- `agentcore-gateway/lambda/handler.py` - Lambda bridge for AWS MCP Server

## Gotchas
- MCP protocol requires `initialize` before `tools/list` - one-shot calls fail
- IAM role needs `aws-mcp:InvokeMcp`, `aws-mcp:CallReadOnlyTool`, `aws-mcp:CallReadWriteTool`
- macOS Python is externally-managed; always use `.venv` for pip installs
- Tests mock `subprocess.run` for MCP client (see `tests/test_mcp_client.py`)
- CDK BedrockAgentCore: `protocolConfiguration` is string not object, use `attrGatewayIdentifier`
- Gateway JWT auth: configure ONLY `allowedAudience` for Cognito ID tokens (not allowedClients)
- Lambda Gateway targets: arguments in event, tool name in `context.client_context.custom['bedrockAgentCoreToolName']`
- AWS MCP `aws___call_aws`: requires `cli_command` param starting with "aws"

## Deployed Resources (us-west-2)
- Gateway: `centralopsgatewaydev-cv4hmvkwce`
- Gateway URL: `https://centralopsgatewaydev-cv4hmvkwce.gateway.bedrock-agentcore.us-west-2.amazonaws.com/mcp`
- Cognito User Pool: `us-west-2_MQN3BQWa2`
- Cognito Client ID: `798pr5p3b8vl2mgospsqdjb05j`
