"""
CentralOpsAgent - Multi-account AWS operations agent for AgentCore Runtime.

Uses Strands Agent with MCP client to connect to AgentCore Gateway.
"""
# Configure logging FIRST
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logger.info("=== CentralOpsAgent module loading ===")

import os
import json
import boto3
from typing import Dict, Any, List

logger.info("Standard imports complete")

from strands import Agent, tool
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamablehttp_client

logger.info("Strands and MCP imports complete")

from bedrock_agentcore.runtime import BedrockAgentCoreApp

logger.info("BedrockAgentCoreApp imported")

# Configuration
GATEWAY_URL = os.environ.get('GATEWAY_URL', '')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
MODEL_ID = os.environ.get('MODEL_ID', 'us.anthropic.claude-sonnet-4-20250514-v1:0')
ACCOUNTS_TABLE_NAME = os.environ.get('ACCOUNTS_TABLE_NAME', '')

logger.info(f"Config: GATEWAY_URL={GATEWAY_URL}")
logger.info(f"Config: AWS_REGION={AWS_REGION}, MODEL_ID={MODEL_ID}")
logger.info(f"Config: ACCOUNTS_TABLE_NAME={ACCOUNTS_TABLE_NAME}")


def get_accounts_from_dynamodb() -> List[Dict[str, Any]]:
    """Fetch enabled accounts from DynamoDB."""
    if not ACCOUNTS_TABLE_NAME:
        logger.warning("ACCOUNTS_TABLE_NAME not set")
        return []
    try:
        logger.info(f"Scanning DynamoDB table: {ACCOUNTS_TABLE_NAME}")
        dynamodb = boto3.client('dynamodb', region_name=AWS_REGION)
        response = dynamodb.scan(
            TableName=ACCOUNTS_TABLE_NAME,
            FilterExpression='enabled = :enabled',
            ExpressionAttributeValues={':enabled': {'BOOL': True}}
        )
        accounts = [{
            'account_id': item.get('account_id', {}).get('S', ''),
            'name': item.get('name', {}).get('S', ''),
            'environment': item.get('environment', {}).get('S', ''),
        } for item in response.get('Items', [])]
        logger.info(f"Found {len(accounts)} accounts")
        return accounts
    except Exception as e:
        logger.error(f"DynamoDB error: {e}", exc_info=True)
        return []


def create_mcp_transport(access_token: str):
    """Create MCP transport with authentication headers."""
    headers = {"Authorization": f"Bearer {access_token}"}
    logger.info(f"Creating MCP transport to {GATEWAY_URL}")
    return streamablehttp_client(GATEWAY_URL, headers=headers)


@tool
def list_accounts() -> str:
    """List all available AWS accounts that can be queried."""
    accounts = get_accounts_from_dynamodb()
    if not accounts:
        return json.dumps({"message": "No accounts configured.", "accounts": []}, indent=2)
    return json.dumps({"accounts": accounts}, indent=2)


