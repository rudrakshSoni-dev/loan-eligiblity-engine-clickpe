#!/usr/bin/env bash
set -euo pipefail

FUNCTION_PREFIX="${FUNCTION_PREFIX:-clickpe-loan-engine-dev}"
PORT="${PORT:-8000}"
UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../ui" && pwd)"

export AWS_PROFILE="${AWS_PROFILE:-clickpe}"
export AWS_REGION="${AWS_REGION:-ap-southeast-2}"
export AWS_PAGER=""

function_url() {
  aws lambda get-function-url-config \
    --function-name "${FUNCTION_PREFIX}-$1" \
    --query FunctionUrl --output text
}

UPLOAD_URL="$(function_url getUploadUrl)"
STATUS_URL="$(function_url batchStatus)"

cat > "${UI_DIR}/config.js" <<EOF
window.LOAN_ENGINE_CONFIG = {
  uploadUrlEndpoint: "${UPLOAD_URL}",
  batchStatusEndpoint: "${STATUS_URL}"
};
EOF

echo "wrote ${UI_DIR}/config.js"
echo "get-upload-url: ${UPLOAD_URL}"
echo "batch-status:   ${STATUS_URL}"
echo "open http://localhost:${PORT}/ (the only origin allowed by CORS unless deployed with --ui-origin)"
exec python3 -m http.server "${PORT}" --bind 127.0.0.1 --directory "${UI_DIR}"
