# n8n on EC2 (T23)

Stack lives in `/opt/clickpe/n8n` on `i-02ffa9d08e8403a4a`. Files: `n8n/docker-compose.yml` (in repo) and `.env` (on the instance only, mode 600, root).

| Setting | Value | Why |
|---|---|---|
| Image | `docker.n8n.io/n8nio/n8n:2.44.4` | Exact tag, not `latest`/`stable`; 2.45.0 was only hours old, so the previous patch line was chosen |
| Encryption key | `N8N_ENCRYPTION_KEY` generated on the instance with `openssl rand -hex 32`, stored only in `.env` | Never typed, printed or committed; back it up before relying on stored credentials |
| `WEBHOOK_URL` | `http://172.31.26.164:5678/` | Lambda reaches n8n by private IP inside the VPC |
| `N8N_BLOCK_ENV_ACCESS_IN_NODE` | `true` | The container env holds the encryption key, so Code nodes must not read `$env`; non-secret config (`DRY_RUN`, `TEST_INBOX_ALIASES`, `MAX_EMAILS_PER_RUN`) comes from an `app_config` table row |
| `N8N_SECURE_COOKIE` | `false` | Editor is plain HTTP through the SSM tunnel on `localhost`; nothing else can reach it |
| `N8N_AWS_SYSTEM_CREDENTIALS_ACCESS_ENABLED` | `true` | Lets the AWS credential use the EC2 instance role (T24) |
| `NODE_EXTRA_CA_CERTS` | `/certs/rds-global-bundle.pem` (host `/opt/clickpe/global-bundle.pem`, mounted read-only) | n8n's Postgres credential has no CA field, so the container trusts the RDS CA instead; chain and hostname are verified (T24) |
| Hardening | public API, diagnostics, version notifications, personalization off; execution data pruned after 168 h | |
| Restart / health | `unless-stopped`; `wget /healthz` every 30 s | |
| Inbound | `clickpe-n8n-sg`: 5678 from the Lambda SG `sg-0ad4c9a31f3b8f7cc` only (rule `sgr-05583458c0968e07c`), no CIDR rules | Webhook callers only; editor is SSM-only |

## Start / update

```bash
export AWS_PROFILE=clickpe AWS_REGION=ap-southeast-2 AWS_PAGER=""
I=i-02ffa9d08e8403a4a
B64=$(base64 -w0 n8n/docker-compose.yml)
aws ssm send-command --instance-ids $I --document-name AWS-RunShellScript \
  --parameters "commands=[\"mkdir -p /opt/clickpe/n8n && cd /opt/clickpe/n8n && echo $B64 | base64 -d > docker-compose.yml\",\"test -f .env || printf 'N8N_ENCRYPTION_KEY=%s\\nN8N_PRIVATE_IP=172.31.26.164\\n' \\\"\$(openssl rand -hex 32)\\\" > .env\",\"chmod 600 .env && docker compose up -d\"]"
```

## Editor access (no inbound internet rule)

```bash
aws ssm start-session --target i-02ffa9d08e8403a4a --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["5678"],"localPortNumber":["5678"]}'
```

Then open `http://localhost:5678`. The first visit asks for the owner account; enable 2FA in Settings → Personal.

## Verification (2026-10-21)

```
docker compose ps                       n8n  docker.n8n.io/n8nio/n8n:2.44.4  Up 2 minutes (healthy)
.env                                    600 root
curl http://172.31.26.164:5678/healthz  200
SSM tunnel -> localhost:15678/          200   /healthz {"status":"ok"}
laptop -> 3.26.22.50:5678               timeout (curl exit 28, SG has no internet rule)
```

Webhook allowlist, with a throwaway probe workflow (`t23probe0001`, two Webhook nodes with the IP allowlist option set, then unpublished):

```
t23-allow  (allowlist 172.31.0.0/16)  POST from the instance via private IP -> 200
t23-deny   (allowlist 10.255.0.0/16)  same caller                           -> 403
t23-allow after unpublish                                                     -> 404
```

The probe workflow remains in the n8n database, inactive; delete it in the editor after the owner account exists.

## Batch-processed webhook (T19)

`load-chunk` POSTs `{"batch_id"}` with `X-Webhook-Secret` to `http://172.31.26.164:5678/webhook/match-batch`
(SSM `/clickpe/n8n/webhook_url`, resolved at deploy). Workflow B (`wfbmatching001`, T32) is published on
exactly this path and starts by moving the batch `processed → matching`, replying 409 when that UPDATE
claims nothing (replies: 202 / 400 / 409 / 500, see `docs/decisions.md` → "Workflow B entry").

