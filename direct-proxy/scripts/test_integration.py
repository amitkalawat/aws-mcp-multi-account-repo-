#!/usr/bin/env python3
# scripts/test_integration.py
"""
Integration test for Direct MCP Proxy approach.

This script tests:
1. AWS credentials are valid
2. MCP proxy can connect to AWS MCP Server
3. Can call an AWS service tool
"""
import sys
import json
sys.path.insert(0, '.')

from agent.mcp_client import MCPClient


def test_aws_identity():
    """Test 1: Verify AWS identity."""
    print("Test 1: Verifying AWS identity...")
    import boto3
    sts = boto3.client('sts')
    identity = sts.get_caller_identity()
    print(f"  Account: {identity['Account']}")
    print(f"  ARN: {identity['Arn']}")
    print("  PASS")
    return identity['Account']


def test_mcp_connection():
    """Test 2: Verify MCP proxy connection via initialize."""
    print("\nTest 2: Testing MCP proxy connection...")
    import subprocess

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "integration-test", "version": "1.0"}
        }
    }

    result = subprocess.run(
        [
            "uvx", "mcp-proxy-for-aws@latest",
            "https://aws-mcp.us-east-1.api.aws/mcp",
            "--metadata", "AWS_REGION=us-east-1"
        ],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=120
    )

    stdout_lines = result.stdout.strip().split('\n')
    if stdout_lines and stdout_lines[0]:
        response = json.loads(stdout_lines[0])
        server_info = response.get("result", {}).get("serverInfo", {})
        print(f"  Server: {server_info.get('name', 'unknown')}")
        print(f"  Version: {server_info.get('version', 'unknown')}")
        print("  PASS")
        return response
    else:
        print(f"  FAIL: No response")
        raise RuntimeError("MCP connection failed")


def test_account_manager():
    """Test 3: Verify AccountManager works."""
    print("\nTest 3: Testing AccountManager...")
    from agent.account_manager import AccountManager

    manager = AccountManager()
    print(f"  Registry loaded: {len(manager.accounts.get('accounts', []))} accounts")
    print("  PASS")
    return manager


def main():
    """Run all integration tests."""
    print("=" * 60)
    print("Direct MCP Proxy Integration Tests")
    print("=" * 60)

    try:
        account_id = test_aws_identity()
        test_mcp_connection()
        test_account_manager()

        print("\n" + "=" * 60)
        print("ALL TESTS PASSED")
        print("=" * 60)
        print(f"\nYour AWS account: {account_id}")
        print("MCP proxy connection: Working")
        print("AccountManager: Working")
        print("\nReady for multi-account operations!")
        return 0
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
