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
