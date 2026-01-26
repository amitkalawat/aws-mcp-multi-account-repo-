"""MCP client for calling AWS MCP Server via mcp-proxy-for-aws."""
import subprocess
import json
from typing import Dict, Any, List, Optional


class MCPClient:
    """Client for AWS MCP Server using mcp-proxy-for-aws."""

    DEFAULT_SERVER_URL = "https://aws-mcp.us-east-1.api.aws/mcp"
    DEFAULT_REGION = "us-east-1"
    DEFAULT_TIMEOUT = 120

    def __init__(
        self,
        server_url: str = None,
        region: str = None,
        timeout: int = None
    ):
        """
        Initialize MCP client.

        Args:
            server_url: AWS MCP Server URL
            region: AWS region for metadata
            timeout: Request timeout in seconds
        """
        self.server_url = server_url or self.DEFAULT_SERVER_URL
        self.region = region or self.DEFAULT_REGION
        self.timeout = timeout or self.DEFAULT_TIMEOUT

    def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Call an MCP tool.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool execution result

        Raises:
            RuntimeError: If MCP proxy fails
        """
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        return self._invoke_proxy(request)

    def list_tools(self) -> List[Dict[str, Any]]:
        """
        List available MCP tools.

        Returns:
            List of tool definitions
        """
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }

        result = self._invoke_proxy(request)
        return result.get("result", {}).get("tools", [])

    def _invoke_proxy(self, request: Dict) -> Dict:
        """
        Invoke mcp-proxy-for-aws with the given request.

        Args:
            request: JSON-RPC request

        Returns:
            JSON-RPC response

        Raises:
            RuntimeError: If proxy returns non-zero exit code
        """
        proc = subprocess.run(
            [
                "uvx", "mcp-proxy-for-aws@latest",
                self.server_url,
                "--metadata", f"AWS_REGION={self.region}"
            ],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=self.timeout
        )

        if proc.returncode != 0:
            raise RuntimeError(f"MCP proxy error: {proc.stderr}")

        return json.loads(proc.stdout)
