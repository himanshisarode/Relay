#!/usr/bin/env bash
# Build the backend image, push it to ECR, and create or update the CloudFormation stack (deploy/aws/backend.yml).
# Needs the AWS CLI v2 (after `aws configure`) and Docker running. From the repo root, in Git Bash:
#   bash deploy/aws/deploy-backend.sh
# Run it again after every backend change; it builds a new image and App Runner rolls over to it.
set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE=relay.env
if [ ! -f "$ENV_FILE" ]; then
  cp relay.env.example "$ENV_FILE"
  echo "Created deploy/aws/relay.env. Fill in FRONTEND_URL and the SMTP settings, then run this again."
  exit 1
fi
set -a; . "./$ENV_FILE"; set +a
: "${FRONTEND_URL:?set FRONTEND_URL in deploy/aws/relay.env}"
REGION=${AWS_REGION:-ap-south-1}
STACK=${STACK_NAME:-relay-backend}
REPO=relay-backend

# Secrets are generated once and kept in relay.env (git-ignored), so later runs reuse them.
if [ -z "${DB_PASSWORD:-}" ]; then DB_PASSWORD=$(openssl rand -hex 20); echo "DB_PASSWORD=$DB_PASSWORD" >> "$ENV_FILE"; fi
if [ -z "${CRON_KEY:-}" ]; then CRON_KEY=$(openssl rand -hex 24); echo "CRON_KEY=$CRON_KEY" >> "$ENV_FILE"; fi

echo "== 1/4 AWS account"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

echo "== 2/4 Container registry"
aws ecr describe-repositories --region "$REGION" --repository-names "$REPO" >/dev/null 2>&1 \
  || aws ecr create-repository --region "$REGION" --repository-name "$REPO" \
       --image-scanning-configuration scanOnPush=true >/dev/null

echo "== 3/4 Build and push the backend image"
TAG="$(git rev-parse --short HEAD 2>/dev/null || echo build)-$(date +%Y%m%d%H%M%S)"
IMAGE="$REGISTRY/$REPO:$TAG"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker build --platform linux/amd64 -t "$IMAGE" ../../backend
docker push "$IMAGE"

echo "== 4/4 CloudFormation stack $STACK (first run creates the database: about 10-15 minutes)"
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" --template-file backend.yml \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides \
    "ImageUri=$IMAGE" "DbPassword=$DB_PASSWORD" "CronKey=$CRON_KEY" "FrontendUrl=$FRONTEND_URL" \
    "SeedOnStart=${SEED_ON_START:-demo}" "SmtpHost=${SMTP_HOST:-}" "SmtpPort=${SMTP_PORT:-587}" \
    "SmtpUser=${SMTP_USER:-}" "SmtpPassword=${SMTP_PASSWORD:-}" "SmtpFrom=${SMTP_FROM:-Relay <no-reply@example.org>}"

API_URL=$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
echo
echo "Backend is live at: $API_URL   (check $API_URL/health)"
echo "Next: paste deploy/aws/amplify-rewrites.json into Amplify, replacing API_URL with $API_URL"
