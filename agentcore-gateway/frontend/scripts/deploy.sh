#!/bin/bash
set -e

# Configuration
REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"

echo "=== Building frontend ==="
npm run build

echo "=== Getting stack outputs ==="
BUCKET_NAME=$(aws cloudformation describe-stacks \
  --stack-name "CentralOps-Frontend-${ENVIRONMENT}" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`BucketName`].OutputValue' \
  --output text)

DISTRIBUTION_ID=$(aws cloudformation describe-stacks \
  --stack-name "CentralOps-Frontend-${ENVIRONMENT}" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`DistributionId`].OutputValue' \
  --output text)

echo "Bucket: $BUCKET_NAME"
echo "Distribution: $DISTRIBUTION_ID"

echo "=== Syncing to S3 ==="
aws s3 sync dist/ "s3://${BUCKET_NAME}/" --delete --region "$REGION"

echo "=== Invalidating CloudFront cache ==="
aws cloudfront create-invalidation \
  --distribution-id "$DISTRIBUTION_ID" \
  --paths "/*"

echo "=== Done ==="
FRONTEND_URL=$(aws cloudformation describe-stacks \
  --stack-name "CentralOps-Frontend-${ENVIRONMENT}" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`FrontendUrl`].OutputValue' \
  --output text)

echo "Frontend available at: $FRONTEND_URL"
