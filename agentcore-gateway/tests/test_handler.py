"""Tests for Lambda bridge handler."""
import json
import pytest
from unittest.mock import patch, MagicMock
import sys


def reload_handler():
    """Reload handler module to pick up fresh state."""
    if 'handler' in sys.modules:
        del sys.modules['handler']
    from handler import handler
    return handler


def test_query_action_calls_mcp():
    """Test query action calls AWS MCP Server."""
    import handler as handler_module

    with patch.object(handler_module, 'call_aws_mcp') as mock_call_mcp:
        mock_call_mcp.return_value = {'result': {'content': [{'text': 'test'}]}}

        event = {'body': json.dumps({
            'action': 'query',
            'tool_name': 'aws___list_regions',
            'account_id': '222222222222',
            'arguments': {}
        })}
        result = handler_module.handler(event, None)

        assert result['statusCode'] == 200
        mock_call_mcp.assert_called_once_with('aws___list_regions', {}, '222222222222', 'us-east-1')


def test_query_missing_account_id_returns_400():
    """Test query without account_id returns 400 error."""
    handler = reload_handler()

    event = {'body': json.dumps({
        'action': 'query',
        'tool_name': 'aws___list_regions',
        'arguments': {}
    })}
    result = handler(event, None)

    assert result['statusCode'] == 400
    body = json.loads(result['body'])
    assert 'error' in body
    assert 'account_id' in body['error']


def test_query_missing_tool_name_returns_400():
    """Test query without tool_name returns 400 error."""
    handler = reload_handler()

    event = {'body': json.dumps({
        'action': 'query',
        'account_id': '222222222222',
        'arguments': {}
    })}
    result = handler(event, None)

    assert result['statusCode'] == 400
    body = json.loads(result['body'])
    assert 'error' in body
    assert 'tool_name' in body['error']


def test_unknown_action_returns_400():
    """Test unknown action returns 400 error."""
    handler = reload_handler()

    event = {'body': json.dumps({'action': 'invalid_action'})}
    result = handler(event, None)

    assert result['statusCode'] == 400
    body = json.loads(result['body'])
    assert 'error' in body


def test_gateway_invocation_with_query_tool():
    """Test Gateway invocation format (tool name in context)."""
    import handler as handler_module

    # Mock context with Gateway format
    mock_context = MagicMock()
    mock_context.client_context = MagicMock()
    mock_context.client_context.custom = {'bedrockAgentCoreToolName': 'bridge-lambda___query'}

    with patch.object(handler_module, 'call_aws_mcp') as mock_call_mcp:
        mock_call_mcp.return_value = {'result': {'content': [{'text': 'regions'}]}}

        # Gateway passes arguments directly in event (not in body)
        event = {
            'account_id': '222222222222',
            'tool_name': 'aws___list_regions',
            'arguments': {},
            'region': 'us-west-2'
        }
        result = handler_module.handler(event, mock_context)

        # Gateway invocation returns result directly (no statusCode wrapper)
        assert 'result' in result
        mock_call_mcp.assert_called_once_with('aws___list_regions', {}, '222222222222', 'us-west-2')


def test_gateway_invocation_missing_account_id():
    """Test Gateway invocation without account_id returns error."""
    import handler as handler_module

    mock_context = MagicMock()
    mock_context.client_context = MagicMock()
    mock_context.client_context.custom = {'bedrockAgentCoreToolName': 'bridge-lambda___query'}

    event = {
        'tool_name': 'aws___list_regions',
        'arguments': {}
    }
    result = handler_module.handler(event, mock_context)

    assert 'error' in result
    assert 'account_id' in result['error']


def test_gateway_invocation_unknown_tool():
    """Test Gateway invocation with unknown tool returns error."""
    import handler as handler_module

    mock_context = MagicMock()
    mock_context.client_context = MagicMock()
    mock_context.client_context.custom = {'bedrockAgentCoreToolName': 'bridge-lambda___unknown_tool'}

    event = {'account_id': '222222222222'}
    result = handler_module.handler(event, mock_context)

    assert 'error' in result
    assert 'unknown_tool' in result['error'].lower()