Re-send a batch whose POST failed (n8n down, workflow not published):

```bash
scripts/retrigger_batch.sh <batch_id>
```

The script refuses unless `batchStatus` says `processed`, then runs `curl` on this instance through SSM Run
Command. The instance role reads `/clickpe/n8n/webhook_secret` and pipes the header to `curl -H @-`, so the
secret is not in the command parameters or SSM history.

Verification receiver used in T19 (`t19stubrecv1`, imported with the CLI, now unpublished): Webhook on
`match-batch` with the VPC CIDR allowlist → SHA-256 of the `X-Webhook-Secret` header → respond 200 if it
equals the hash of the SSM secret (computed on the instance), else 401.

```
right secret from the instance          -> 200 {"secret_ok":true}
wrong secret / no header                 -> 401 {"secret_ok":false}
127.0.0.1 (outside the allowlist)        -> 403
after unpublish + restart                -> 404
```

`t23probe0001` and `t19stubrecv1` stay in the n8n database, inactive; delete both in the editor once the
owner account exists. Their saved executions contain the request headers, including the secret; they are
pruned after 168 h.

Note: `/healthz` answers 200 before published webhooks are registered. Wait for
`Finished building workflow dependency index` in `docker logs n8n` after a restart before calling a webhook.

## Credentials (T24)

Created in the editor by name; workflows reference only these names. Screenshots with values masked are in `docs/screenshots/t24-*.png`.

| Name | Type | Settings | Test |
|---|---|---|---|
| `rds-postgres` | Postgres | RDS endpoint from SSM `/clickpe/db/host`, database and user `clickpe`, SSL Require, Ignore SSL Issues off | "Connection tested successfully" |
| `aws-ses-assume-role` | AWS (Assume Role) | `ap-southeast-2`, Use System Credentials on, role `clickpe-n8n-ses-role`, external ID `clickpe-n8n` (the form requires one; the trust policy does not check it) | "Connection tested successfully" |
| `webhook-secret` | Header Auth | `X-Webhook-Secret`, value from SSM `/clickpe/n8n/webhook_secret` | T32: wrong or missing secret → 403, right secret → 202 / 409 on `match-batch` |
| `groq-api` | Header Auth | `Authorization`, value `Bearer <key>` (the prefix is part of the value; T24 first saved the bare key, which Groq rejected with 401, fixed in T30) | `GET https://api.groq.com/openai/v1/models` → 200 from the instance; used by Workflow A |

SES role chain: instance role `clickpe-n8n-ec2-role` (inline policy `assume-n8n-ses-role`, `sts:AssumeRole` on one ARN) assumes `clickpe-n8n-ses-role` (trust: that instance role only; policy `ses-send-test-identities`: `ses:SendEmail` and `ses:SendRawEmail` on the three verified identities). Policy documents are in `infra/iam/`. From the instance, `aws sts assume-role` returned `assumed-role/clickpe-n8n-ses-role/t24check`. No static keys exist.

