# Direct MCP Proxy Test Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Test the Direct MCP Proxy approach using `mcp-proxy-for-aws` to query AWS resources via the AWS MCP Server.

**Architecture:** Agent runs locally, uses `mcp-proxy-for-aws` to handle SigV4 signing, connects to AWS MCP Server at `https://aws-mcp.us-east-1.api.aws/mcp`. For multi-account, uses STS AssumeRole to switch credentials before MCP calls.

**Tech Stack:** Python 3.11+, boto3, mcp-proxy-for-aws (via uvx), AWS MCP Server

---

## Prerequisites Checklist

Before starting, verify:
- [ ] AWS CLI installed and configured (`aws --version`)
- [ ] `uv` package manager installed (`uv --version`)
- [ ] AWS credentials valid (`aws sts get-caller-identity`)
- [ ] IAM permissions include `aws-mcp:*` actions

---

## Task 1: Verify Prerequisites

**Files:**
- Create: `scripts/verify_prerequisites.sh`

**Step 1: Write the verification script**

```bash
#!/bin/bash
# scripts/verify_prerequisites.sh
set -e

echo "=== Checking Prerequisites ==="

echo -n "1. AWS CLI: "
if command -v aws &> /dev/null; then
    aws --version
else
    echo "MISSING - Install from https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
    exit 1
fi

echo -n "2. uv package manager: "
if command -v uv &> /dev/null; then
    uv --version
else
    echo "MISSING - Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo -n "3. AWS credentials: "
if aws sts get-caller-identity &> /dev/null; then
    aws sts get-caller-identity --query 'Arn' --output text
else
    echo "INVALID - Run 'aws configure' or 'aws sso login'"
    exit 1
fi

echo -n "4. Python 3.11+: "
python3 --version

echo ""
echo "=== All prerequisites satisfied ==="
```

**Step 2: Run the script**

Run: `chmod +x scripts/verify_prerequisites.sh && ./scripts/verify_prerequisites.sh`
Expected: All checks pass with version info displayed

**Step 3: Commit**

```bash
git add scripts/verify_prerequisites.sh
git commit -m "feat: add prerequisites verification script"
```

---

## Task 2: Test MCP Proxy Connection

**Files:**
- Create: `scripts/test_mcp_connection.py`

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run the test**

Run: `python3 scripts/test_mcp_connection.py`
Expected: PASS with tool count and sample tool names

**Step 3: Commit**

```bash
git add scripts/test_mcp_connection.py
git commit -m "feat: add MCP connection test script"
```

---

## Task 3: Create Agent Directory Structure

**Files:**
- Create: `agent/__init__.py`
- Create: `agent/requirements.txt`
- Create: `tests/__init__.py`

**Step 1: Create directory structure**

```bash
mkdir -p agent tests
touch agent/__init__.py tests/__init__.py
```

**Step 2: Write requirements.txt**

```text
# agent/requirements.txt
boto3>=1.35.0
pytest>=8.0.0
```

**Step 3: Install dependencies**

Run: `pip install -r agent/requirements.txt`
Expected: Successfully installed boto3 and pytest

**Step 4: Commit**

```bash
git add agent/__init__.py agent/requirements.txt tests/__init__.py
git commit -m "feat: create agent directory structure"
```

---

## Task 4: Implement Account Manager

**Files:**
- Create: `agent/account_manager.py`
- Create: `tests/test_account_manager.py`

**Step 1: Write the failing test**

```python
# tests/test_account_manager.py
"""Tests for AccountManager."""
import os
import pytest
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
    mock_sts.assume_role.return_value = {
        'Credentials': {
            'AccessKeyId': 'AKIATEST',
            'SecretAccessKey': 'secret',
            'SessionToken': 'token',
            'Expiration': MagicMock()
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_account_manager.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'agent.account_manager'"

**Step 3: Write the implementation**

```python
# agent/account_manager.py
"""Account manager for cross-account role assumption and credential caching."""
import boto3
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class AccountCredentials:
    """Container for temporary AWS credentials."""
    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: datetime
    account_id: str


