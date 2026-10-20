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