def invoke_agent_with_gateway(prompt: str, access_token: str) -> str:
    """Invoke agent with Gateway tools via MCP client."""
    if not GATEWAY_URL:
        return "Gateway URL not configured"

    if not access_token:
        return "Access token not provided"

    # Get accounts info for system prompt
    accounts = get_accounts_from_dynamodb()
    accounts_info = ""
    if accounts:
        accounts_list = "\n".join([f"- {a['name']} ({a['account_id']}) - {a['environment']}" for a in accounts])
        accounts_info = f"\n\nAvailable AWS accounts:\n{accounts_list}"

    system_prompt = f"""You are a helpful AWS operations assistant that can query AWS resources across multiple accounts and search AWS documentation.

You have access to tools from the Gateway via bridge-lambda___query.

## Account-Specific Tools (require account_id)

### aws___call_aws
Execute AWS CLI commands in a specific account.
- account_id: Required - The 12-digit AWS account ID
- tool_name: "aws___call_aws"
- arguments: {{"cli_command": "aws <service> <command>"}}
- region: AWS region (default: us-east-1)

Example - List S3 buckets:
  tool_name: "aws___call_aws", account_id: "878687028155", arguments: {{"cli_command": "aws s3 ls"}}

### aws___list_regions
List available AWS regions for an account.
- account_id: Required
- tool_name: "aws___list_regions"

## Global Tools (no account_id needed)

### aws___search_documentation
Search AWS documentation for topics, services, or concepts.
- tool_name: "aws___search_documentation"
- arguments: {{"query": "search terms"}}

Example: Search for Lambda best practices:
  tool_name: "aws___search_documentation", arguments: {{"query": "Lambda best practices"}}

### aws___read_documentation
Read a specific AWS documentation page.
- tool_name: "aws___read_documentation"
- arguments: {{"url": "https://docs.aws.amazon.com/..."}}

### aws___retrieve_agent_sop
Get step-by-step Standard Operating Procedures for AWS tasks.
- tool_name: "aws___retrieve_agent_sop"
- arguments: {{"query": "task description"}} or {{"sop_id": "specific-sop-id"}}

Example: Get SOP for VPC setup:
  tool_name: "aws___retrieve_agent_sop", arguments: {{"query": "set up VPC with public and private subnets"}}

### aws___suggest_aws_commands
Get help with AWS CLI command syntax and usage.
- tool_name: "aws___suggest_aws_commands"
- arguments: {{"query": "what you want to do"}}

Example: Get help with S3 sync:
  tool_name: "aws___suggest_aws_commands", arguments: {{"query": "sync local folder to S3 bucket"}}

### aws___recommend
Get AWS documentation recommendations based on context.
- tool_name: "aws___recommend"
- arguments: {{"query": "topic or question"}}

## Local Tools
- **list_accounts**: List available AWS accounts from the registry
{accounts_info}"""

    try:
        # Create MCP client with authentication
        mcp_client = MCPClient(lambda: create_mcp_transport(access_token))

        # Create Bedrock model
        bedrock_model = BedrockModel(
            model_id=MODEL_ID,
            region_name=AWS_REGION,
        )

        # Use MCP client context to get tools and invoke agent
        with mcp_client:
            # Get tools from Gateway
            gateway_tools = mcp_client.list_tools_sync()
            logger.info(f"Got {len(gateway_tools)} tools from Gateway")

            # Combine Gateway tools with local tools
            all_tools = list(gateway_tools) + [list_accounts]

            # Create agent with all tools
            agent = Agent(
                model=bedrock_model,
                system_prompt=system_prompt,
                tools=all_tools
            )

            # Invoke agent
            logger.info(f"Invoking agent with prompt: {prompt[:100]}...")
            response = agent(prompt)

            # Extract text from response
            if hasattr(response, 'message') and hasattr(response.message, 'content'):
                content = response.message.content
                if isinstance(content, list) and len(content) > 0:
                    text = content[0].get('text', str(response))
                else:
                    text = str(content)
            else:
                text = str(response)

            return text

    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        return f"Error: {str(e)}"


# AgentCore Runtime app
logger.info("Creating BedrockAgentCoreApp")
app = BedrockAgentCoreApp()
logger.info("BedrockAgentCoreApp created")


@app.entrypoint
def agent_invocation(payload):
    """Handler for agent invocation."""
    logger.info(f"=== Received invocation ===")
    logger.info(f"Payload keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload)}")

    prompt = payload.get("prompt", "")
    if not prompt:
        logger.warning("No prompt provided")
        return {"response": "Please provide a prompt."}

    # Get access token from payload
    # The token can be passed in different ways:
    # 1. Directly in payload as 'access_token' or 'token'
    # 2. In headers
    # 3. In context
    access_token = None
    if isinstance(payload, dict):
        access_token = (
            payload.get('access_token') or
            payload.get('token') or
            payload.get('accessToken') or
            payload.get('headers', {}).get('Authorization', '').replace('Bearer ', '') or
            payload.get('context', {}).get('access_token')
        )

    logger.info(f"Access token found: {'yes' if access_token else 'no'}")

    if not access_token:
        # If no token provided, return error with instructions
        return {
            "response": "Access token required. Please include 'access_token' in your request payload to authenticate with the Gateway.",
            "error": "missing_token"
        }

    try:
        response_text = invoke_agent_with_gateway(prompt, access_token)
        return {"response": response_text}
    except Exception as e:
        logger.error(f"Invocation error: {e}", exc_info=True)
        return {"error": str(e)}


logger.info("=== Module loading complete ===")

if __name__ == "__main__":
    logger.info("Starting app.run()")
    app.run()