class AccountManager:
    """Manages cross-account role assumption and credential caching."""

    ROLE_NAME = "CentralOpsTargetRole"
    SESSION_DURATION = 3600  # 1 hour
    REFRESH_BUFFER = timedelta(minutes=5)

    def __init__(self, registry_path: str = None):
        """
        Initialize AccountManager.

        Args:
            registry_path: Path to account registry JSON file.
                          Falls back to ACCOUNT_REGISTRY env var.
        """
        self.sts = boto3.client('sts')
        self.credential_cache: Dict[str, AccountCredentials] = {}
        self.accounts = self._load_registry(registry_path)

    def _load_registry(self, path: str = None) -> Dict:
        """Load account registry from file or environment."""
        if path and os.path.exists(path):
            with open(path) as f:
                return json.load(f)

        # Try environment variable
        registry_json = os.environ.get('ACCOUNT_REGISTRY')
        if registry_json:
            return json.loads(registry_json)

        return {"accounts": []}

    def list_accounts(self) -> List[Dict]:
        """List all available target accounts (excludes central)."""
        return [
            {
                "id": acc["id"],
                "name": acc["name"],
                "environment": acc.get("environment", "unknown")
            }
            for acc in self.accounts.get("accounts", [])
            if acc.get("role") != "central"
        ]

    def get_credentials(self, account_id: str) -> AccountCredentials:
        """
        Get credentials for target account, using cache if valid.

        Args:
            account_id: 12-digit AWS account ID

        Returns:
            AccountCredentials with temporary credentials
        """
        # Check cache
        if account_id in self.credential_cache:
            creds = self.credential_cache[account_id]
            if not self._is_expired(creds):
                return creds

        # Assume role
        role_arn = f"arn:aws:iam::{account_id}:role/{self.ROLE_NAME}"

        response = self.sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=f"CentralOps-{account_id}",
            DurationSeconds=self.SESSION_DURATION
        )

        creds = AccountCredentials(
            access_key_id=response['Credentials']['AccessKeyId'],
            secret_access_key=response['Credentials']['SecretAccessKey'],
            session_token=response['Credentials']['SessionToken'],
            expiration=response['Credentials']['Expiration'],
            account_id=account_id
        )

        self.credential_cache[account_id] = creds
        return creds

    def set_environment_credentials(self, account_id: str) -> None:
        """Set AWS credentials as environment variables for MCP proxy."""
        creds = self.get_credentials(account_id)

        os.environ['AWS_ACCESS_KEY_ID'] = creds.access_key_id
        os.environ['AWS_SECRET_ACCESS_KEY'] = creds.secret_access_key
        os.environ['AWS_SESSION_TOKEN'] = creds.session_token

    def clear_environment_credentials(self) -> None:
        """Clear AWS credential environment variables."""
        for key in ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN']:
            os.environ.pop(key, None)

    def _is_expired(self, creds: AccountCredentials) -> bool:
        """Check if credentials are expired or expiring soon."""
        now = datetime.now(timezone.utc)
        expiration = creds.expiration
        if expiration.tzinfo is None:
            expiration = expiration.replace(tzinfo=timezone.utc)
        return now + self.REFRESH_BUFFER >= expiration
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_account_manager.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add agent/account_manager.py tests/test_account_manager.py
git commit -m "feat: implement AccountManager with credential caching"
```

---

## Task 5: Implement MCP Client

**Files:**
- Create: `agent/mcp_client.py`
- Create: `tests/test_mcp_client.py`

**Step 1: Write the failing test**

```python
# tests/test_mcp_client.py
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_client.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'agent.mcp_client'"

**Step 3: Write the implementation**

```python
# agent/mcp_client.py
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_client.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add agent/mcp_client.py tests/test_mcp_client.py
git commit -m "feat: implement MCPClient for AWS MCP Server"
```

---

## Task 6: Create Integration Test Script

**Files:**
- Create: `scripts/test_integration.py`

**Step 1: Write the integration test**

