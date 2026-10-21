#!/usr/bin/env bash
set -euo pipefail

FUNCTION_PREFIX="${FUNCTION_PREFIX:-clickpe-loan-engine-dev}"
CSV="${1:-data/synthetic_100k.csv}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-1800}"
POLL_SECONDS=2
SETTLE_SECONDS=20

export AWS_PROFILE="${AWS_PROFILE:-clickpe}"
export AWS_REGION="${AWS_REGION:-ap-southeast-2}"
export AWS_PAGER=""

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

function_url() {
  aws lambda get-function-url-config \
    --function-name "${FUNCTION_PREFIX}-$1" \
    --query FunctionUrl --output text
}

elapsed_since() {
  awk -v now="$(date +%s.%N)" -v start="$1" 'BEGIN { printf "%.1f", now - start }'
}

UPLOAD_URL="$(function_url getUploadUrl)"
STATUS_URL="$(function_url batchStatus)"
ISSUED="$(curl -sS --fail-with-body -X POST "${UPLOAD_URL}")"
BATCH_ID="$(jq -r .batch_id <<<"${ISSUED}")"
S3_URL="$(jq -r .upload.url <<<"${ISSUED}")"
echo "batch_id: ${BATCH_ID}"
echo "file: ${CSV} rows=$(($(wc -l <"${CSV}") - 1)) bytes=$(stat -c %s "${CSV}")"

FORM_ARGS=()
while IFS= read -r field; do
  FORM_ARGS+=(--form-string "${field}")
done < <(jq -r '.upload.fields | to_entries[] | "\(.key)=\(.value)"' <<<"${ISSUED}")

START="$(date +%s.%N)"
UPLOAD_CODE="$(curl -sS -o /dev/null -w '%{http_code}' "${FORM_ARGS[@]}" -F "file=@${CSV};type=text/csv" "${S3_URL}")"
[[ "${UPLOAD_CODE}" == "204" ]] || fail "S3 upload returned HTTP ${UPLOAD_CODE}"
echo "[+$(elapsed_since "${START}")s] upload finished: HTTP ${UPLOAD_CODE}"

LAST_STATUS=""
LAST_CHUNKS=""
DEADLINE=$((SECONDS + TIMEOUT_SECONDS))
while ((SECONDS < DEADLINE)); do
  BODY="$(curl -sS --fail-with-body "${STATUS_URL}?batch_id=${BATCH_ID}")"
  STATUS="$(jq -r .status <<<"${BODY}")"
  CHUNKS="$(jq -r '"\(.chunks_done)/\(.total_chunks)"' <<<"${BODY}")"
  if [[ "${STATUS}" != "${LAST_STATUS}" || "${CHUNKS}" != "${LAST_CHUNKS}" ]]; then
    echo "[+$(elapsed_since "${START}")s] status=${STATUS} chunks=${CHUNKS}"
    LAST_STATUS="${STATUS}"
    LAST_CHUNKS="${CHUNKS}"
  fi
  if [[ "${STATUS}" == "failed" ]]; then
    jq . <<<"${BODY}"
    fail "batch ended as failed"
  fi
  if [[ "${STATUS}" == "matched" || "${STATUS}" == "notified" ]]; then
    SETTLE_STARTED="${SETTLE_STARTED:-${SECONDS}}"
    if ((SECONDS - SETTLE_STARTED >= SETTLE_SECONDS)); then
      jq . <<<"${BODY}"
      echo "DONE: batch ${BATCH_ID} ${STATUS} after $(elapsed_since "${START}")s from upload start"
      exit 0
    fi
  else
    unset SETTLE_STARTED
  fi
  sleep "${POLL_SECONDS}"
done
fail "batch ${BATCH_ID} still ${LAST_STATUS} after ${TIMEOUT_SECONDS}s"
