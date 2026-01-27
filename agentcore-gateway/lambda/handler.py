"""
Lambda Bridge for AWS MCP Server access.

This Lambda is a simple bridge that:
1. Receives tool request from agent (via Gateway)
2. For account-specific tools: Assumes IAM role in target account
3. For global tools (docs, SOPs): Uses Lambda's own credentials
4. Calls AWS MCP Server with SigV4 signing
5. Returns result

Account management is handled by the agent (via DynamoDB), not this Lambda.
"""
import json
import boto3
from datetime import datetime, timezone, timedelta
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import urllib.request
from typing import Dict, Any, Set

# AWS MCP Server is only available in us-east-1
AWS_MCP_ENDPOINT = 'https://aws-mcp.us-east-1.api.aws/mcp'
AWS_MCP_REGION = 'us-east-1'
TARGET_ROLE_NAME = 'CentralOpsTargetRole'

# Global tools don't need account-specific credentials
# These use Lambda's own credentials to access AWS MCP Server
GLOBAL_TOOLS: Set[str] = {
    'aws___search_documentation',
    'aws___read_documentation',
    'aws___retrieve_agent_sop',
    'aws___recommend',
    'aws___suggest_aws_commands',
}

# In-memory credential cache (persists across warm invocations)
credential_cache: Dict[str, Dict] = {}

# Session cache per account (for MCP session persistence)
session_cache: Dict[str, str] = {}

# Session cache for global tools (no account context)
global_session_id: str = None


def get_credentials(account_id: str) -> Dict[str, Any]:
    """Get or refresh credentials for target account."""
    now = datetime.now(timezone.utc)

    if account_id in credential_cache:
        creds = credential_cache[account_id]
        if now + timedelta(minutes=5) < creds['expiration']:
            return creds

    sts = boto3.client('sts')
    response = sts.assume_role(
        RoleArn=f"arn:aws:iam::{account_id}:role/{TARGET_ROLE_NAME}",
        RoleSessionName=f"Bridge-{account_id}",
        DurationSeconds=3600
    )

    creds = {
        'access_key_id': response['Credentials']['AccessKeyId'],
        'secret_access_key': response['Credentials']['SecretAccessKey'],
        'session_token': response['Credentials']['SessionToken'],
        'expiration': response['Credentials']['Expiration']
    }
    credential_cache[account_id] = creds
    return creds


def make_mcp_request(
    method: str,
    params: Dict[str, Any],
    boto_session: 'boto3.Session',
    session_id: str = None
) -> tuple:
    """Make a signed MCP request. Returns (response_body, response_headers)."""
    mcp_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }

    headers = {'Content-Type': 'application/json'}
    if session_id:
        headers['Mcp-Session-Id'] = session_id

    request = AWSRequest(
        method='POST',
        url=AWS_MCP_ENDPOINT,
        data=json.dumps(mcp_request),
        headers=headers
    )
    SigV4Auth(boto_session.get_credentials(), 'aws-mcp', AWS_MCP_REGION).add_auth(request)

    req = urllib.request.Request(
        AWS_MCP_ENDPOINT,
        data=request.body.encode() if isinstance(request.body, str) else request.body,
        headers=dict(request.headers),
        method='POST'
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        response_headers = dict(resp.headers)
        return json.loads(resp.read()), response_headers


def get_or_create_mcp_session(account_id: str, boto_session: 'boto3.Session') -> str:
    """Get existing MCP session or create new one for account-specific tools."""
    if account_id in session_cache:
        return session_cache[account_id]

    # Initialize new MCP session
    result, headers = make_mcp_request(
        method="initialize",
        params={
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "aws-mcp-bridge", "version": "1.0.0"}
        },
        boto_session=boto_session,
        session_id=None
    )

    # Server returns session ID in response header
    session_id = headers.get('Mcp-Session-Id') or headers.get('mcp-session-id')
    if session_id and 'error' not in result:
        session_cache[account_id] = session_id
        return session_id

    raise Exception(f"Failed to initialize MCP session: {result}")


def get_or_create_global_mcp_session() -> tuple:
    """Get existing MCP session or create new one for global tools (using Lambda's credentials)."""
    global global_session_id

    # Create boto session with Lambda's own credentials
    boto_session = boto3.Session(region_name=AWS_MCP_REGION)

    if global_session_id:
        return global_session_id, boto_session

    # Initialize new MCP session
    result, headers = make_mcp_request(
        method="initialize",
        params={
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "aws-mcp-bridge-global", "version": "1.0.0"}
        },
        boto_session=boto_session,
        session_id=None
    )

    # Server returns session ID in response header
    session_id = headers.get('Mcp-Session-Id') or headers.get('mcp-session-id')
    if session_id and 'error' not in result:
        global_session_id = session_id
        return session_id, boto_session

    raise Exception(f"Failed to initialize global MCP session: {result}")