```python
#!/usr/bin/env python3
# scripts/test_integration.py
"""
Integration test for Direct MCP Proxy approach.

This script tests:
1. AWS credentials are valid
2. MCP proxy can connect to AWS MCP Server
3. Can list EC2 instances in current account
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
    """Test 2: Verify MCP proxy connection."""
    print("\nTest 2: Testing MCP proxy connection...")
    client = MCPClient()
    tools = client.list_tools()
    print(f"  Retrieved {len(tools)} tools")
    print("  PASS")
    return tools


def test_ec2_describe(tools):
    """Test 3: Call EC2 DescribeInstances."""
    print("\nTest 3: Testing EC2 DescribeInstances...")

    # Find the EC2 describe instances tool
    ec2_tool = None
    for tool in tools:
        name = tool.get('name', '')
        if 'ec2' in name.lower() and 'describe' in name.lower() and 'instance' in name.lower():
            ec2_tool = tool
            break

    if not ec2_tool:
        print("  SKIP: EC2 describe instances tool not found")
        print("  Available EC2 tools:")
        for tool in tools[:20]:
            if 'ec2' in tool.get('name', '').lower():
                print(f"    - {tool.get('name')}")
        return

    print(f"  Using tool: {ec2_tool['name']}")

    client = MCPClient()
    try:
        result = client.call_tool(ec2_tool['name'], {})
        print(f"  Result: {json.dumps(result, indent=2)[:500]}...")
        print("  PASS")
    except Exception as e:
        print(f"  FAIL: {e}")
        raise


def main():
    """Run all integration tests."""
    print("=" * 60)
    print("Direct MCP Proxy Integration Tests")
    print("=" * 60)

    try:
        account_id = test_aws_identity()
        tools = test_mcp_connection()
        test_ec2_describe(tools)

        print("\n" + "=" * 60)
        print("ALL TESTS PASSED")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

**Step 2: Run the integration test**

Run: `python3 scripts/test_integration.py`
Expected: All 3 tests pass

**Step 3: Commit**

```bash
git add scripts/test_integration.py
git commit -m "feat: add integration test for Direct MCP Proxy"
```

---

## Task 7: Create Account Registry

**Files:**
- Modify: `infrastructure/account-registry.template.json`
- Create: `infrastructure/account-registry.json` (from template)

**Step 1: Verify template exists**

Run: `cat infrastructure/account-registry.template.json`
Expected: JSON template with placeholder account IDs

**Step 2: Create actual registry from template**

```bash
cp infrastructure/account-registry.template.json infrastructure/account-registry.json
```

**Step 3: Edit registry with actual account IDs**

Edit `infrastructure/account-registry.json` with your AWS account IDs.

**Step 4: Add to .gitignore**

Verify `infrastructure/account-registry.json` is in `.gitignore` (contains real account IDs).

**Step 5: Commit template update if needed**

```bash
git add infrastructure/account-registry.template.json
git commit -m "docs: update account registry template"
```

---

## Task 8: Final Verification

**Files:**
- None (verification only)

**Step 1: Run all unit tests**

Run: `pytest tests/ -v`
Expected: All tests pass

**Step 2: Run integration test**

Run: `python3 scripts/test_integration.py`
Expected: All integration tests pass

**Step 3: Run prerequisites check**

Run: `./scripts/verify_prerequisites.sh`
Expected: All prerequisites satisfied

**Step 4: Commit any final changes**

```bash
git status
# If clean, done. Otherwise:
git add -A
git commit -m "chore: final cleanup for Direct MCP Proxy test"
```

---

## Summary

After completing this plan, you will have:

1. **Prerequisites verification** - Script to check all requirements
2. **MCP connection test** - Standalone script to verify AWS MCP Server connectivity
3. **AccountManager** - Credential caching and cross-account role assumption
4. **MCPClient** - Wrapper for mcp-proxy-for-aws calls
5. **Integration tests** - End-to-end verification of the Direct Proxy approach
6. **Account registry** - Configuration for multi-account setup

## Next Steps (Future Tasks)

- [ ] Implement `MultiAccountMCPClient` for credential switching
- [ ] Implement `CentralOpsAgent` with natural language processing
- [ ] Add Dockerfile for containerized deployment
- [ ] Deploy to AgentCore Runtime
