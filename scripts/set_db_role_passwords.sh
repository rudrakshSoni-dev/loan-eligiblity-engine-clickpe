#!/usr/bin/env bash
set -euo pipefail

INSTANCE_ID="${N8N_INSTANCE_ID:-i-02ffa9d08e8403a4a}"
ROLES=(app_ingest app_n8n)
WAIT_ATTEMPTS=60
WAIT_SECONDS=2

export AWS_PROFILE="${AWS_PROFILE:-clickpe}"
export AWS_REGION="${AWS_REGION:-ap-southeast-2}"
export AWS_PAGER=""

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

SCRAM_VERIFIER_PY="import base64, hashlib, hmac, os, sys
password = sys.stdin.read().strip().encode()
salt, iterations = os.urandom(16), 4096
salted = hashlib.pbkdf2_hmac(\"sha256\", password, salt, iterations)
client_key = hmac.new(salted, b\"Client Key\", hashlib.sha256).digest()
server_key = hmac.new(salted, b\"Server Key\", hashlib.sha256).digest()
encode = lambda raw: base64.b64encode(raw).decode()
stored_key = hashlib.sha256(client_key).digest()
print(f\"SCRAM-SHA-256\${iterations}:{encode(salt)}\${encode(stored_key)}:{encode(server_key)}\")"

REMOTE_SCRIPT="$(cat <<REMOTE
set -eu
param() { aws ssm get-parameter --region ${AWS_REGION} --name "\$1" --with-decryption --query Parameter.Value --output text; }
HOST="\$(param /clickpe/db/host)"
export PGSSLMODE=verify-full PGSSLROOTCERT=/opt/clickpe/global-bundle.pem PGCONNECT_TIMEOUT=10
for ROLE in ${ROLES[*]}; do
  VERIFIER="\$(param /clickpe/db/\${ROLE}_password | python3 -c '${SCRAM_VERIFIER_PY}')"
  printf "ALTER ROLE %s PASSWORD '%s';\n" "\${ROLE}" "\${VERIFIER}" \
    | PGPASSWORD="\$(param /clickpe/db/password)" psql -h "\${HOST}" -U clickpe -d clickpe -v ON_ERROR_STOP=1 -X -q
  PGPASSWORD="\$(param /clickpe/db/\${ROLE}_password)" psql -h "\${HOST}" -U "\${ROLE}" -d clickpe -X -tA \
    -c "SELECT 'login ok', current_user, ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
done
REMOTE
)"

COMMAND_ID="$(aws ssm send-command \
  --instance-ids "${INSTANCE_ID}" \
  --document-name AWS-RunShellScript \
  --comment "set database role passwords" \
  --parameters "$(jq -n --arg script "${REMOTE_SCRIPT}" '{commands: [$script]}')" \
  --query Command.CommandId --output text)"

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
[[ "$(grep -c '^login ok|' <<<"${OUTPUT}")" -eq "${#ROLES[@]}" ]] || fail "not every role could log in"
echo "PASS: ${ROLES[*]} log in over verified TLS"