def call_aws_mcp(
    tool_name: str,
    arguments: Dict[str, Any],
    account_id: str,
    region: str = "us-east-1"
) -> Dict[str, Any]:
    """Call AWS MCP Server with SigV4 authentication using account credentials."""
    creds = get_credentials(account_id)

    boto_session = boto3.Session(
        aws_access_key_id=creds['access_key_id'],
        aws_secret_access_key=creds['secret_access_key'],
        aws_session_token=creds['session_token'],
        region_name=region
    )

    # Get or create MCP session
    session_id = get_or_create_mcp_session(account_id, boto_session)

    # Make tool call
    result, _ = make_mcp_request(
        method="tools/call",
        params={"name": tool_name, "arguments": arguments},
        boto_session=boto_session,
        session_id=session_id
    )
    return result


def call_aws_mcp_global(
    tool_name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Call AWS MCP Server for global tools using Lambda's own credentials.

    Global tools like documentation search and SOP retrieval don't need
    account-specific credentials.
    """
    # Get or create global MCP session
    session_id, boto_session = get_or_create_global_mcp_session()

    # Make tool call
    result, _ = make_mcp_request(
        method="tools/call",
        params={"name": tool_name, "arguments": arguments},
        boto_session=boto_session,
        session_id=session_id
    )
    return result


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda handler - simple bridge for AWS MCP queries.

    Gateway format:
    - event = tool arguments directly (e.g., {"account_id": "123", "tool_name": "aws___list_regions"})
    - context.client_context.custom contains bedrockAgentCoreToolName

    Required arguments:
    - account_id: Target AWS account ID
    - tool_name: MCP tool to call (e.g., "aws___list_regions")
    - arguments: Tool arguments (optional, defaults to {})
    - region: AWS region for the query (optional, defaults to "us-east-1")
    """
    # Check if this is from AgentCore Gateway
    tool_name = None
    if hasattr(context, 'client_context') and context.client_context:
        custom = getattr(context.client_context, 'custom', None)
        if custom and 'bedrockAgentCoreToolName' in custom:
            full_tool_name = custom['bedrockAgentCoreToolName']
            if '___' in full_tool_name:
                tool_name = full_tool_name.split('___', 1)[1]
            else:
                tool_name = full_tool_name

    # Gateway invocation
    if tool_name == 'query':
        account_id = event.get('account_id')
        mcp_tool = event.get('tool_name')
        tool_args = event.get('arguments', {})
        region = event.get('region', 'us-east-1')

        if not mcp_tool:
            return {'error': 'Missing tool_name'}

        try:
            # Global tools don't need account credentials
            if mcp_tool in GLOBAL_TOOLS:
                result = call_aws_mcp_global(mcp_tool, tool_args)
                return result

            # Account-specific tools require account_id
            if not account_id:
                return {'error': f'Missing account_id (required for {mcp_tool})'}

            result = call_aws_mcp(mcp_tool, tool_args, account_id, region)
            return result
        except Exception as e:
            return {'error': str(e)}

    # Direct invocation (for testing)
    if tool_name is None:
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return {'statusCode': 400, 'body': json.dumps({'error': 'Invalid JSON body'})}

        action = body.get('action')
        if action == 'query':
            account_id = body.get('account_id')
            mcp_tool = body.get('tool_name')
            tool_args = body.get('arguments', {})
            region = body.get('region', 'us-east-1')

            if not mcp_tool:
                return {'statusCode': 400, 'body': json.dumps({'error': 'Missing tool_name'})}

            try:
                # Global tools don't need account credentials
                if mcp_tool in GLOBAL_TOOLS:
                    result = call_aws_mcp_global(mcp_tool, tool_args)
                    return {'statusCode': 200, 'body': json.dumps(result, default=str)}

                # Account-specific tools require account_id
                if not account_id:
                    return {'statusCode': 400, 'body': json.dumps({'error': f'Missing account_id (required for {mcp_tool})'})}

                result = call_aws_mcp(mcp_tool, tool_args, account_id, region)
                return {'statusCode': 200, 'body': json.dumps(result, default=str)}
            except Exception as e:
                return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}

        return {'statusCode': 400, 'body': json.dumps({'error': f'Unknown action: {action}'})}

    return {'error': f'Unknown tool: {tool_name}'}
