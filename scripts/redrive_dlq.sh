#!/usr/bin/env bash
set -euo pipefail

STAGE="${STAGE:-dev}"
SERVICE="${SERVICE:-clickpe-loan-engine}"

export AWS_PROFILE="${AWS_PROFILE:-clickpe}"
export AWS_REGION="${AWS_REGION:-ap-southeast-2}"
export AWS_PAGER=""

queue_url() {
  aws sqs get-queue-url --queue-name "${SERVICE}-${STAGE}-$1" --query QueueUrl --output text
}

queue_arn() {
  aws sqs get-queue-attributes --queue-url "$(queue_url "$1")" \
    --attribute-names QueueArn --query Attributes.QueueArn --output text
}

DEPTH="$(aws sqs get-queue-attributes --queue-url "$(queue_url ingest-dlq)" \
  --attribute-names ApproximateNumberOfMessages --query Attributes.ApproximateNumberOfMessages --output text)"
echo "ingest-dlq holds ${DEPTH} message(s)"
[[ "${DEPTH}" != "0" ]] || exit 0

aws sqs start-message-move-task \
  --source-arn "$(queue_arn ingest-dlq)" \
  --destination-arn "$(queue_arn ingest)" \
  --query TaskHandle --output text
