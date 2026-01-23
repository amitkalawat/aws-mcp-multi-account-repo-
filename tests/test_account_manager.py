"""Tests for AccountManager."""
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from agent.account_manager import AccountManager, AccountCredentials


def test_load_registry_from_file(tmp_path):
    """Test loading account registry from JSON file."""
    registry_file = tmp_path / "accounts.json"
    registry_file.write_text('''
    {
        "accounts": [
            {"id": "111111111111", "name": "Central", "environment": "ops", "role": "central"},
            {"id": "222222222222", "name": "Production", "environment": "prod", "role": "workload"}
        ]
    }
    ''')

    manager = AccountManager(str(registry_file))
    accounts = manager.list_accounts()

    assert len(accounts) == 1  # Excludes central account
    assert accounts[0]["id"] == "222222222222"
    assert accounts[0]["name"] == "Production"


def test_list_accounts_excludes_central():
    """Test that list_accounts excludes central account."""
    manager = AccountManager()
    manager.accounts = {
        "accounts": [
            {"id": "111", "name": "Central", "role": "central"},
            {"id": "222", "name": "Prod", "role": "workload"},
            {"id": "333", "name": "Dev", "role": "workload"}
        ]
    }

    accounts = manager.list_accounts()

    assert len(accounts) == 2
    assert all(acc["id"] != "111" for acc in accounts)


@patch('agent.account_manager.boto3.client')
def test_get_credentials_caches(mock_boto_client):
    """Test that credentials are cached."""
    mock_sts = MagicMock()
    mock_boto_client.return_value = mock_sts
    # Use a future expiration time to ensure credentials are not expired
    future_expiration = datetime.now(timezone.utc) + timedelta(hours=1)
    mock_sts.assume_role.return_value = {
        'Credentials': {
            'AccessKeyId': 'AKIATEST',
            'SecretAccessKey': 'secret',
            'SessionToken': 'token',
            'Expiration': future_expiration
        }
    }

    manager = AccountManager()

    # First call - should call STS
    creds1 = manager.get_credentials("222222222222")
    assert mock_sts.assume_role.call_count == 1

    # Second call - should use cache
    creds2 = manager.get_credentials("222222222222")
    assert mock_sts.assume_role.call_count == 1  # Still 1, used cache

    assert creds1.access_key_id == creds2.access_key_id
