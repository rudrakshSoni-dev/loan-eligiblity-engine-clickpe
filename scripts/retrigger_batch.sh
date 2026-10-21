#!/usr/bin/env bash
set -euo pipefail

BATCH_ID="${1:-}"
INSTANCE_ID="${N8N_INSTANCE_ID:-i-02ffa9d08e8403a4a}"
FUNCTION_PREFIX="${FUNCTION_PREFIX:-clickpe-loan-engine-dev}"
SECRET_PARAMETER=/clickpe/n8n/webhook_secret
URL_PARAMETER=/clickpe/n8n/webhook_url
UUID_PATTERN='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
WAIT_ATTEMPTS=30
TOKEN_TTL_SECONDS=60
MINT_TOKEN_PY="import base64, hashlib, hmac, json, os, sys, time
b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b\"=\").decode()
pack = lambda value: b64(json.dumps(value, separators=(\",\", \":\"), sort_keys=True).encode())
now = int(time.time())
claims = {\"iss\": \"clickpe-retrigger\", \"batch_id\": sys.argv[1], \"iat\": now, \"exp\": now + ${TOKEN_TTL_SECONDS}}
signing_input = pack({\"alg\": \"HS256\", \"typ\": \"JWT\"}) + \".\" + pack(claims)
signature = hmac.new(os.environ[\"SIGNING_KEY\"].encode(), signing_input.encode(), hashlib.sha256).digest()
print(\"Authorization: Bearer \" + signing_input + \".\" + b64(signature))"
WAIT_SECONDS=2

export AWS_PROFILE="${AWS_PROFILE:-clickpe}"
export AWS_REGION="${AWS_REGION:-ap-southeast-2}"
export AWS_PAGER=""

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[[ "${BATCH_ID}" =~ ${UUID_PATTERN} ]] || fail "usage: $0 <batch_id as a lower-case UUID>"

STATUS_URL="$(aws lambda get-function-url-config --function-name "${FUNCTION_PREFIX}-batchStatus" --query FunctionUrl --output text)"
STATUS="$(curl -sS "${STATUS_URL}?batch_id=${BATCH_ID}" | jq -r '.status // "unknown"')"
[[ "${STATUS}" == "processed" ]] || fail "batch ${BATCH_ID} is '${STATUS}'; only a processed batch is handed to n8n"

WEBHOOK_URL="$(aws ssm get-parameter --name "${URL_PARAMETER}" --query Parameter.Value --output text)"
[[ "${WEBHOOK_URL}" =~ ^http://[0-9.]+:5678/webhook/[a-z-]+$ ]] || fail "unexpected webhook URL in ${URL_PARAMETER}"

REMOTE_SCRIPT="$(cat <<EOF
set -eu
export SIGNING_KEY="\$(aws ssm get-parameter --region ${AWS_REGION} --name ${SECRET_PARAMETER} --with-decryption --query Parameter.Value --output text)"
python3 -c '${MINT_TOKEN_PY}' '${BATCH_ID}' | curl -sS -o /dev/null -w 'webhook HTTP %{http_code}\n' --max-time 5 -H @- -H 'Content-Type: application/json' --data '{"batch_id":"${BATCH_ID}"}' '${WEBHOOK_URL}'
EOF
)"

COMMAND_ID="$(aws ssm send-command \
  --instance-ids "${INSTANCE_ID}" \
  --document-name AWS-RunShellScript \
  --comment "retrigger batch ${BATCH_ID}" \
  --parameters "$(jq -n --arg script "${REMOTE_SCRIPT}" '{commands: [$script]}')" \
  --query Command.CommandId --output text)"
echo "batch ${BATCH_ID} is processed; re-POSTing from ${INSTANCE_ID} (command ${COMMAND_ID})"

for _ in $(seq "${WAIT_ATTEMPTS}"); do
  RESULT="$(aws ssm get-command-invocation --command-id "${COMMAND_ID}" --instance-id "${INSTANCE_ID}" \
    --query '[Status, StandardOutputContent, StandardErrorContent]' --output json 2>/dev/null || echo '["Pending","",""]')"
  case "$(jq -r '.[0]' <<<"${RESULT}")" in
    Pending | InProgress | Delayed) sleep "${WAIT_SECONDS}" ;;
    *) break ;;
  esac
done

OUTPUT="$(jq -r '.[1] + .[2]' <<<"${RESULT}")"
echo "${OUTPUT}"
grep -qE '^webhook HTTP 2[0-9]{2}$' <<<"${OUTPUT}" || fail "n8n did not accept the re-POST"
echo "PASS: batch ${BATCH_ID} handed to n8n again"
