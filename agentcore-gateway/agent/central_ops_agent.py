"""
CentralOpsAgent - Multi-account AWS operations agent for AgentCore Runtime.

This agent:
1. Receives natural language queries from users
2. Uses Strands Agent with Bedrock Claude to understand intent and call tools
3. Queries DynamoDB for available accounts
4. Calls AgentCore Gateway using MCP JSON-RPC protocol to query AWS resources
"""
import os
import json
import boto3
import urllib.request
from typing import Dict, Any, List

from strands import Agent, tool
from bedrock_agentcore import BedrockAgentCoreApp

# Configuration
GATEWAY_URL = os.environ.get('GATEWAY_URL', '')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
MODEL_ID = os.environ.get('MODEL_ID', 'anthropic.claude-3-5-sonnet-20241022-v2:0')
ACCOUNTS_TABLE_NAME = os.environ.get('ACCOUNTS_TABLE_NAME', '')


def get_accounts_from_dynamodb() -> List[Dict[str, Any]]:
    """Fetch enabled accounts from DynamoDB."""
    if not ACCOUNTS_TABLE_NAME:
        return []

    dynamodb = boto3.client('dynamodb', region_name=AWS_REGION)
    response = dynamodb.scan(
        TableName=ACCOUNTS_TABLE_NAME,
        FilterExpression='enabled = :enabled',
        ExpressionAttributeValues={':enabled': {'BOOL': True}}
    )

    return [{
        'account_id': item.get('account_id', {}).get('S', ''),
        'name': item.get('name', {}).get('S', ''),
        'environment': item.get('environment', {}).get('S', ''),
    } for item in response.get('Items', [])]


def call_gateway_mcp(
    mcp_tool_name: str,
    account_id: str,
    arguments: Dict = None,
    region: str = "us-east-1"
) -> Dict[str, Any]:
    """
    Call AgentCore Gateway using MCP JSON-RPC protocol.
    """
    if not GATEWAY_URL:
        return {"error": "GATEWAY_URL not configured"}

    # Build MCP JSON-RPC request
    mcp_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "bridge-lambda___query",
            "arguments": {
                "account_id": account_id,
                "tool_name": mcp_tool_name,
                "arguments": arguments or {},
                "region": region
            }
        }
    }

    req = urllib.request.Request(
        GATEWAY_URL,
        data=json.dumps(mcp_request).encode(),
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        return {"error": f"Gateway error {e.code}: {error_body}"}
    except Exception as e:
        return {"error": f"Gateway call failed: {str(e)}"}


# Define tools using Strands @tool decorator
@tool
def list_accounts() -> str:
    """
    List all available AWS accounts that can be queried.
    Use this first to discover which accounts are available.
    """
    accounts = get_accounts_from_dynamodb()
    if not accounts:
        return json.dumps({
            "message": "No accounts configured. Please add accounts to the DynamoDB table.",
            "accounts": []
        }, indent=2)
    return json.dumps({"accounts": accounts}, indent=2)


@tool
def query_aws_resources(
    account_id: str,
    cli_command: str,
    region: str = "us-east-1"
) -> str:
    """
    Query AWS resources in a specific account using AWS CLI commands.

    Args:
        account_id: The 12-digit AWS account ID to query
        cli_command: The AWS CLI command to run (e.g., 'aws s3 ls', 'aws ec2 describe-instances')
        region: AWS region to query (default: us-east-1)

    Returns:
        The result of the AWS CLI command
    """
    result = call_gateway_mcp(
        mcp_tool_name="aws___call_aws",
        account_id=account_id,
        arguments={"cli_command": cli_command},
        region=region
    )
    return json.dumps(result, indent=2, default=str)


def build_system_prompt() -> str:
    """Build system prompt with available accounts."""
    accounts = get_accounts_from_dynamodb()
    accounts_info = ""
    if accounts:
        accounts_list = "\n".join([
            f"- {a['name']} ({a['account_id']}) - {a['environment']}"
            for a in accounts
        ])
        accounts_info = f"\n\nAvailable accounts:\n{accounts_list}"

    return f"""You are a helpful AWS operations assistant. You can query AWS resources across multiple accounts.

First, use the list_accounts tool to see which accounts are available, then use query_aws_resources to fetch information.

When using query_aws_resources:
- Provide the account_id (12-digit AWS account ID)
- Provide the cli_command (full AWS CLI command like 'aws s3 ls' or 'aws ec2 describe-instances')
- Optionally specify the region

Common CLI commands:
- aws s3 ls - List S3 buckets
- aws ec2 describe-instances - List EC2 instances
- aws rds describe-db-instances - List RDS databases
- aws lambda list-functions - List Lambda functions
{accounts_info}"""


# Create the Strands Agent with tools
agent = Agent(
    model=MODEL_ID,
    system_prompt=build_system_prompt(),
    tools=[list_accounts, query_aws_resources]
)

# AgentCore Runtime app
app = BedrockAgentCoreApp()


@app.entrypoint
async def agent_invocation(payload):
    """Handler for agent invocation with streaming."""
    prompt = payload.get("prompt", "")

    if not prompt:
        yield {"response": "Please provide a prompt."}
        return

    try:
        stream = agent.stream_async(prompt)
        async for event in stream:
            print(event)
            yield event
    except Exception as e:
        yield {"error": str(e)}


if __name__ == "__main__":
    app.run()
