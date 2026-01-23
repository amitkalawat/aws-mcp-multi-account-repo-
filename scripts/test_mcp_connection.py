#!/usr/bin/env python3
# scripts/test_mcp_connection.py
"""Test basic MCP proxy connection to AWS MCP Server."""
import subprocess
import json
import sys


def test_mcp_initialize():
    """Test that we can initialize MCP connection to AWS MCP Server."""
    # MCP protocol requires initialize first
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"}
        }
    }

    print("Testing MCP proxy connection to AWS MCP Server...")
    print(f"Endpoint: https://aws-mcp.us-east-1.api.aws/mcp")

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

    # Parse first line of output (may have multiple JSON responses)
    stdout_lines = result.stdout.strip().split('\n')
    if not stdout_lines or not stdout_lines[0]:
        print(f"FAIL: No response from MCP proxy")
        print(f"stderr: {result.stderr[:500]}")
        return False

    try:
        response = json.loads(stdout_lines[0])

        if "error" in response:
            print(f"FAIL: MCP error: {response['error']}")
            return False

        server_info = response.get("result", {}).get("serverInfo", {})
        protocol_version = response.get("result", {}).get("protocolVersion", "unknown")
        capabilities = response.get("result", {}).get("capabilities", {})

        print(f"\nPASS: MCP connection established")
        print(f"  Server: {server_info.get('name', 'unknown')}")
        print(f"  Version: {server_info.get('version', 'unknown')}")
        print(f"  Protocol: {protocol_version}")
        print(f"  Capabilities: tools={bool(capabilities.get('tools'))}, "
              f"prompts={bool(capabilities.get('prompts'))}, "
              f"resources={bool(capabilities.get('resources'))}")

        return True

    except json.JSONDecodeError as e:
        print(f"FAIL: Invalid JSON response: {e}")
        print(f"stdout: {result.stdout[:500]}")
        return False


if __name__ == "__main__":
    success = test_mcp_initialize()
    sys.exit(0 if success else 1)
