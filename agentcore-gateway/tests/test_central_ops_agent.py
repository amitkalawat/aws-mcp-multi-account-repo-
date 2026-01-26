"""Tests for CentralOpsAgent."""
import json
import pytest
from unittest.mock import patch, MagicMock


def test_build_tools_returns_query_tool():
    """Test that build_tools returns the query_aws_resources tool."""
    from central_ops_agent import build_tools

    tools = build_tools()

    assert len(tools) == 1
    assert tools[0]["name"] == "query_aws_resources"
    # Bedrock Converse API uses camelCase inputSchema with nested json key
    assert "account_id" in tools[0]["inputSchema"]["json"]["properties"]
    assert "tool_name" in tools[0]["inputSchema"]["json"]["properties"]


def test_call_gateway_constructs_request():
    """Test that call_gateway builds correct request structure."""
    with patch('central_ops_agent.urllib.request.urlopen') as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"result": "success"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        from central_ops_agent import call_gateway

        result = call_gateway(
            gateway_url="https://gateway.example.com",
            action="query",
            tool_name="ec2_describe_instances",
            account_id="222222222222",
            arguments={},
            workload_token="test-token"
        )

        assert result == {"result": "success"}

        # Verify the request was constructed correctly
        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        assert request.get_header('Authorization') == 'Bearer test-token'
        assert request.get_header('Content-type') == 'application/json'


def test_call_gateway_query_all_action():
    """Test that call_gateway handles query_all action."""
    with patch('central_ops_agent.urllib.request.urlopen') as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"accounts": ["111", "222"]}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        from central_ops_agent import call_gateway

        result = call_gateway(
            gateway_url="https://gateway.example.com",
            action="query_all",
            tool_name="s3_list_buckets",
            arguments={"region": "us-west-2"},
            workload_token="test-token"
        )

        assert result == {"accounts": ["111", "222"]}


def test_process_tool_call_query_aws_resources():
    """Test process_tool_call handles query_aws_resources tool."""
    with patch('central_ops_agent.call_gateway') as mock_gateway:
        mock_gateway.return_value = {"instances": []}

        from central_ops_agent import process_tool_call

        result = process_tool_call(
            tool_name="query_aws_resources",
            tool_input={
                "account_id": "123456789012",
                "tool_name": "ec2_describe_instances",
                "arguments": {},
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
                            "tool_name": "ec2_describe_instances"
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

    with patch('central_ops_agent.call_gateway') as mock_gateway:
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