First attempt on `rds-postgres` failed with `self-signed certificate in certificate chain` (the RDS CA is not in Node's trust store); the fix was the `NODE_EXTRA_CA_CERTS` mount above, not the Ignore SSL Issues toggle.

## Importing and running a workflow (T28)

The public API is disabled, so workflows are imported with the n8n CLI inside the container through SSM
Run Command. `n8n execute` starts a second n8n process, so its task-broker and HTTP ports are moved
(otherwise it exits with "Task Broker's port 5679 is already in use"). Imports are keyed by the workflow
`id`, so importing the same file again overwrites the workflow. The run is saved as an execution with mode
`cli` and is visible in the editor's Executions list.

```bash
export AWS_PROFILE=clickpe AWS_REGION=ap-southeast-2 AWS_PAGER=""
I=i-02ffa9d08e8403a4a
B64=$(base64 -w0 n8n/workflows/workflow-a-product-discovery.json)
aws ssm send-command --instance-ids $I --document-name AWS-RunShellScript --timeout-seconds 300 \
  --parameters "commands=[\"echo $B64 | base64 -d > /tmp/wf.json && docker cp /tmp/wf.json n8n:/tmp/wf.json && docker exec n8n n8n import:workflow --input=/tmp/wf.json && docker exec -e N8N_RUNNERS_BROKER_PORT=5680 -e N8N_PORT=5681 n8n n8n execute --id=wfaproductdisc01 > /dev/null; rm -f /tmp/wf.json\"]"
```

`n8n execute` prints the whole run data to stdout and cuts it off inside the first multi-megabyte page,
so results are read from the saved execution in `database.sqlite` (read-only) instead.

## Publishing Workflow B (T32)

Same import as T28, then publish and restart (the CLI only flags the workflow; a running n8n registers its
webhook after a restart, and `/healthz` answers 200 before that):

```bash
B64=$(base64 -w0 n8n/workflows/workflow-b-matching.json)
aws ssm send-command --instance-ids $I --document-name AWS-RunShellScript --timeout-seconds 300 \
  --parameters "commands=[\"echo $B64 | base64 -d > /tmp/wfb.json && docker cp /tmp/wfb.json n8n:/tmp/wfb.json && docker exec n8n n8n import:workflow --input=/tmp/wfb.json && docker exec n8n n8n publish:workflow --id=wfbmatching001; rm -f /tmp/wfb.json; cd /opt/clickpe/n8n && docker compose restart n8n\"]"
docker exec n8n n8n list:workflow --active=true      # B · Matching must be listed
```

The throwaway workflow `t32faildrill01` (forced database error, path `t32-fail-drill`) was unpublished and
answers 404; like `t23probe0001`, `t19stubrecv1` and `scratchprobe0001` it stays inactive in the n8n
database until the owner account exists to delete it in the editor.

## Stage 1 drill (T33)

`t33faildrill01` is a copy of Workflow B on path `t33-fail-drill` whose Stage 1 query is `SELECT 1/0`. It was
published, called once from the instance (claim 202, Stage 1 retried 3 times in 4,047 ms, batch set `failed`),
then unpublished with `docker exec n8n n8n unpublish:workflow --id=t33faildrill01` and a restart; the path then
answers 404. Like the earlier probes it stays inactive in the n8n database until it is deleted in the editor.

## Stage 2 drill (T34)

`t34faildrill01` is a copy of Workflow B on path `t34-fail-drill` whose `Stage 2 · Classify pairs` query is
`SELECT 1/0`. It was published, called once from the instance with a throwaway empty batch in `processed`
(202, batch `failed` with `matching stage 2 failed: division by zero`), then unpublished with a restart; the path
answers 404. The throwaway batch and its run row were deleted. Like the earlier probes the workflow stays
inactive in the n8n database until it is deleted in the editor.

## Stage 3 (T35)

Migration `0004_stage3_cohorts` was applied with `infra/ec2/migrate.sh` (the `db/` files shipped as a tarball
through SSM Run Command; password read from SSM on the instance; file SHA-256 `1a879933…4fb0` identical on both
sides). Workflow B was re-imported and published as in T32. Stage 3 calls Groq with the existing `groq-api`
credential; no new credential.

`t35drill000001` is a copy of Workflow B on path `t35-drill`, imported twice with the same id: first with a
1-token budget and `verdict_version` `drill` (every cohort `unresolved_budget`, 0 calls), then with
`Stage 3 · Store verdicts + fan out` replaced by `SELECT 1/0` (batch `failed`). It was then unpublished with a
restart; the path answers 404. Like the earlier drills it stays inactive in the n8n database until it is deleted
in the editor.

Reading a saved execution's per-node timings (read-only, on the instance): open
`/var/lib/docker/volumes/n8n_n8n_data/_data/database.sqlite` with `mode=ro`, take `execution_data.data` for the
execution id and decode it with the `flatted` format (every string and nested object is an index into the
top-level array); `resultData.runData[node][i]` holds `startTime`, `executionTime` and the output items.


## Persist step (T36)

Migration `0005_final_matches` was applied with `infra/ec2/migrate.sh` (file SHA-256 `de22a2e7…3090` identical on both sides). Workflow B was re-imported and published as in T32, but the file is now over SSM's 97 KB parameter limit, so it is sent gzipped: `gzip -9c n8n/workflows/workflow-b-matching.json | base64 -w0` and `base64 -d | gunzip` on the instance (remote file SHA-256 `847db5fc…4e24` equals the local one).

To run the funnel again on a batch that is already `matched`, set it back to `processed` and call `scripts/retrigger_batch.sh <batch_id>`; the claim step then creates a new `pipeline_runs` row.
