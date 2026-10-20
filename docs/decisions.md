# Design decisions

One section per decision: what was chosen, what was rejected, and why.
Every claim is labelled by where it comes from:
**cited** (linked primary source, mostly AWS / n8n / Groq / PostgreSQL docs),
**measured** (this project: commands recorded in `PROGRESS.md`, or the T07 research probes of 2026-10-20),
or **estimate** (arithmetic or judgement that the build must confirm). No estimate is quoted in the
README as a result.

The research behind the 2026-10-20 revision (four parallel investigations: ingestion,
network/security, database, n8n/LLM) is summarised here; the cited sources are linked inline.

## Index

1. [Region: ap-southeast-2](#region-ap-southeast-2)
2. [Runtime: Python 3.12 on arm64 Lambdas](#runtime-python-312-on-arm64-lambdas)
3. [Upload: presigned S3 POST](#upload-presigned-s3-post)
4. [Ingestion fan-out: S3 → split-csv → SQS → load-chunk](#ingestion-fan-out-s3--split-csv--sqs--load-chunk)
5. [Concurrency cap: SQS MaximumConcurrency, not reserved concurrency](#concurrency-cap-sqs-maximumconcurrency-not-reserved-concurrency)
6. [Chunking: exact record byte offsets](#chunking-exact-record-byte-offsets)
7. [Idempotency and the completion signal: a chunk ledger](#idempotency-and-the-completion-signal-a-chunk-ledger)
8. [Database: RDS PostgreSQL 16 on db.t4g.micro](#database-rds-postgresql-16-on-dbt4gmicro)
9. [Driver and load pattern: pg8000, COPY, deduplicating upsert](#driver-and-load-pattern-pg8000-copy-deduplicating-upsert)
10. [Network: no NAT Gateway](#network-no-nat-gateway)
11. [n8n hosting and editor access](#n8n-hosting-and-editor-access)
12. [Webhook security: four layers](#webhook-security-four-layers)
13. [Browser endpoints: Lambda Function URLs](#browser-endpoints-lambda-function-urls)
14. [Secrets: SSM SecureString resolved at deploy](#secrets-ssm-securestring-resolved-at-deploy)
15. [IAM and the SES credential](#iam-and-the-ses-credential)
16. [Data findings that shape the design](#data-findings-that-shape-the-design)
17. [LLM provider: Groq](#llm-provider-groq)
18. [Matching and the Optimization Treasure Hunt](#matching-and-the-optimization-treasure-hunt)
19. [Crawl targets](#crawl-targets)
20. [Infrastructure as code: Serverless Framework v3](#infrastructure-as-code-serverless-framework-v3)
21. [Row validation: strict on meaning, lenient on format](#row-validation-strict-on-meaning-lenient-on-format)

---

## Region: ap-southeast-2

**Choice.** Everything is deployed to `ap-southeast-2` (Sydney). The region is a single value in
`serverless.yml` and the CLI profile.

**Rejected.** `ap-south-1` (Mumbai), the natural region for an Indian lending product.

**Why (measured).** The demo account was created through the AWS Projects console, which attaches
SCP `p-veigobeu` and locks the account to one region. Creating an SES identity in `ap-south-1`
failed with an explicit SCP deny; EC2, Lambda, RDS, SQS and SES were denied in `ap-south-1` and
`us-east-1` and allowed only in `ap-southeast-2` (`PROGRESS.md` → T03). Every service this design
needs is available in Sydney, and one region avoids cross-region transfer and SES/Lambda mismatches.

**Production.** `ap-south-1`, for latency to Indian users and to keep borrower data in India in line
with RBI data-localisation expectations. Moving is a config change plus a redeploy.

## Runtime: Python 3.12 on arm64 Lambdas

**Choice.** All Lambdas run `python3.12` on `arm64` (Graviton).

**Rejected.** Node.js; Python on `x86_64`.

**Why.** Python gives boto3, the `csv` module and simple typed code for validation and bulk loading.
Lambda bills arm64 at a lower price per GB-second than x86_64
([AWS Lambda pricing](https://aws.amazon.com/lambda/pricing/)). No dependency needs a native build
(see the driver section), so arm64 costs nothing in packaging effort.

## Upload: presigned S3 POST

**Choice.** The browser asks `get-upload-url` for a presigned **POST** (`generate_presigned_post`)
and sends the file as `multipart/form-data` straight to S3. The signed policy pins the exact key
`uploads/{batch_id}.csv`, `Content-Type: text/csv`, `content-length-range` 1 B–20 MB, and a
5-minute expiry. `split-csv` re-checks `object.size` from the S3 event as a second guard.

**Rejected.**
- *Presigned PUT* (the original plan). It signs the Content-Type, but no AWS page documents S3
  enforcing a size limit on it, so "content-length limit" could not honestly be claimed
  ([S3 presigned upload](https://docs.aws.amazon.com/AmazonS3/latest/userguide/PresignedUrlUploadObject.html);
  [POST policy](https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-HTTPPOSTConstructPolicy.html)).
- *Body upload through API Gateway or a Function URL.* API Gateway caps payloads at 10 MB and Lambda
  synchronous invocations at 6 MB ([Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)).
  The 10,000-row sample is 993,191 bytes (measured), so the 100k benchmark file (~10 MB, estimate)
  would not fit.

**Regional endpoint (measured in T15).** `generate_presigned_post` returns the global
`https://<bucket>.s3.amazonaws.com/` unless the client has an `endpoint_url`. A POST to that host
for the Sydney test bucket returned `HTTP 307` to `<bucket>.s3-ap-southeast-2.amazonaws.com`. A
browser will not follow a redirect on a cross-origin form post, so `new_s3_client` pins
`https://s3.<region>.amazonaws.com` with SigV4 and virtual-hosted addressing.

**Verified in T15.** Against a real S3 bucket with the handler's output and `curl -F`: a valid file
returned `204`; a 22,020,096-byte file returned `400 EntityTooLarge` (`MaxSizeAllowed 20971520`);
a wrong `Content-Type` and a changed `key` each returned `403` with the failed policy condition.
Evidence in `PROGRESS.md` T15.

## Ingestion fan-out: S3 → split-csv → SQS → load-chunk

**Choice.** S3 `ObjectCreated` triggers `split-csv` (outside the VPC), which validates the header and
sends one SQS message per 5,000-row chunk. `load-chunk` (inside the VPC) consumes `ingest-queue`
with batch size 1 and `ReportBatchItemFailures`, reads only its byte range, validates, COPYs and
upserts. After 5 receives a message moves to `ingest-dlq`; a CloudWatch alarm fires on DLQ depth.

**Why.**
- **Retry isolation.** A failing chunk is retried alone; committed chunks are untouched.
- **Poison isolation.** A chunk that keeps failing goes to the DLQ and the batch is marked `failed`
  with the chunk number, instead of retrying forever.
- **No size ceiling from one invocation's 15-minute timeout**, and parallelism that scales with file size.
- **No VPC Lambda ever calls an AWS API** except S3 through the free gateway endpoint, which keeps
  the no-NAT design simple (see Network).

**Honest caveat (estimate).** At 10k–100k rows (≤ ~10 MB) one Lambda would finish well inside
900 s. The case for fan-out is per-chunk retry and horizontal scale, not need at this size; the
T37 benchmark carries the scale argument with measured numbers.

**DLQ settings (cited).** AWS recommends a visibility timeout of at least 6× the function timeout
and `maxReceiveCount` of at least 5, because throttled invocations also raise the receive count
([SQS event source config](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-configure.html)).
The original plan's `maxReceiveCount` of 3 could have sent healthy chunks to the DLQ under throttling.

**Runner-up: Step Functions Standard with an Inline Map.** S3 → EventBridge → state machine:
plan chunks → Map (`MaxConcurrency` 3) over `load-chunk` → one finalize step. Its strengths are real:
a structurally single finalize step, redrive that reruns only failed iterations
([redrive](https://docs.aws.amazon.com/step-functions/latest/dg/redrive-executions.html)), a console
execution graph that films well, and every Lambda could sit in the VPC. Inline Map supports up to
40 concurrent iterations and 25,000 history events
([Inline Map](https://docs.aws.amazon.com/step-functions/latest/dg/state-map-inline.html)); the free
tier is 4,000 transitions a month with no expiry ([pricing](https://aws.amazon.com/step-functions/pricing/)).
It was not chosen because it adds a second orchestration language (ASL written as raw CloudFormation;
the `serverless-step-functions` plugin does not document Serverless v4 support), an EventBridge
configuration and new failure modes, for no correctness gain over SQS + a Postgres ledger.
**Would switch if** the SQS path already passes the T22 smoke test with 3–4 spare hours before the
README, purely for the video.

**Rejected: Step Functions Distributed Map with the CSV ItemReader.** It pads short rows with empty
strings, drops extra fields and treats every field as a string
([ItemReader](https://docs.aws.amazon.com/step-functions/latest/dg/input-output-itemreader.html)).
That silently repairs malformed rows and destroys the per-line reject report.

**Time-crunch fallback.** If `split-csv` (T17, P1) is cut, `load-chunk` is triggered by S3 directly
and loads the file in chunked transactions; the README then calls the SQS fan-out "designed, not
implemented".

## Concurrency cap: SQS MaximumConcurrency, not reserved concurrency

**Choice.** No reserved concurrency anywhere. The `load-chunk` event source mapping sets
`ScalingConfig.MaximumConcurrency: 3`.

**Why.**
- **Measured:** `aws lambda get-account-settings` → `ConcurrentExecutions: 10`,
  `UnreservedConcurrentExecutions: 10`. New accounts start with reduced quotas
  ([Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)).
- **Cited:** reserved concurrency can be set only up to "unreserved account concurrency minus 100"
  ([concurrency](https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html)), so on
  this account it cannot be set at all. The SQS mapping accepts `MaximumConcurrency` between 2 and
  1,000 at no cost, and stops polling once the cap is reached instead of throttling
  ([SQS scaling](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-scaling.html)).
- **Why 3 (estimate):** it leaves room in the 10-unit pool for `split-csv`, `get-upload-url` and
  `batch-status`, and bounds RDS connections from loaders to 3, far below `max_connections` on a
  `db.t4g.micro` (recorded in T11).

## Chunking: exact record byte offsets

**Choice.** `split-csv` streams the file once with a quote-aware CSV scan and records the exact byte
offsets of record boundaries. Each message carries
`{batch_id, s3_key, chunk_no, total_chunks, start_byte, end_byte, first_line_no, row_count, columns}`,
where `columns` is the header in file order (a byte-range chunk has no header row; added in T16).
`load-chunk` issues `Range: bytes=start-end` and receives whole records, so line numbers in the reject
report are exact.

**Rejected.** "Guess a range, then realign to the next newline." It breaks on quoted fields that
contain newlines, which CSV allows
([ItemReader CSV rules](https://docs.aws.amazon.com/step-functions/latest/dg/input-output-itemreader.html)).
The scan also handles a UTF-8 BOM, CRLF, a trailing empty line and multi-byte characters at a
boundary. This is an engineering choice, not a cited AWS pattern.

**`split-csv` never touches RDS.** It runs outside the VPC (it must send to SQS without an
endpoint), so `total_chunks`, the `pending → loading` transition, and any header/size error travel in
the messages and are applied by `load-chunk`. A bad header or oversize file produces one
`{batch_id, error}` control message instead of chunks.

## Idempotency and the completion signal: a chunk ledger

**Choice.** All idempotency lives in Postgres, because every hop is at-least-once: S3 notifications
([S3 events](https://docs.aws.amazon.com/AmazonS3/latest/userguide/EventNotifications.html)), async
Lambda invocations ([async](https://docs.aws.amazon.com/lambda/latest/dg/invocation-async-error-handling.html))
and SQS ([Lambda + SQS](https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html)).

Each `load-chunk` invocation runs one transaction:
1. `INSERT INTO chunk_loads (batch_id, chunk_no, …) ON CONFLICT DO NOTHING RETURNING 1` — no row
   means a redelivery: acknowledge and exit.
2. COPY into a `TEMP … ON COMMIT DROP` staging table, validate, upsert into `users`, record rejects,
   update the display counters on `upload_batches`.
3. Commit.

After commit, the caller that gets a row back from
`UPDATE upload_batches SET status = 'processed' WHERE id = $1 AND status = 'loading' AND
(SELECT count(*) FROM chunk_loads WHERE batch_id = $1) = total_chunks RETURNING id`
is the only one that POSTs to n8n. If that POST fails, the batch stays `processed` and a documented
retrigger script re-POSTs it (T19).

Because chunking is deterministic, a duplicate S3 event produces the same `chunk_no` values, which the
ledger ignores, so `split-csv` needs no database claim step of its own.

**Rejected: a bare `chunks_done = chunks_done + 1` counter** (the original plan). If a transaction
commits but the SQS delete fails, the redelivered message increments the counter again: two
invocations can both see "complete", or the counter overshoots `total_chunks` and n8n is never
triggered. The ledger makes the redelivery a no-op; the row lock on the conditional UPDATE
serialises concurrent finishers.

**Rejected: n8n polling for finished batches.** Adds latency and a schedule for no benefit.

## Database: RDS PostgreSQL 16 on db.t4g.micro

**Choice.** RDS for PostgreSQL 16, `db.t4g.micro`, single-AZ, 20 GB gp3, not publicly accessible,
1-day backups, deletion protection, default parameter group.

**Why.** The Free plan names `db.t4g.micro` for RDS PostgreSQL ([RDS free](https://aws.amazon.com/rds/free/)).
Matching is set-based SQL (users ⋈ products on ranges), which PostgreSQL does natively and n8n's
Postgres node speaks directly. `rds.force_ssl` already defaults to 1 on PostgreSQL 15+, so no custom
parameter group is needed ([RDS SSL](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html));
T11 proves it with a rejected `sslmode=disable` connection.

**Rejected.**
- *Aurora Serverless v2.* It can pause at 0 ACU, but not while any user connection is open
  ([auto-pause](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2-auto-pause.html)),
  and n8n's connection pool keeps one open, so it would bill continuously.
- *Aurora DSQL.* No temporary tables and a 3,000-row-per-transaction limit
  ([unsupported features](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-postgresql-compatibility-unsupported-features.html)),
  which breaks the 5,000-row staging transaction.
- *RDS Data API* (to keep Lambdas out of the VPC). Aurora only, and not supported on T instance classes
  ([Data API limits](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/data-api.limitations.html)).
- *DynamoDB.* No set-based joins for Stage 1 matching.
- *RDS Proxy.* Billed per vCPU-hour ([pricing](https://aws.amazon.com/rds/proxy/pricing/)); unnecessary
  with at most 3 loaders plus n8n's pool. Named as the production upgrade for high fan-out.

**Connections (cited + estimate).** Default `max_connections` is
`LEAST(DBInstanceClassMemory/9531392, 5000)` ([RDS limits](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_Limits.html));
for 1 GiB that is at most ~112 before OS reservations. The real value is recorded in T11 with
`SHOW max_connections`.

## Driver and load pattern: pg8000, COPY, deduplicating upsert

**Choice.** `pg8000` with a verifying TLS context, and per chunk:
TEMP staging → `COPY FROM STDIN` →
`INSERT INTO users SELECT DISTINCT ON (user_id) … ORDER BY user_id, line_no DESC
ON CONFLICT (user_id) DO UPDATE SET … WHERE users.* IS DISTINCT FROM EXCLUDED.*`.

**Why pg8000 (cited + measured).** It is pure Python and supports
`con.run("COPY … FROM STDIN WITH (FORMAT CSV)", stream=…)` ([pg8000](https://pypi.org/project/pg8000/)).
The development machine is `x86_64` (measured, `uname -m`) and the Lambdas are arm64, so a pure-Python
driver packages with no cross-build.

**Rejected: psycopg 3 / psycopg2-binary.** They do publish aarch64 wheels, so "needs a native build" is
not the reason. The reason is packaging risk: building from x86_64 needs pip `--platform` flags or
Docker, and psycopg calls its binary wheels "best effort", preferring a local build for production
([psycopg install](https://www.psycopg.org/psycopg3/docs/basic/install.html)). No pg8000-vs-psycopg
COPY benchmark was found, so any speed difference is unmeasured.

**TLS.** pg8000's `ssl_context=True` encrypts "with the minimum of checks" ([pg8000](https://pypi.org/project/pg8000/)).
The Lambda package ships the RDS global CA bundle and connects with
`ssl.create_default_context(cafile=…)`, which verifies the certificate and hostname.

**Why the upsert has two extra clauses (cited).** `ON CONFLICT DO UPDATE` raises a cardinality
violation if two proposed rows share the conflict key
([INSERT](https://www.postgresql.org/docs/16/sql-insert.html)), so `DISTINCT ON (user_id)` is required
for a chunk that repeats an ID. `IS DISTINCT FROM` makes re-uploading an identical CSV update zero rows,
which is visible idempotency evidence for T43.

**Rejected: `executemany`.** In a third-party laptop benchmark on 32.5k rows, `executemany` took
124.7 s against 0.46 s for COPY ([benchmark](https://hakibenita.com/fast-load-data-python-postgresql)).
Those figures are not RDS throughput; T37 measures that.

## Network: no NAT Gateway

**Choice.** No NAT Gateway and no paid interface endpoints.

| Component | In VPC? | Talks to | How |
|---|---|---|---|
| `get-upload-url` | Yes | RDS (create `pending` batch), S3 presign | RDS on private IP; presigning is local signing, no network call |
| `split-csv` | No | S3 (read), SQS (send) | Public AWS endpoints; never touches RDS |
| `load-chunk` | Yes | S3 (ranged GET), RDS, n8n | Free S3 Gateway Endpoint; RDS and n8n on private IPs; SQS messages are delivered by the Lambda service, so no SQS endpoint |
| `batch-status` | Yes | RDS | Private IP |
| n8n (EC2) | Public subnet | RDS, Groq, crawl sites, SES, SSM | RDS on private IP; everything else outbound through the free Internet Gateway |

Security groups reference each other, not CIDRs: `sg-rds` allows 5432 from `sg-lambda` and `sg-n8n`;
`sg-n8n` allows 5678 from `sg-lambda` only; `sg-lambda` has egress only.

**Why (cited).** A VPC Lambda reaches only VPC resources, and a public subnet does not give it internet
access; the S3 Gateway endpoint has no charge
([Lambda VPC internet](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc-internet.html)).
With an SQS event source mapping, the Lambda service polls the queue and invokes the function
([Lambda + SQS](https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html)). A NAT Gateway and each
interface endpoint bill per hour plus per GB ([VPC pricing](https://aws.amazon.com/vpc/pricing/)),
which would be the largest line in a demo bill. Function URLs work for in-VPC Lambdas because
invocation comes through the Lambda service, not the VPC.

**Known cost (cited + estimate).** The EC2 public IPv4 address costs $0.005/hour whether in use or
idle ([VPC pricing](https://aws.amazon.com/vpc/pricing/)), about $0.36 over 72 hours, drawn from Free
plan credits.

## n8n hosting and editor access

**Choice.** n8n with Docker Compose on one EC2 `t4g.small` (2 GB, Amazon Linux 2023 arm64) plus a
1–2 GB swap file, in a public subnet of the default VPC. The image is pinned to an exact 2.x tag.
The editor is reached **only** through an SSM Session Manager port forward to `localhost:5678`; the
security group has **no inbound rules from the internet**. n8n user management with an owner account
and 2FA; SQLite on a persistent `.n8n` volume; fixed `N8N_ENCRYPTION_KEY`;
`N8N_PUBLIC_API_DISABLED=true`, `N8N_DIAGNOSTICS_ENABLED=false`, execution pruning on.

**Why (cited).**
- Session Manager needs only outbound 443 to the SSM endpoints and the
  `AmazonSSMManagedInstanceCore` policy, with no inbound port
  ([prerequisites](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-prerequisites.html)).
  The instance reaches those endpoints through the Internet Gateway, so no paid endpoint is needed.
- n8n 1.0 made user management mandatory and removed basic auth
  ([1.0 migration](https://docs.n8n.io/1-0-migration-checklist/)), so the original "basic auth" item
  was obsolete.
- `N8N_SECURE_COOKIE` defaults to true ([security env vars](https://docs.n8n.io/hosting/configuration/environment-variables/security/));
  the tunnel serves the editor on `http://localhost`, which browsers treat as a secure context, so the
  cookie setting can stay on (estimate, verified in T23).
- n8n 2.0 runs Code nodes in task runners, removes the Start node, replaces activation with Publish,
  and renames Docker tags to `stable`/`beta`, which is why an exact tag is pinned
  ([2.0 breaking changes](https://docs.n8n.io/2-0-breaking-changes/)). The same page says
  `N8N_BLOCK_ENV_ACCESS_IN_NODE` now defaults to true while the security page still says false, so
  compose sets it explicitly.
- n8n publishes no official RAM minimum ([memory errors](https://docs.n8n.io/hosting/scaling/memory-errors/));
  the README reports a measured `docker stats` reading instead of a vendor figure.

**Rejected.**
- *IP-allowlisted 22/5678* (the original plan). Exposes two ports and breaks when the home IP changes.
  Kept only as the fallback if SSM fails.
- *n8n in a private subnet.* Needs NAT to reach Groq, the crawl sites and SES.
- *ECS Fargate.* n8n's state would need EFS or an external database; no scaling benefit at this size.
- *n8n Cloud.* Cannot reach a private RDS.
- *Caddy + sslip.io + Let's Encrypt, Cloudflare Tunnel, Tailscale.* Only needed if the editor must be
  public; a third party for no gain here.

**Fallback (only with explicit approval, if EC2 fails).** Local n8n + public RDS with
`rds.force_ssl=1` + Cloudflare Tunnel, documented as a weaker trade-off.

## Webhook security: four layers

**Choice.** `load-chunk` calls `http://<n8n-private-ip>:5678/webhook/...`, protected by:
1. **Security group:** 5678 only from `sg-lambda`.
2. **Webhook IP allowlist:** the VPC CIDR; anything else gets 403.
3. **Header Auth credential:** `X-Webhook-Secret`.
4. **Idempotent Workflow B:** refuses to run unless the batch is in `processed`, which neutralises replays.

**Why (cited).** The Webhook node supports Basic, Header and JWT auth plus an IP allowlist; HMAC
verification is not built in ([Webhook node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/)).

**Rejected for the build.** An HMAC-signed body with a timestamp (custom Raw Body + Code node) or JWT
with `exp`. They matter for internet-facing webhooks; this one never leaves the VPC. Both are listed
as upgrades.

## Browser endpoints: Lambda Function URLs

**Choice.** Function URLs for `get-upload-url` and `batch-status`, `AuthType NONE`, CORS restricted
to the UI origin, and a resource policy with the `lambda:InvokedViaFunctionUrl` condition.

**Why (cited).** No separate charge and no extra resources. Since October 2025, new Function URLs need
both `lambda:InvokeFunctionUrl` and `lambda:InvokeFunction` in the resource policy
([Function URL auth](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html)).

**Stated honestly.** With `AuthType NONE`, anyone with the URL can invoke the function, and CORS is
not access control. Mitigations: the signed size/type/key policy on uploads, 5-minute expiry, uploads
lifecycle-deleted after 7 days, SES sandbox plus the recipient guard (abuse cannot spam), the small
account concurrency limiting blast radius, and the budget alarm.

**Rejected for now.** API Gateway HTTP API with a JWT authorizer and throttling (about $1 per million
requests, [pricing](https://aws.amazon.com/api-gateway/pricing/)) — the named production upgrade.

## Secrets: SSM SecureString resolved at deploy

**Choice.** Database password, webhook secret and similar values are SSM Parameter Store
`SecureString` parameters, injected into Lambda environment variables by `serverless.yml`
(`${ssm:/…}`) at deploy time. n8n keeps its own credentials in its encrypted store
(`N8N_ENCRYPTION_KEY`). Locally they live in a gitignored `.env`.

**Rejected.** Secrets Manager with runtime lookups. From inside a no-NAT VPC a runtime lookup needs a
paid interface endpoint, and Secrets Manager costs $0.40 per secret per month plus $0.05 per 10,000
calls ([pricing](https://aws.amazon.com/secrets-manager/pricing/)).

**Trade-off stated openly (cited).** Lambda encrypts environment variables at rest with KMS, but AWS
recommends Secrets Manager over environment variables for database credentials
([env var encryption](https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars-encryption.html)).
Anyone with `lambda:GetFunctionConfiguration` (and decrypt) can read the values, and rotation needs a
redeploy. Secrets Manager with rotation is the production option.

**Second copy (measured, T10 review).** `${ssm:…}` is resolved by the framework, so the packaged
CloudFormation template holds the SecureString values as literals (48- and 64-character strings in
`.serverless/cloudformation-template-update-stack.json`). That copy is gitignored locally. After a deploy it
also sits in the deployment bucket (SSE, TLS-only policy) and in the stack's template, which anyone
with `cloudformation:GetTemplate` can read. The same production fix applies: Secrets Manager, with the
function reading the secret at runtime.

## IAM and the SES credential

**Choice.** One role per Lambda, scoped to specific ARNs:

| Function | Permissions beyond logs |
|---|---|
| `get-upload-url` | `s3:PutObject` on `uploads/*`; VPC ENI permissions |
| `split-csv` | `s3:GetObject` on `uploads/*`; `sqs:SendMessage` on `ingest-queue` and `split-failures` (async on-failure destination) |
| `load-chunk` | `s3:GetObject` on `uploads/*`; SQS receive/delete/get-attributes on `ingest-queue`; VPC ENI permissions |
| `batch-status` | VPC ENI permissions |

Roles are plain CloudFormation in `serverless.yml`, not the framework's shared role, so each function
gets only its own row. Log permissions cover only the function's own log group (`CreateLogStream`,
`PutLogEvents`; the group itself is created by the stack). The one `Resource: "*"` statement is the
three ENI actions every VPC-attached Lambda needs (`ec2:CreateNetworkInterface`,
`DescribeNetworkInterfaces`, `DeleteNetworkInterface`). Describe actions cannot be scoped to a resource,
and AWS's own `AWSLambdaVPCAccessExecutionRole` uses `*` for all three
([Lambda VPC permissions](https://docs.aws.amazon.com/lambda/latest/dg/configuring-vpc.html#configuring-vpc-permissions)).
The inline version still drops that managed policy's `logs:*`-on-`*` grant. `split-csv` runs outside
the VPC and has no EC2 permissions.

For n8n → SES, the first choice is the EC2 instance role: n8n's **AWS (Assume Role)** credential with
"Use System Credentials" (`N8N_AWS_SYSTEM_CREDENTIALS_ACCESS_ENABLED=true`) assumes one SES-only role,
so no long-lived keys exist on the box. n8n's plain AWS (IAM) credential accepts only static keys, and
n8n advises system credentials only on single-tenant instances, which this is
([n8n AWS credentials](https://docs.n8n.io/integrations/builtin/credentials/aws/)).

**Fallback.** An IAM user limited to `ses:SendEmail`/`ses:SendRawEmail` on the verified identity
ARNs, used if the SES node does not accept the Assume Role credential type (unverified; tested first
thing in T24).

**SES itself (cited + measured).** It stays in the sandbox on purpose: only verified identities can
receive, 200 messages per 24 h, 1 per second
([production access](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html);
`aws sesv2 get-account` in T03). It is an AWS-enforced second barrier behind the n8n recipient guard
(T38), so a bug in one still cannot mail the sample CSV's addresses.

## Data findings that shape the design

From the sample `users.csv` (full profile in [`data-notes.md`](data-notes.md), T01; all measured):

- **10,000 rows, 7 columns, zero malformed or empty values.** Validation is still required for
  future uploads, so reject paths are tested with synthetic fixtures in `tests/fixtures/`.
- **`user_id` is a unique UUID; `email` is not unique** (2,632 distinct emails, each shared by 2–5
  users). The upsert key is `user_id`, and notifications are grouped by `user_id`, never by email.
- **Ranges:** income 25,000–150,000 (multiples of 1,000), credit score 650–800 (multiples of 5), age
  22–50. CHECK constraints are deliberately wider (e.g. score 300–900, age 18–100) so valid future
  data is not rejected by the database; tighter business rules live in code.
- **Employment has exactly 3 values** (`Salaried`, `Self-Employed`, `Business`).
- **Users are nearly all distinct:** 9,869 distinct (income, score, age, employment) tuples across
  10,000 users (T07 research analysis). Deduplicating identical users saves only ~1.3%, so cohorting
  by raw values cannot rescue a per-pair LLM design (see Treasure Hunt).

---

## LLM provider: Groq

**Choice.** Groq's OpenAI-compatible API, called from n8n through one reusable "LLM Gateway"
sub-workflow using an HTTP Request node with **strict JSON-schema Structured Outputs**,
`temperature: 0`, `reasoning_effort: "low"` and `include_reasoning: false`.

**Rejected.**
- *Calling the LLM per (user, product) pair.* The limits below make it impossible.
- *JSON Object Mode* (the original plan). It guarantees only valid JSON syntax and "can occasionally
  error"; strict Structured Outputs guarantee the schema and are supported on both gpt-oss models
  ([structured outputs](https://console.groq.com/docs/structured-outputs)). The Code-node validation
  stays for unit coercion and defence in depth.
- *n8n's Groq Chat Model node as the main path.* It exposes only model, max tokens and temperature,
  with no response format ([node docs](https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.lmchatgroq/)).
- *The n8n AI Agent node.* Non-deterministic tool loops with unbounded calls, the opposite of what a
  1,000-request daily budget needs.

### Models available to this key (measured 2026-10-20)

`GET /openai/v1/models` returned these chat-capable models:
`openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b` (all 131,072-token context),
plus `allam-2-7b` (4,096 context). No Llama chat models are offered to this account.

### Chosen models

| Use | Model | Why |
|---|---|---|
| Workflow A structuring, Workflow B cohort judgment | `openai/gpt-oss-120b` | Largest model available; same rate limits as the 20b model, so there is no throughput reason to pick the smaller one. |
| Fallback on 429 / outage | `openai/gpt-oss-20b` | Groq limits are per model, so falling back gives a second, independent quota. |

### Free-tier limits (organization level, measured 2026-10-20)

Source: console.groq.com → Settings → Limits (screenshot by the user), cross-checked against the
`x-ratelimit-limit-*` response headers of a real request.

| Model | Requests/min | Requests/day | Tokens/min | Tokens/day |
|---|---|---|---|---|
| openai/gpt-oss-120b | 30 | 1,000 | 8,000 | 200,000 |
| openai/gpt-oss-20b | 30 | 1,000 | 8,000 | 200,000 |
| qwen/qwen3.8-27b | 30 | 1,000 | 8,000 | 200,000 |

Header check on `openai/gpt-oss-120b`: `x-ratelimit-limit-requests: 1000` (per day) and
`x-ratelimit-limit-tokens: 8000` (per minute), matching the console. Groq documents that
`retry-after` is sent only on a 429 ([rate limits](https://console.groq.com/docs/rate-limits)).

### Verification request and token cost (measured)

Same prompt (extract income and rate range from one sentence of loan text) on 2026-10-20:

| Model | `reasoning_effort` | HTTP | Latency | Prompt tok | Completion tok | Output |
|---|---|---|---|---|---|---|
| gpt-oss-120b | default | 200 | 0.71 s | 154 | 153 | `{"min_monthly_income":25000,"interest_rate_min":10.5,"interest_rate_max":24}` |
| gpt-oss-20b | default | 200 | 0.74 s | 154 | 191 | same JSON |
| gpt-oss-120b | low | 200 | 0.64 s | 154 | 79 | same JSON |

gpt-oss models spend completion tokens on hidden reasoning, so the JSON itself is a small part of
what is billed. `reasoning_effort: "low"` halved completion tokens here with identical output, so it
is the gateway default. Whether hidden reasoning tokens count toward the per-minute token limit is
undocumented; the `llm_calls` table records `usage` from every response to settle it.

### What the limits mean for the design

- **Tokens bind, not requests.** 8,000 tokens ÷ 30 requests ≈ 267 tokens per call is the crossover.
  Real requests (product text, several cohorts per request) of 1.5–3K tokens allow roughly 3–5
  requests a minute and 70–130 a day per model (estimate). The gateway therefore has an explicit
  429 branch that waits for `retry-after` (≤ 60 s), retries at most 3 times, then falls back to the
  20b model; plain Retry On Fail is used only for network errors because it waits a fixed delay.
- **1,000 requests/day caps the whole system** (see the counterfactual below).
- **Change detection in Workflow A** matters for the same reason: an unchanged page costs zero calls.

## Matching and the Optimization Treasure Hunt

**Choice.** Make matching deterministic and spend tokens only on what columns cannot express. In
score-per-hour order:

1. **LLM at ingest, not at match time.** Workflow A structures each product's criteria once per
   content change, gated by a SHA-256 of the normalised criteria text. Steady state: zero calls a day.
2. **Stage 1 — SQL.** One set-based query applies hard criteria in Postgres (NULL criterion =
   unconstrained, `employment_status = ANY(allowed_employment)`).
3. **Stage 2 — deterministic rules.** EMI affordability with a cited assumption (BankBazaar publishes
   "EMI up to 65% of income", [source](https://www.bankbazaar.com/personal-loan-eligibility.html)),
   then each pair is `clear_match`, `clear_reject` or `borderline`, with a `borderline_reason`.
4. **Skip the LLM** for fully structured, high-confidence products: their borderline pairs resolve
   deterministically.
5. **Reason-keyed cohorts.** Borderline pairs are grouped by
   `(product_id, borderline_reason, coarse band of the triggering feature, employment)` and packed
   into ~2.5K-token requests.
6. **Cross-run cache.** `cohort_verdicts` is keyed by cohort and product content hash: a product
   change invalidates its verdicts automatically, and a re-upload costs zero calls. The cache-hit rate
   is reported.
7. **Budget guard.** Pairs left when the daily budget is spent are recorded as `unresolved_budget`,
   never guessed.

The funnel `total_pairs → stage1 → clear / borderline / reject → cohorts → cache hits → llm_calls →
tokens → final_matches`, with per-stage timings, is stored in `pipeline_runs` for every batch.

**Rejected: cohorts by raw value bands** (the original plan: income × score × age × employment ×
product). On the real CSV this gives (measured, before multiplying by products):

| Cohort key | Cohorts across 10,000 users |
|---|---|
| Exact (income, score, age, employment) | 9,869 |
| Income 5k × score 10 × age 5 × employment | 5,528 |
| Income 10k × score 25 × age 10 × employment | 1,028 |
| Income 25k × score 50 × age 10 × employment | 265 |

Fine bands exceed the daily request budget, and coarse bands invite the question "how can one verdict
cover ₹31k and ₹39k?". Keying by the *reason* a pair is ambiguous asks the LLM only questions that
columns cannot answer, such as "a credit score of 700 and above is **preferred**".

**Counterfactual for the README (derived from measured limits).** One LLM call per pair for 10,000
users × 3 products is 30,000 calls, or 30 days of the 1,000-requests/day quota for a single batch. The
engine's actual call count is reported only from a measured run (T36/T37).

## Crawl targets

**Choice (measured, live probe 2026-10-20 with a desktop browser User-Agent).** Three pages that serve
eligibility criteria in static HTML to a plain GET; T27 confirms them:

| Target | HTTP | robots.txt | Criteria in static HTML |
|---|---|---|---|
| [ICICI eligibility](https://www.icicibank.com/personal-banking/loans/personal-loan/eligibility) | 200 | Allows | Age 18–58, ₹30,000 minimum monthly income, "credit score of 700 and above is preferred"; rates from 9.99% |
| [HDFC eligibility](https://www.hdfcbank.com/personal/borrow/popular-loans/personal-loan/eligibility) | 200 | Returned 403, so unverified | ₹25,000 income; main page 9.99%–24% |
| [BankBazaar eligibility](https://www.bankbazaar.com/personal-loan-eligibility.html) | 200 | Allows the path | "CIBIL score of 750 or more", "EMI up to 65% of income" |

Swaps: [Kotak](https://www.kotak.com/en/personal-banking/loans/personal-loan.html) and
[IDFC FIRST](https://www.idfcfirstbank.com/personal-banking/loans/personal-loan), if HDFC blocks the
EC2 IP or its robots stance stays unverifiable.

**Rejected.** Bajaj Finserv, Paisabazaar and Axis: their static HTML was mostly navigation text, so
criteria would need a headless browser.

**Change detection.** Hash only the extracted, normalised criteria text with month/year strings
removed, never the full HTML; pages carry dates such as "Oct 2026" that would change the hash daily.

**Why these thresholds help the demo (estimate).** ₹25k/₹30k income floors and 700/750 score floors
fall inside the sample's ranges, so the funnel will have a real borderline band.

## Infrastructure as code: Serverless Framework v3

**Choice.** Serverless Framework 3.40.0 with `serverless-python-requirements` 6.1.2, pinned in
`package.json` / `package-lock.json`. All resources are in one `serverless.yml`: the four functions, the S3
bucket, both queues, the event source mapping, the S3 Gateway Endpoint, the Lambda security group and
the per-function roles.

**Rejected.**
- *Serverless Framework v4.* It requires a Serverless account login, and a paid licence for
  organisations above a revenue threshold. v3 needs neither.
- *AWS SAM / CDK.* Both are valid. The task brief and plan name the Serverless Framework, and v3's
  `url:` and `sqs: maximumConcurrency` cover what this stack needs in a few lines.

**Facts found while building (measured, T10).**
- v3 refuses a config file outside the working directory, and it ignores a symlinked
  `serverless.yml`, because it checks for a regular file. The packaged code (`lambdas/`) must sit
  below the config. So `serverless.yml` lives at the repo root, not in `infra/` as first planned;
  `infra/` holds the Lambda requirements file and the EC2 material.
- v3's schema does not list `python3.12`, so `sls package` prints a validation warning. The value is
  passed to CloudFormation unchanged, and `cfn-lint` accepts it. `configValidationMode: error` is
  therefore not set.
- Function keys are camelCase (`loadChunk`) because v3 turns `_` into `Underscore` in logical IDs
  (`LoadUnderscorechunkLambdaFunction`), which breaks hand-written `!Ref`s.
- The S3 → `splitCsv` notification is declared on the bucket itself. Roles and environment variables
  use the deterministic bucket name, `clickpe-loan-uploads-<account>-<stage>`, instead of `!GetAtt`.
  Otherwise bucket → notification → function → role → bucket is a cycle, which CloudFormation's
  `validate-template` reported.
- Function URLs get two permissions: the framework's `lambda:InvokeFunctionUrl`, plus an explicit
  `lambda:InvokeFunction` with `InvokedViaFunctionUrl: true`. The second is required for Function URLs
  created since October 2025, and its condition stops it from allowing a direct `Invoke` call.

- `slim: true` (the plugin's size optimisation) strips every `*.dist-info` folder, and `scramp`
  (pg8000's SCRAM auth library) calls `importlib.metadata.version("scramp")` at import. The packaged
  zip failed `import pg8000` with `PackageNotFoundError: No package metadata was found for scramp`, so every
  RDS-facing Lambda would have crashed at cold start. `validate-template` and `cfn-lint` cannot see
  this. `slim` is off (zip 372 KB → 838 KB), and `make package` now runs `scripts/check_package.py`, which
  imports pg8000 and every handler from the extracted zip in an interpreter with no site-packages
  (`-I -S`).
- `splitCsv` is invoked asynchronously by S3. After Lambda's retries, a failed event used to be dropped
  silently, leaving the batch `pending` forever. `maximumRetryAttempts: 2`, `maximumEventAge: 3600` and an
  on-failure destination, the `split-failures` queue (kept apart from `ingest-dlq` because its records
  are Lambda invocation records, not chunk messages, and must never be redriven into `ingest`), make
  that failure visible. T21 adds the alarm.

**SSM parameters and placeholders.** `${ssm:…}` is resolved at package time, so all four parameters
must exist before `sls package`. `/clickpe/db/host` and `/clickpe/n8n/webhook_url` hold placeholders
until the RDS endpoint (T11) and the EC2 private IP (T12) exist. The two SecureStrings were generated
with `openssl rand` and never displayed.

## Row validation: strict on meaning, lenient on format

**Choice (T16).** `lambdas/shared/validation.py` is pure (no AWS, no database). It checks the header
once, reads CSV records with their file line numbers, and turns each record into a typed `UserRow` or
a `Reject` that lists every broken field, for example
`credit_score: '950' is not a whole number from 300 to 900; age: missing`.

- **Columns are matched by name, in any order**, ignoring case, surrounding spaces and a UTF-8 BOM.
  Missing or repeated required columns refuse the file with all problems in one message. Unknown extra
  columns are ignored and reported (`ColumnLayout.ignored`). Rejected: a fixed column order, which
  would refuse a re-ordered spreadsheet export.
- **Format is normalised, meaning is not guessed.** Emails are trimmed and lowercased, UUIDs
  canonicalised, and `employment_status` is matched ignoring case and separators (`self employed`,
  `SELF_EMPLOYED` → `Self-Employed`). Values such as `25,000`, `₹25000`, `750.0`, `1e5` or an unknown
  status (`Student`) are rejected with a reason, not converted.
- **Numbers must be ASCII digits.** Python's `int()` accepts `7_50` and Arabic-Indic `٧٥٠`, and `\d`
  matches any Unicode digit, so the patterns use `[0-9]` and run before conversion.
- **Never looser than the schema.** Every accepted row satisfies the `users` CHECK constraints, plus
  rules the schema cannot express: no control characters (Postgres `text` cannot store NUL), ASCII
  email with a dotted domain and at most 254 characters, name at most 200 characters, income within
  `numeric(12,2)`. Reason: `load-chunk` COPYs a chunk in one statement, so a single accepted row that
  the database refused would fail all 5,000 rows of its chunk.
- **Duplicates.** A repeated `user_id` within a chunk keeps its first row; later copies are rejected
  with `user_id: duplicate of line N`. Duplicates in different chunks are not visible to one chunk:
  the upsert still keeps one row per `user_id`, but the version stored is from whichever chunk commits
  last. Rejected: a cross-chunk check, which would need a second pass over the file or shared state
  between loaders for a case the sample does not contain (10,000 distinct ids, T01).

**Measured (T16).** All 10,000 sample rows are accepted with 0 rejects in 464 ms on the dev machine,
and the 10,000 validated rows insert into PostgreSQL 16 under the real CHECK constraints in one
statement. Boundary rows (score 300/900, age 18/100, income 0.01 and 9,999,999,999.99, 254-character
email, 200-character name) insert the same way. With email lowercasing removed (a mutation probe),
that test fails with `users_email_check`. Commands in `PROGRESS.md` T16.
