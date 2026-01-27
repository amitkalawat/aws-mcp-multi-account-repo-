"""
Lambda Bridge for AWS MCP Server access.

This Lambda function:
1. Receives requests from AgentCore Gateway (SigV4 authenticated)
2. Assumes IAM roles in target accounts
3. Calls AWS MCP Server with SigV4 signing
"""
import os
import json
import boto3
from datetime import datetime, timezone, timedelta
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import urllib.request
from typing import Dict, Any

# AWS MCP Server is only available in us-east-1
AWS_MCP_ENDPOINT = os.environ.get('AWS_MCP_ENDPOINT', 'https://aws-mcp.us-east-1.api.aws/mcp')
AWS_MCP_REGION = 'us-east-1'  # MCP service region (not the target resource region)
TARGET_ROLE_NAME = os.environ.get('TARGET_ROLE_NAME', 'CentralOpsTargetRole')

# In-memory credential cache (persists across warm invocations)
credential_cache: Dict[str, Dict] = {}


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


# Session cache per account (for MCP session persistence)
session_cache: Dict[str, str] = {}


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
    """Get existing MCP session or create new one."""
    if account_id in session_cache:
        return session_cache[account_id]

    # Initialize new MCP session (no session ID on first request)
    result, headers = make_mcp_request(
        method="initialize",
        params={
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "aws-mcp-bridge", "version": "1.0.0"}
        },
        boto_session=boto_session,
        session_id=None  # Server will return session ID
    )

    # Server returns session ID in response header
    session_id = headers.get('Mcp-Session-Id') or headers.get('mcp-session-id')
    if session_id and 'error' not in result:
        session_cache[account_id] = session_id
        return session_id

    raise Exception(f"Failed to initialize MCP session: {result}")


def call_aws_mcp(
    tool_name: str,
    arguments: Dict[str, Any],
    account_id: str,
    region: str = "us-east-1"
) -> Dict[str, Any]:
    """Call AWS MCP Server with SigV4 authentication."""
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


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda handler for Gateway and direct invocations.

    Gateway format (from AgentCore Gateway):
    - event = tool arguments directly (e.g., {"account_id": "123", "tool_name": "aws___list_regions"})
    - context.client_context.custom contains:
      - bedrockAgentCoreToolName: "bridge-lambda___query"
      - bedrockAgentCoreGatewayId, bedrockAgentCoreTargetId, etc.

    Direct invocation format:
    - event = {"body": "{\"action\": \"list_accounts\"}"}
    """
    accounts = json.loads(os.environ.get('TARGET_ACCOUNTS', '[]'))

    # Check if this is from AgentCore Gateway (has client_context with tool info)
    tool_name = None
    if hasattr(context, 'client_context') and context.client_context:
        custom = getattr(context.client_context, 'custom', None)
        if custom and 'bedrockAgentCoreToolName' in custom:
            full_tool_name = custom['bedrockAgentCoreToolName']
            # Strip target prefix (e.g., "bridge-lambda___query" -> "query")
            if '___' in full_tool_name:
                tool_name = full_tool_name.split('___', 1)[1]
            else:
                tool_name = full_tool_name

    # Gateway invocation: event is the arguments, tool_name from context
    if tool_name:
        try:
            if tool_name == 'list_accounts':
                return accounts

            elif tool_name == 'query':
                account_id = event.get('account_id')
                mcp_tool = event.get('tool_name')
                tool_args = event.get('arguments', {})
                region = event.get('region', 'us-east-1')

                if not mcp_tool or not account_id:
                    return {'error': 'Missing tool_name or account_id'}

                result = call_aws_mcp(mcp_tool, tool_args, account_id, region)
                return result

            elif tool_name == 'query_all':
                mcp_tool = event.get('tool_name')
                tool_args = event.get('arguments', {})
                region = event.get('region', 'us-east-1')

                if not mcp_tool:
                    return {'error': 'Missing tool_name'}

                results = {}
                for acc in accounts:
                    try:
                        result = call_aws_mcp(mcp_tool, tool_args, acc['id'], region)
                        results[acc['id']] = {'status': 'success', 'data': result}
                    except Exception as e:
                        results[acc['id']] = {'status': 'error', 'error': str(e)}

                return results

            else:
                return {'error': f'Unknown tool: {tool_name}'}

        except Exception as e:
            return {'error': str(e)}

    # Direct invocation format: event has 'body' field
    try:
        body = json.loads(event.get('body', '{}'))
    except json.JSONDecodeError:
        return {'statusCode': 400, 'body': json.dumps({'error': 'Invalid JSON body'})}

    action = body.get('action')

    if action == 'list_accounts':
        return {'statusCode': 200, 'body': json.dumps(accounts)}

    elif action == 'query':
        tool_name = body.get('tool_name')
        account_id = body.get('account_id')
        arguments = body.get('arguments', {})
        region = body.get('region', 'us-east-1')

        if not tool_name or not account_id:
            return {'statusCode': 400, 'body': json.dumps({'error': 'Missing tool_name or account_id'})}

        result = call_aws_mcp(tool_name, arguments, account_id, region)
        return {'statusCode': 200, 'body': json.dumps(result, default=str)}

    elif action == 'query_all':
        tool_name = body.get('tool_name')
        arguments = body.get('arguments', {})
        region = body.get('region', 'us-east-1')

        if not tool_name:
            return {'statusCode': 400, 'body': json.dumps({'error': 'Missing tool_name'})}

        results = {}
        for acc in accounts:
            try:
                result = call_aws_mcp(tool_name, arguments, acc['id'], region)
                results[acc['id']] = {'status': 'success', 'data': result}
            except Exception as e:
                results[acc['id']] = {'status': 'error', 'error': str(e)}

        return {'statusCode': 200, 'body': json.dumps(results, default=str)}

    return {'statusCode': 400, 'body': json.dumps({'error': f'Unknown action: {action}'})}
