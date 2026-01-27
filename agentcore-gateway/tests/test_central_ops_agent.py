"""Tests for CentralOpsAgent."""
import json
import pytest
from unittest.mock import patch, MagicMock


def test_build_tools_returns_both_tools():
    """Test that build_tools returns list_accounts and query_aws_resources tools."""
    from central_ops_agent import build_tools

    tools = build_tools()

    assert len(tools) == 2
    tool_names = [t["name"] for t in tools]
    assert "list_accounts" in tool_names
    assert "query_aws_resources" in tool_names

    # Verify query_aws_resources has the right properties
    query_tool = next(t for t in tools if t["name"] == "query_aws_resources")
    assert "account_id" in query_tool["inputSchema"]["json"]["properties"]
    assert "tool_name" in query_tool["inputSchema"]["json"]["properties"]


def test_call_gateway_mcp_constructs_request():
    """Test that call_gateway_mcp builds correct MCP JSON-RPC request structure."""
    with patch('central_ops_agent.urllib.request.urlopen') as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"result": "success"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        from central_ops_agent import call_gateway_mcp

        result = call_gateway_mcp(
            gateway_url="https://gateway.example.com",
            workload_token="test-token",
            mcp_tool_name="aws___call_aws",
            account_id="222222222222",
            arguments={"cli_command": "aws s3 ls"},
            region="us-east-1"
        )

        assert result == {"result": "success"}

        # Verify the request was constructed correctly
        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        assert request.get_header('Authorization') == 'Bearer test-token'
        assert request.get_header('Content-type') == 'application/json'

        # Verify MCP JSON-RPC format
        request_body = json.loads(request.data.decode())
        assert request_body["jsonrpc"] == "2.0"
        assert request_body["method"] == "tools/call"
        assert request_body["params"]["name"] == "bridge-lambda___query"
        assert request_body["params"]["arguments"]["account_id"] == "222222222222"


def test_get_accounts_with_table():
    """Test get_accounts returns accounts from DynamoDB."""
    with patch('central_ops_agent.boto3.client') as mock_boto:
        mock_dynamodb = MagicMock()
        mock_boto.return_value = mock_dynamodb
        mock_dynamodb.scan.return_value = {
            'Items': [
                {
                    'account_id': {'S': '123456789012'},
                    'name': {'S': 'Test Account'},
                    'environment': {'S': 'dev'},
                    'enabled': {'BOOL': True}
                }
            ]
        }

        with patch.dict('os.environ', {'ACCOUNTS_TABLE_NAME': 'test-accounts'}):
            # Need to reimport to pick up env var
            import sys
            if 'central_ops_agent' in sys.modules:
                del sys.modules['central_ops_agent']
            from central_ops_agent import get_accounts

            accounts = get_accounts()

            assert len(accounts) == 1
            assert accounts[0]['account_id'] == '123456789012'
            assert accounts[0]['name'] == 'Test Account'


def test_process_tool_call_list_accounts():
    """Test process_tool_call handles list_accounts tool."""
    with patch('central_ops_agent.get_accounts') as mock_get:
        mock_get.return_value = [
            {'account_id': '111', 'name': 'Acc1', 'environment': 'prod'}
        ]

        from central_ops_agent import process_tool_call

        result = process_tool_call(
            tool_name="list_accounts",
            tool_input={},
            workload_token="test-token"
        )

        parsed = json.loads(result)
        assert "accounts" in parsed
        assert len(parsed["accounts"]) == 1
        assert parsed["accounts"][0]["account_id"] == "111"


def test_process_tool_call_query_aws_resources():
    """Test process_tool_call handles query_aws_resources tool."""
    with patch('central_ops_agent.call_gateway_mcp') as mock_gateway:
        mock_gateway.return_value = {"instances": []}

        from central_ops_agent import process_tool_call

        result = process_tool_call(
            tool_name="query_aws_resources",
            tool_input={
                "account_id": "123456789012",
                "tool_name": "aws___call_aws",
                "arguments": {"cli_command": "aws ec2 describe-instances"},
                "region": "us-east-1"
            },
            workload_token="test-token"
        )

        parsed = json.loads(result)
        assert parsed == {"instances": []}
        mock_gateway.assert_called_once()


