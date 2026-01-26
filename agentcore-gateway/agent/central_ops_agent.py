"""
CentralOpsAgent - Multi-account AWS operations agent for AgentCore Runtime.

This agent:
1. Receives natural language queries from users
2. Uses Bedrock Claude to understand intent and call tools
3. Calls AgentCore Gateway to query AWS resources across accounts
"""
import os
import json
import boto3
import urllib.request
from typing import Dict, Any, List

# Configuration
GATEWAY_URL = os.environ.get('GATEWAY_URL', '')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
MODEL_ID = os.environ.get('MODEL_ID', 'anthropic.claude-3-5-sonnet-20241022-v2:0')


def build_tools() -> List[Dict[str, Any]]:
    """Build tool definitions for Bedrock Converse API."""
    return [{
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
                        "description": "The MCP tool name (e.g., 'ec2_describe_instances', 's3_list_buckets')"
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments to pass to the MCP tool",
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
    }]


def call_gateway(
    gateway_url: str,
    action: str,
    workload_token: str,
    tool_name: str = None,
    account_id: str = None,
    arguments: Dict = None,
    region: str = "us-east-1"
) -> Dict[str, Any]:
    """
    Call AgentCore Gateway with workload identity token.

    Args:
        gateway_url: Gateway endpoint URL
        action: Action to perform (list_accounts, query, query_all)
        workload_token: Workload access token from AgentCore Identity
        tool_name: MCP tool name (for query/query_all)
        account_id: Target account ID (for query)
        arguments: Tool arguments
        region: AWS region

    Returns:
        Gateway response
    """
    request_body = {"action": action}

    if action == "query":
        request_body.update({
            "tool_name": tool_name,
            "account_id": account_id,
            "arguments": arguments or {},
            "region": region
        })
    elif action == "query_all":
        request_body.update({
            "tool_name": tool_name,
            "arguments": arguments or {},
            "region": region
        })

    req = urllib.request.Request(
        gateway_url,
        data=json.dumps(request_body).encode(),
        headers={
            "Authorization": f"Bearer {workload_token}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


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
    if tool_name == "query_aws_resources":
        result = call_gateway(
            gateway_url=GATEWAY_URL,
            action="query",
            workload_token=workload_token,
            tool_name=tool_input["tool_name"],
            account_id=tool_input["account_id"],
            arguments=tool_input.get("arguments", {}),
            region=tool_input.get("region", "us-east-1")
        )
        return json.dumps(result, indent=2, default=str)

    return json.dumps({"error": f"Unknown tool: {tool_name}"})


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

    system_prompt = """You are a helpful AWS operations assistant. You can query AWS resources across multiple accounts.

When users ask about AWS resources, use the query_aws_resources tool to fetch the information.
Available MCP tools include:
- ec2_describe_instances: List EC2 instances
- s3_list_buckets: List S3 buckets
- rds_describe_db_instances: List RDS databases
- lambda_list_functions: List Lambda functions

Always specify the account_id when querying. If the user doesn't specify an account, ask them which account to query."""

    response = bedrock_client.converse(
        modelId=MODEL_ID,
        messages=messages,
        system=[{"text": system_prompt}],
        toolConfig={"tools": [{"toolSpec": t} for t in tools]}
    )

    # Handle tool use loop
    while response.get("stopReason") == "tool_use":
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
    from bedrock_agentcore.identity import get_workload_access_token

    app = BedrockAgentCoreApp()

    @app.entrypoint
    def handler(payload: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """AgentCore Runtime entrypoint."""
        prompt = payload.get("prompt", "")

        if not prompt:
            return {"response": "Please provide a prompt."}

        # Get workload token for Gateway authentication
        workload_token = get_workload_access_token()

        response = converse_with_tools(prompt, workload_token)
        return {"response": response}

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
