# CLAUDE.md

## Project Overview
Multi-account AWS operations agent using Direct MCP Proxy approach with `mcp-proxy-for-aws`.

## Commands
- `source .venv/bin/activate` - Activate venv before running Python/pytest
- `pytest tests/ -v` - Run all unit tests
- `python3 scripts/test_integration.py` - Run integration tests
- `./scripts/verify_prerequisites.sh` - Check AWS CLI, uv, credentials, Python

## Architecture
- Agent uses `mcp-proxy-for-aws` via subprocess to call AWS MCP Server
- MCP Server requires SigV4 auth (proxy handles this)
- Cross-account access via STS AssumeRole with credential caching

## Key Files
- `agent/mcp_client.py` - MCP proxy wrapper (subprocess calls)
- `agent/account_manager.py` - Credential caching and role assumption
- `infrastructure/account-registry.json` - Account config (gitignored, has real IDs)

## Gotchas
- MCP protocol requires `initialize` before `tools/list` - one-shot calls fail
- IAM user needs `aws-mcp:InvokeMcp`, `aws-mcp:CallReadOnlyTool` permissions
- macOS Python is externally-managed; always use `.venv` for pip installs
- Tests mock `subprocess.run` for MCP client (see `tests/test_mcp_client.py`)

## Next Steps (from plan)
- Implement `MultiAccountMCPClient` for credential switching
- Implement `CentralOpsAgent` with Bedrock Claude
- Containerize and deploy to AgentCore Runtime
