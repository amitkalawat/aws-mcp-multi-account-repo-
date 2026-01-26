"""Tests for Lambda bridge handler."""
import json
import pytest
from unittest.mock import patch, MagicMock


def test_list_accounts_action():
    """Test list_accounts action returns configured accounts."""
    with patch.dict('os.environ', {'TARGET_ACCOUNTS': '[{"id":"222222222222","name":"Production"}]'}):
        # Import inside to pick up mocked env
        import sys
        if 'handler' in sys.modules:
            del sys.modules['handler']
        from handler import handler

        event = {'body': json.dumps({'action': 'list_accounts'})}
        result = handler(event, None)

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert len(body) == 1
        assert body[0]['id'] == '222222222222'


def test_unknown_action_returns_400():
    """Test unknown action returns 400 error."""
    with patch.dict('os.environ', {'TARGET_ACCOUNTS': '[]'}):
        import sys
        if 'handler' in sys.modules:
            del sys.modules['handler']
        from handler import handler

        event = {'body': json.dumps({'action': 'invalid_action'})}
        result = handler(event, None)

        assert result['statusCode'] == 400
        body = json.loads(result['body'])
        assert 'error' in body


def test_query_action_calls_mcp():
    """Test query action calls AWS MCP Server."""
    with patch.dict('os.environ', {'TARGET_ACCOUNTS': '[]'}):
        import sys
        if 'handler' in sys.modules:
            del sys.modules['handler']

        import handler as handler_module

        with patch.object(handler_module, 'call_aws_mcp') as mock_call_mcp:
            mock_call_mcp.return_value = {'result': {'content': [{'text': 'test'}]}}

            event = {'body': json.dumps({
                'action': 'query',
                'tool_name': 'ec2_describe_instances',
                'account_id': '222222222222',
                'arguments': {}
            })}
            result = handler_module.handler(event, None)

            assert result['statusCode'] == 200
            mock_call_mcp.assert_called_once()
