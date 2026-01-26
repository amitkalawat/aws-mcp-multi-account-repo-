# agentcore-gateway/tests/conftest.py
import sys
from pathlib import Path

# Add lambda directory to path so tests can import handler
lambda_dir = Path(__file__).parent.parent / 'lambda'
sys.path.insert(0, str(lambda_dir))

# Add agent directory to path so tests can import central_ops_agent
agent_dir = Path(__file__).parent.parent / 'agent'
sys.path.insert(0, str(agent_dir))