def test_process_tool_call_unknown_tool():
    """Test process_tool_call returns error for unknown tools."""
    from central_ops_agent import process_tool_call

    result = process_tool_call(
        tool_name="unknown_tool",
        tool_input={},
        workload_token="test-token"
    )

    parsed = json.loads(result)
    assert "error" in parsed
    assert "Unknown tool" in parsed["error"]


def test_converse_with_tools_returns_text():
    """Test converse_with_tools returns text response."""
    mock_bedrock = MagicMock()
    mock_bedrock.converse.return_value = {
        "stopReason": "end_turn",
        "output": {
            "message": {
                "content": [{"text": "Here are your EC2 instances..."}]
            }
        }
    }

    with patch('central_ops_agent.get_accounts') as mock_get_accounts:
        mock_get_accounts.return_value = []

        from central_ops_agent import converse_with_tools

        result = converse_with_tools(
            prompt="List EC2 instances in account 123",
            workload_token="test-token",
            bedrock_client=mock_bedrock
        )

        assert result == "Here are your EC2 instances..."
        mock_bedrock.converse.assert_called_once()


def test_converse_with_tools_handles_tool_use():
    """Test converse_with_tools processes tool calls correctly."""
    mock_bedrock = MagicMock()

    # First response requests tool use
    tool_use_response = {
        "stopReason": "tool_use",
        "output": {
            "message": {
                "role": "assistant",
                "content": [{
                    "toolUse": {
                        "toolUseId": "tool-123",
                        "name": "query_aws_resources",
                        "input": {
                            "account_id": "123456789012",
                            "tool_name": "aws___call_aws",
                            "arguments": {"cli_command": "aws ec2 describe-instances"}
                        }
                    }
                }]
            }
        }
    }

    # Second response is final text
    final_response = {
        "stopReason": "end_turn",
        "output": {
            "message": {
                "content": [{"text": "Found 2 instances in your account."}]
            }
        }
    }

    mock_bedrock.converse.side_effect = [tool_use_response, final_response]

    with patch('central_ops_agent.get_accounts') as mock_get_accounts:
        mock_get_accounts.return_value = []

        with patch('central_ops_agent.call_gateway_mcp') as mock_gateway:
            mock_gateway.return_value = {"instances": [{"id": "i-123"}, {"id": "i-456"}]}

            from central_ops_agent import converse_with_tools

            result = converse_with_tools(
                prompt="List EC2 instances in account 123456789012",
                workload_token="test-token",
                bedrock_client=mock_bedrock
            )

            assert result == "Found 2 instances in your account."
            assert mock_bedrock.converse.call_count == 2
            mock_gateway.assert_called_once()


def test_handler_returns_response():
    """Test handler function returns properly formatted response."""
    import sys
    # Clear module to allow re-import
    if 'central_ops_agent' in sys.modules:
        del sys.modules['central_ops_agent']

    with patch.dict('os.environ', {'WORKLOAD_TOKEN': 'test-token'}):
        import central_ops_agent

        # Mock converse_with_tools after import
        with patch.object(central_ops_agent, 'converse_with_tools') as mock_converse:
            mock_converse.return_value = "Test response"

            result = central_ops_agent.handler({"prompt": "Test prompt"}, None)

            assert result == {"response": "Test response"}
            mock_converse.assert_called_once_with("Test prompt", "test-token")


def test_handler_empty_prompt():
    """Test handler returns message for empty prompt."""
    import sys
    if 'central_ops_agent' in sys.modules:
        del sys.modules['central_ops_agent']

    from central_ops_agent import handler

    result = handler({"prompt": ""}, None)

    assert result == {"response": "Please provide a prompt."}
