"""
CentralOpsAgent - Multi-account AWS operations agent for AgentCore Runtime.

This agent:
1. Receives natural language queries from users
2. Uses Bedrock Claude to understand intent and call tools
3. Queries DynamoDB for available accounts
4. Calls AgentCore Gateway using MCP JSON-RPC protocol to query AWS resources
"""
import os
import json
import boto3
import urllib.request
from typing import Dict, Any, List, AsyncGenerator

# Configuration
GATEWAY_URL = os.environ.get('GATEWAY_URL', '')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
MODEL_ID = os.environ.get('MODEL_ID', 'anthropic.claude-3-5-sonnet-20241022-v2:0')
ACCOUNTS_TABLE_NAME = os.environ.get('ACCOUNTS_TABLE_NAME', '')


def get_accounts() -> List[Dict[str, Any]]:
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


def build_tools() -> List[Dict[str, Any]]:
    """Build tool definitions for Bedrock Converse API."""
    return [
        {
            "name": "list_accounts",
            "description": "List all available AWS accounts that can be queried. Use this first to discover which accounts are available.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "name": "query_aws_resources",
            "description": "Query AWS resources in a specific account using AWS MCP Server tools. Use this to get information about EC2 instances, S3 buckets, RDS databases, Lambda functions, etc.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "account_id": {
                            "type": "string",
                            "description": "The 12-digit AWS account ID to query"
                        },
                        "tool_name": {
                            "type": "string",
                            "description": "The MCP tool name (e.g., 'aws___call_aws' for AWS CLI commands)"
                        },
                        "arguments": {
                            "type": "object",
                            "description": "Arguments to pass to the MCP tool. For aws___call_aws, use {'cli_command': 'aws s3 ls'}",
                            "default": {}
                        },
                        "region": {
                            "type": "string",
                            "description": "AWS region to query",
                            "default": "us-east-1"
                        }
                    },
                    "required": ["account_id", "tool_name"]
                }
            }
        }
    ]


