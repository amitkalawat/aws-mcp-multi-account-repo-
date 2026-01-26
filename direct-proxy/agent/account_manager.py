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
