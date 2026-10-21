#!/usr/bin/env bash
set -euo pipefail

INSTANCE_ID="${N8N_INSTANCE_ID:-i-02ffa9d08e8403a4a}"
WAIT_ATTEMPTS=60
WAIT_SECONDS=2

export AWS_PROFILE="${AWS_PROFILE:-clickpe}"
export AWS_REGION="${AWS_REGION:-ap-southeast-2}"
export AWS_PAGER=""

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

SQL="${1:-}"
[[ -n "${SQL}" ]] || fail "usage: $0 '<SQL>'"

SQL_B64="$(printf '%s' "${SQL}" | base64 -w0)"
REMOTE_SCRIPT="$(cat <<REMOTE
set -eu
HOST="\$(aws ssm get-parameter --region ${AWS_REGION} --name /clickpe/db/host --query Parameter.Value --output text)"
export PGPASSWORD="\$(aws ssm get-parameter --region ${AWS_REGION} --name /clickpe/db/password --with-decryption --query Parameter.Value --output text)"
export PGSSLMODE=verify-full PGSSLROOTCERT=/opt/clickpe/global-bundle.pem
echo '${SQL_B64}' | base64 -d | psql -h "\${HOST}" -U clickpe -d clickpe -v ON_ERROR_STOP=1 -X
REMOTE
)"

COMMAND_ID="$(aws ssm send-command \
  --instance-ids "${INSTANCE_ID}" \
  --document-name AWS-RunShellScript \
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

jq -r '.[1], .[2]' <<<"${RESULT}"
[[ "$(jq -r '.[0]' <<<"${RESULT}")" == "Success" ]] || fail "query did not succeed"