def call_gateway_mcp(
    gateway_url: str,
    workload_token: str,
    mcp_tool_name: str,
    account_id: str,
    arguments: Dict = None,
    region: str = "us-east-1"
) -> Dict[str, Any]:
    """
    Call AgentCore Gateway using MCP JSON-RPC protocol.

    Args:
        gateway_url: Gateway endpoint URL
        workload_token: Workload access token from AgentCore Identity
        mcp_tool_name: MCP tool name (e.g., 'aws___call_aws')
        account_id: Target account ID
        arguments: Tool arguments
        region: AWS region

    Returns:
        Gateway response
    """
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
        gateway_url,
        data=json.dumps(mcp_request).encode(),
        headers={
            "Authorization": f"Bearer {workload_token}",
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


def process_tool_call(
    tool_name: str,
    tool_input: Dict[str, Any],
    workload_token: str
) -> str:
    """
    Process a tool call from the LLM.

    Args:
        tool_name: Name of the tool being called
        tool_input: Tool input parameters
        workload_token: Workload access token

    Returns:
        Tool result as string
    """
    if tool_name == "list_accounts":
        accounts = get_accounts()
        if not accounts:
            return json.dumps({
                "message": "No accounts configured. Please add accounts to the DynamoDB table.",
                "accounts": []
            }, indent=2)
        return json.dumps({"accounts": accounts}, indent=2)

    elif tool_name == "query_aws_resources":
        result = call_gateway_mcp(
            gateway_url=GATEWAY_URL,
            workload_token=workload_token,
            mcp_tool_name=tool_input.get("tool_name", "aws___call_aws"),
            account_id=tool_input["account_id"],
            arguments=tool_input.get("arguments", {}),
            region=tool_input.get("region", "us-east-1")
        )
        return json.dumps(result, indent=2, default=str)

    return json.dumps({"error": f"Unknown tool: {tool_name}"})


def get_system_prompt() -> str:
    """Build system prompt with available accounts."""
    accounts = get_accounts()
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
- Use tool_name: "aws___call_aws" with arguments: {{"cli_command": "aws <service> <command>"}}
- Example: {{"tool_name": "aws___call_aws", "arguments": {{"cli_command": "aws s3 ls"}}, "account_id": "123456789012"}}

Common CLI commands:
- aws s3 ls - List S3 buckets
- aws ec2 describe-instances - List EC2 instances
- aws rds describe-db-instances - List RDS databases
- aws lambda list-functions - List Lambda functions
{accounts_info}"""


async def converse_with_tools_streaming(
    prompt: str,
    workload_token: str,
    bedrock_client=None
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Process user prompt with Bedrock Claude, handling tool calls with streaming.

    Args:
        prompt: User's natural language query
        workload_token: Workload access token for Gateway calls
        bedrock_client: Optional Bedrock client (for testing)

    Yields:
        Response chunks
    """
    if bedrock_client is None:
        bedrock_client = boto3.client('bedrock-runtime', region_name=AWS_REGION)

    tools = build_tools()
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    system_prompt = get_system_prompt()

    max_iterations = 10
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        try:
            # Use streaming for the response
            response = bedrock_client.converse_stream(
                modelId=MODEL_ID,
                messages=messages,
                system=[{"text": system_prompt}],
                toolConfig={"tools": [{"toolSpec": t} for t in tools]}
            )

            # Collect the full response while streaming text
            assistant_content = []
            current_text = ""
            current_tool_use = None
            tool_use_input_json = ""
            stop_reason = None

            for event in response.get('stream', []):
                if 'contentBlockStart' in event:
                    block_start = event['contentBlockStart']
                    if 'toolUse' in block_start.get('start', {}):
                        current_tool_use = {
                            'toolUseId': block_start['start']['toolUse']['toolUseId'],
                            'name': block_start['start']['toolUse']['name'],
                        }
                        tool_use_input_json = ""

                elif 'contentBlockDelta' in event:
                    delta = event['contentBlockDelta']['delta']
                    if 'text' in delta:
                        text_chunk = delta['text']
                        current_text += text_chunk
                        yield {"type": "text", "content": text_chunk}
                    elif 'toolUse' in delta:
                        tool_use_input_json += delta['toolUse'].get('input', '')

                elif 'contentBlockStop' in event:
                    if current_text:
                        assistant_content.append({"text": current_text})
                        current_text = ""
                    if current_tool_use:
                        try:
                            current_tool_use['input'] = json.loads(tool_use_input_json) if tool_use_input_json else {}
                        except json.JSONDecodeError:
                            current_tool_use['input'] = {}
                        assistant_content.append({"toolUse": current_tool_use})
                        current_tool_use = None
                        tool_use_input_json = ""

                elif 'messageStop' in event:
                    stop_reason = event['messageStop'].get('stopReason')

            # If there's remaining text, add it
            if current_text:
                assistant_content.append({"text": current_text})

            # Add assistant message to history
            if assistant_content:
                messages.append({"role": "assistant", "content": assistant_content})

            # Check if we need to handle tool use
            if stop_reason == "tool_use":
                tool_results = []
                for block in assistant_content:
                    if "toolUse" in block:
                        tool_use = block["toolUse"]
                        yield {"type": "tool_call", "name": tool_use["name"], "input": tool_use.get("input", {})}

                        result = process_tool_call(
                            tool_name=tool_use["name"],
                            tool_input=tool_use.get("input", {}),
                            workload_token=workload_token
                        )

                        yield {"type": "tool_result", "name": tool_use["name"], "result": result}

                        tool_results.append({
                            "toolResult": {
                                "toolUseId": tool_use["toolUseId"],
                                "content": [{"text": result}]
                            }
                        })

                messages.append({"role": "user", "content": tool_results})
                # Continue the loop for next model call
            else:
                # No more tool calls, we're done
                break

        except Exception as e:
            yield {"type": "error", "content": f"Error: {str(e)}"}
            break

    yield {"type": "done"}


# Non-streaming version for compatibility
def converse_with_tools(
    prompt: str,
    workload_token: str,
    bedrock_client=None
) -> str:
    """
    Process user prompt with Bedrock Claude, handling tool calls.

    Args:
        prompt: User's natural language query
        workload_token: Workload access token for Gateway calls
        bedrock_client: Optional Bedrock client (for testing)

    Returns:
        Final response text
    """
    if bedrock_client is None:
        bedrock_client = boto3.client('bedrock-runtime', region_name=AWS_REGION)

    tools = build_tools()
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    system_prompt = get_system_prompt()

    response = bedrock_client.converse(
        modelId=MODEL_ID,
        messages=messages,
        system=[{"text": system_prompt}],
        toolConfig={"tools": [{"toolSpec": t} for t in tools]}
    )

    # Handle tool use loop
    max_iterations = 10
    iteration = 0

    while response.get("stopReason") == "tool_use" and iteration < max_iterations:
        iteration += 1
        assistant_message = response["output"]["message"]
        messages.append(assistant_message)

        tool_results = []
        for block in assistant_message["content"]:
            if "toolUse" in block:
                tool_use = block["toolUse"]
                result = process_tool_call(
                    tool_name=tool_use["name"],
                    tool_input=tool_use["input"],
                    workload_token=workload_token
                )
                tool_results.append({
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"text": result}]
                    }
                })

        messages.append({"role": "user", "content": tool_results})

        response = bedrock_client.converse(
            modelId=MODEL_ID,
            messages=messages,
            system=[{"text": system_prompt}],
            toolConfig={"tools": [{"toolSpec": t} for t in tools]}
        )

    # Extract final text response
    for block in response["output"]["message"]["content"]:
        if "text" in block:
            return block["text"]

    return "I couldn't generate a response."


# AgentCore Runtime entrypoint
try:
    from bedrock_agentcore import BedrockAgentCoreApp
    from bedrock_agentcore.runtime import RequestContext
    from bedrock_agentcore.identity import IdentityClient

    app = BedrockAgentCoreApp()

    @app.entrypoint
    async def handler(payload: Dict[str, Any], context: RequestContext):
        """AgentCore Runtime entrypoint with streaming support."""
        prompt = payload.get("prompt", "")

        if not prompt:
            yield {"response": "Please provide a prompt."}
            return

        # Get workload token for Gateway authentication
        user_token = None
        if hasattr(context, 'authorization') and context.authorization:
            user_token = context.authorization.replace('Bearer ', '')

        identity_client = IdentityClient(AWS_REGION)

        if user_token:
            workload_token = identity_client.get_workload_access_token_for_jwt(
                jwt=user_token
            )
        else:
            workload_token = identity_client.get_workload_access_token()

        # Stream response chunks
        async for chunk in converse_with_tools_streaming(prompt, workload_token):
            yield chunk

    if __name__ == "__main__":
        app.run()

except ImportError:
    # Running outside AgentCore Runtime (local testing)
    def handler(payload: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
        """Local testing entrypoint."""
        prompt = payload.get("prompt", "")

        if not prompt:
            return {"response": "Please provide a prompt."}

        # For local testing, use a placeholder token
        workload_token = os.environ.get("WORKLOAD_TOKEN", "local-test-token")
        response = converse_with_tools(prompt, workload_token)
        return {"response": response}

    if __name__ == "__main__":
        import sys
        if len(sys.argv) > 1:
            result = handler({"prompt": " ".join(sys.argv[1:])})
            print(result["response"])
