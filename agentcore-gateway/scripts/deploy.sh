#!/bin/bash
# agentcore-gateway/scripts/deploy.sh
# Deploy AgentCore Gateway + Runtime infrastructure using CDK

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="${SCRIPT_DIR}/../infrastructure"
AGENT_DIR="${SCRIPT_DIR}/../agent"

# Configuration
ENVIRONMENT="${ENVIRONMENT:-dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI not found"
        exit 1
    fi

    if ! command -v npx &> /dev/null; then
        log_error "Node.js/npx not found - required for CDK"
        exit 1
    fi

    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS credentials not valid"
        exit 1
    fi

    log_info "Prerequisites OK"
}

install_cdk_deps() {
    log_info "Installing CDK dependencies..."
    cd "${INFRA_DIR}"
    npm install
    cd - > /dev/null
}

bootstrap_cdk() {
    log_info "Bootstrapping CDK (if needed)..."
    cd "${INFRA_DIR}"
    npx cdk bootstrap --context environment="${ENVIRONMENT}" --context region="${AWS_REGION}" || true
    cd - > /dev/null
}

deploy_stacks() {
    log_info "Deploying CDK stacks..."
    cd "${INFRA_DIR}"
    npx cdk deploy --all \
        --context environment="${ENVIRONMENT}" \
        --context region="${AWS_REGION}" \
        --require-approval never
    cd - > /dev/null
}

get_outputs() {
    log_info "Getting stack outputs..."

    COGNITO_USER_POOL_ID=$(aws cloudformation describe-stacks \
        --stack-name "CentralOps-Cognito-${ENVIRONMENT}" \
        --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
        --output text --region "${AWS_REGION}")

    COGNITO_CLIENT_ID=$(aws cloudformation describe-stacks \
        --stack-name "CentralOps-Cognito-${ENVIRONMENT}" \
        --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' \
        --output text --region "${AWS_REGION}")

    COGNITO_DISCOVERY_URL=$(aws cloudformation describe-stacks \
        --stack-name "CentralOps-Cognito-${ENVIRONMENT}" \
        --query 'Stacks[0].Outputs[?OutputKey==`DiscoveryUrl`].OutputValue' \
        --output text --region "${AWS_REGION}")

    LAMBDA_ARN=$(aws cloudformation describe-stacks \
        --stack-name "CentralOps-Lambda-${ENVIRONMENT}" \
        --query 'Stacks[0].Outputs[?OutputKey==`LambdaArn`].OutputValue' \
        --output text --region "${AWS_REGION}")

    GATEWAY_ROLE_ARN=$(aws cloudformation describe-stacks \
        --stack-name "CentralOps-Roles-${ENVIRONMENT}" \
        --query 'Stacks[0].Outputs[?OutputKey==`GatewayRoleArn`].OutputValue' \
        --output text --region "${AWS_REGION}")

    RUNTIME_ROLE_ARN=$(aws cloudformation describe-stacks \
        --stack-name "CentralOps-Roles-${ENVIRONMENT}" \
        --query 'Stacks[0].Outputs[?OutputKey==`RuntimeRoleArn`].OutputValue' \
        --output text --region "${AWS_REGION}")
}

print_gateway_commands() {
    log_info "Gateway and Runtime CLI Commands"
    log_warn "Run these commands manually after CDK deployment:"
    echo ""
    echo "# 1. Create Gateway"
    echo "aws bedrock-agentcore-control create-gateway \\"
    echo "  --gateway-name central-ops-gateway-${ENVIRONMENT} \\"
    echo "  --role-arn ${GATEWAY_ROLE_ARN}"
    echo ""
    echo "# 2. Add Lambda target to Gateway"
    echo "aws bedrock-agentcore-control create-gateway-target \\"
    echo "  --gateway-identifier central-ops-gateway-${ENVIRONMENT} \\"
    echo "  --name bridge-lambda \\"
    echo "  --target-configuration '{\"lambdaTargetConfiguration\": {\"lambdaArn\": \"${LAMBDA_ARN}\"}}'"
    echo ""
    echo "# 3. Deploy Runtime Agent with JWT auth"
    echo "cd ${AGENT_DIR}"
    echo "agentcore deploy --execution-role ${RUNTIME_ROLE_ARN}"
    echo ""
}

print_summary() {
    echo ""
    log_info "=========================================="
    log_info "Deployment Summary"
    log_info "=========================================="
    log_info "Environment: ${ENVIRONMENT}"
    log_info "Region: ${AWS_REGION}"
    echo ""
    log_info "CDK Stacks:"
    log_info "  Cognito:  CentralOps-Cognito-${ENVIRONMENT}"
    log_info "  Lambda:   CentralOps-Lambda-${ENVIRONMENT}"
    log_info "  Roles:    CentralOps-Roles-${ENVIRONMENT}"
    echo ""
    log_info "Resources:"
    log_info "  Cognito Pool:    ${COGNITO_USER_POOL_ID}"
    log_info "  Cognito Client:  ${COGNITO_CLIENT_ID}"
    log_info "  Discovery URL:   ${COGNITO_DISCOVERY_URL}"
    log_info "  Lambda ARN:      ${LAMBDA_ARN}"
    log_info "  Gateway Role:    ${GATEWAY_ROLE_ARN}"
    log_info "  Runtime Role:    ${RUNTIME_ROLE_ARN}"
    log_info "=========================================="
}

main() {
    check_prerequisites
    install_cdk_deps
    bootstrap_cdk
    deploy_stacks
    get_outputs
    print_gateway_commands
    print_summary
}

main "$@"
