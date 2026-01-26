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

AWS_MCP_ENDPOINT = "https://aws-mcp.us-east-1.api.aws/mcp"
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


def call_aws_mcp(
    tool_name: str,
    arguments: Dict[str, Any],
    account_id: str,
    region: str = "us-east-1"
) -> Dict[str, Any]:
    """Call AWS MCP Server with SigV4 authentication."""
    creds = get_credentials(account_id)

    mcp_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments}
    }

    session = boto3.Session(
        aws_access_key_id=creds['access_key_id'],
        aws_secret_access_key=creds['secret_access_key'],
        aws_session_token=creds['session_token'],
        region_name=region
    )

    request = AWSRequest(
        method='POST',
        url=AWS_MCP_ENDPOINT,
        data=json.dumps(mcp_request),
        headers={'Content-Type': 'application/json'}
    )
    SigV4Auth(session.get_credentials(), 'aws-mcp', region).add_auth(request)

    req = urllib.request.Request(
        AWS_MCP_ENDPOINT,
        data=request.body.encode() if isinstance(request.body, str) else request.body,
        headers=dict(request.headers),
        method='POST'
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda handler for Gateway invocations."""
    try:
        body = json.loads(event.get('body', '{}'))
    except json.JSONDecodeError:
        return {'statusCode': 400, 'body': json.dumps({'error': 'Invalid JSON body'})}

    action = body.get('action')
    accounts = json.loads(os.environ.get('TARGET_ACCOUNTS', '[]'))

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
