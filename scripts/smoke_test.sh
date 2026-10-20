#!/usr/bin/env bash
set -euo pipefail

FUNCTION_PREFIX="${FUNCTION_PREFIX:-clickpe-loan-engine-dev}"
CSV="${1:-tests/fixtures/good_users.csv}"
EXPECTED_ROWS="${EXPECTED_ROWS:-$(($(wc -l < "$CSV") - 1))}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-180}"
POLL_SECONDS=3

export AWS_PROFILE="${AWS_PROFILE:-clickpe}"
export AWS_REGION="${AWS_REGION:-ap-southeast-2}"
export AWS_PAGER=""

function_url() {
  aws lambda get-function-url-config \
    --function-name "${FUNCTION_PREFIX}-$1" \
    --query FunctionUrl --output text
}

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

UPLOAD_URL="$(function_url getUploadUrl)"
STATUS_URL="$(function_url batchStatus)"
echo "get-upload-url: ${UPLOAD_URL}"
echo "batch-status:   ${STATUS_URL}"

ISSUED="$(curl -sS --fail-with-body -X POST "${UPLOAD_URL}")"
BATCH_ID="$(jq -r .batch_id <<<"${ISSUED}")"
S3_URL="$(jq -r .upload.url <<<"${ISSUED}")"
echo "batch_id: ${BATCH_ID}"

FORM_ARGS=()
while IFS= read -r field; do
  FORM_ARGS+=(--form-string "${field}")
done < <(jq -r '.upload.fields | to_entries[] | "\(.key)=\(.value)"' <<<"${ISSUED}")

UPLOAD_CODE="$(curl -sS -o /dev/null -w '%{http_code}' "${FORM_ARGS[@]}" -F "file=@${CSV};type=text/csv" "${S3_URL}")"
[[ "${UPLOAD_CODE}" == "204" ]] || fail "S3 upload returned HTTP ${UPLOAD_CODE}"
echo "uploaded ${CSV}: HTTP ${UPLOAD_CODE}"

DEADLINE=$((SECONDS + TIMEOUT_SECONDS))
LAST_STATUS=""
while ((SECONDS < DEADLINE)); do
  BODY="$(curl -sS --fail-with-body "${STATUS_URL}?batch_id=${BATCH_ID}")"
  STATUS="$(jq -r .status <<<"${BODY}")"
  if [[ "${STATUS}" != "${LAST_STATUS}" ]]; then
    echo "[+${SECONDS}s] status=${STATUS} chunks=$(jq -r '"\(.chunks_done)/\(.total_chunks)"' <<<"${BODY}")"
    LAST_STATUS="${STATUS}"
  fi
  case "${STATUS}" in
    processed | matching | matched | notifying | notified)
      echo "${BODY}" | jq .
      ROWS_TOTAL="$(jq -r '.rows_ok + .rows_rejected' <<<"${BODY}")"
      [[ "${ROWS_TOTAL}" == "${EXPECTED_ROWS}" ]] || fail "rows_ok + rows_rejected = ${ROWS_TOTAL}, expected ${EXPECTED_ROWS}"
      echo "PASS: batch ${BATCH_ID} reached ${STATUS} with ${ROWS_TOTAL} rows accounted for"
      exit 0
      ;;
    failed)
      echo "${BODY}" | jq .
      fail "batch ${BATCH_ID} failed"
      ;;
  esac
  sleep "${POLL_SECONDS}"
done

fail "batch ${BATCH_ID} still '${LAST_STATUS}' after ${TIMEOUT_SECONDS}s"
