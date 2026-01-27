# AgentCore Runtime container for CentralOpsAgent
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent code
COPY central_ops_agent.py .
COPY .bedrock_agentcore.yaml .

# AgentCore Runtime expects the server on port 8000
EXPOSE 8000

# Run the agent
CMD ["python", "central_ops_agent.py"]
