"""Tests for MCPClient."""
import pytest
from unittest.mock import patch, MagicMock
from agent.mcp_client import MCPClient


@patch('agent.mcp_client.subprocess.run')
def test_call_tool_success(mock_run):
    """Test successful tool call."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout='{"jsonrpc":"2.0","id":1,"result":{"content":[{"text":"test result"}]}}',
        stderr=''
    )

    client = MCPClient()
    result = client.call_tool("test_tool", {"arg1": "value1"})

    assert result["result"]["content"][0]["text"] == "test result"
    mock_run.assert_called_once()


@patch('agent.mcp_client.subprocess.run')
def test_call_tool_error(mock_run):
    """Test tool call with error."""
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout='',
        stderr='Connection error'
    )

    client = MCPClient()

    with pytest.raises(RuntimeError, match="MCP proxy error"):
        client.call_tool("test_tool", {})


@patch('agent.mcp_client.subprocess.run')
def test_list_tools(mock_run):
    """Test listing tools."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout='{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"tool1"},{"name":"tool2"}]}}',
        stderr=''
    )

    client = MCPClient()
    tools = client.list_tools()

    assert len(tools) == 2
    assert tools[0]["name"] == "tool1"
