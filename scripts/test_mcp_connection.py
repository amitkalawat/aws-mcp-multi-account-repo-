#!/usr/bin/env python3
# scripts/test_mcp_connection.py
"""Test basic MCP proxy connection to AWS MCP Server."""
import subprocess
import json
import sys


def test_mcp_tools_list():
    """Test that we can list tools from AWS MCP Server."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {}
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
        timeout=60
    )

    if result.returncode != 0:
        print(f"FAIL: MCP proxy error: {result.stderr}")
        return False

    try:
        response = json.loads(result.stdout)
        tools = response.get("result", {}).get("tools", [])
        print(f"PASS: Retrieved {len(tools)} tools from AWS MCP Server")

        # Print first 5 tool names as sample
        print("\nSample tools:")
        for tool in tools[:5]:
            print(f"  - {tool.get('name')}")

        return True
    except json.JSONDecodeError as e:
        print(f"FAIL: Invalid JSON response: {e}")
        print(f"stdout: {result.stdout[:500]}")
        return False


if __name__ == "__main__":
    success = test_mcp_tools_list()
    sys.exit(0 if success else 1)
