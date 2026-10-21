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
22. [Chunk loader: outcomes, limits and sizing](#chunk-loader-outcomes-limits-and-sizing)
23. [First deployment (T22): measured results and one shortcut](#first-deployment-t22-measured-results-and-one-shortcut)
24. [Completion trigger: one POST from the winner](#completion-trigger-one-post-from-the-winner)
25. [Product structuring: strict schema, then distrust the answer](#product-structuring-strict-schema-then-distrust-the-answer)
26. [Product storage and lifecycle: one statement per site, retire by run history](#product-storage-and-lifecycle-one-statement-per-site-retire-by-run-history)
27. [Workflow B entry: claim, count and record in one statement](#workflow-b-entry-claim-count-and-record-in-one-statement)
28. [Workflow B Stage 1: SQL pre-filter that keeps near misses](#workflow-b-stage-1-sql-pre-filter-that-keeps-near-misses)
29. [Workflow B Stage 2: rule cards in code, classification in SQL](#workflow-b-stage-2-rule-cards-in-code-classification-in-sql)
30. [Workflow B Stage 3: cohort verdicts on the lender's wording](#workflow-b-stage-3-cohort-verdicts-on-the-lenders-wording)
31. [Workflow B persist: matches written from the database, final count read back](#workflow-b-persist-matches-written-from-the-database-final-count-read-back)
32. [Workflow C: compose and recipient guard](#workflow-c-compose-and-recipient-guard)
33. [Workflow C sending: SES at the sandbox rate, send then mark](#workflow-c-sending-ses-at-the-sandbox-rate-send-then-mark)

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

**Choice.** `split-csv` reads the file once and records the exact byte offsets of record boundaries.
Each message carries
`{batch_id, s3_key, etag, chunk_no, total_chunks, start_byte, end_byte, first_line_no, row_count, columns}`,
where `columns` is the header in file order (a byte-range chunk has no header row; added in T16).
`start_byte` is inclusive and `end_byte` exclusive, like a Python slice; `load-chunk` issues
`Range: bytes=start-(end-1)` and receives whole records, so line numbers in the reject report are exact.
The contract is code, not prose: `lambdas/shared/chunks.py` encodes and parses it for both Lambdas.

**`etag` (added in T18).** The ETag from the S3 event is sent as `IfMatch` on every ranged read. A
presigned POST stays valid for 5 minutes, so the same key can be uploaded twice; without the check,
chunks split from the first file could read byte ranges of the second. **Measured on real S3
(T18):** a wrong ETag → `PreconditionFailed`, quoted and unquoted ETags are both accepted, a range
past the end → `InvalidRange`, and the two ranged reads of the sample reassemble the 993,191-byte file
exactly.

**How boundaries are found (T17).** With the parser load-chunk already uses, not a separate scanner.
`csv.reader` (strict) reads the universal-newline lines of the decoded file, the same way
`validation.read_records` reads a chunk, and the bytes of the lines each record consumed are summed
(`surrogateescape` decoding makes `len(line.encode(...))` the exact byte count even for invalid UTF-8).
A cut can therefore fall only where load-chunk's own parse of the whole file would end a record, and
`first_line_no` uses the same physical-line count, so reject line numbers match the file. Chunks hold
5,000 records; blank lines stay with the chunk before them and a chunk starts only at a record, so no
chunk is empty. Tested property, on every fixture and on a seeded random file with quoted CRLFs,
blank lines and doubled quotes at chunk sizes 1, 7, 50 and 1,000: the header plus the chunks
reassemble the file byte for byte, and validating chunk by chunk gives the same valid rows and the
same `(line_no, reason)` rejects as validating the file as one chunk.

**Rejected: a byte scanner that flips "inside quotes" on every `"`.** It is the usual quote-aware
scan, but Python's csv treats a `"` in the middle of an unquoted field as a literal. For
`…,ab"c,"u1⏎@x",…` the toggle scanner believes the quoted field ends at `,"` and cuts at the
newline inside the real quoted field, turning one record into two rejects. A unit test covers this
input (`test_literal_quote_inside_unquoted_field_is_not_a_cut_point`).

**Rejected: "guess a range, then realign to the next newline."** It breaks on quoted fields that
contain newlines, which CSV allows
([ItemReader CSV rules](https://docs.aws.amazon.com/step-functions/latest/dg/input-output-itemreader.html)).
This is an engineering choice, not a cited AWS pattern.

**Whole-object read instead of streaming (T17, user-approved).** The upload cap is 20 MB, enforced by
the POST policy and re-checked by `split-csv` from the event's `object.size` before reading and from
the bytes after reading. So one `GetObject` (with `IfMatch` = the event's ETag) and an in-memory
parse are simpler than carrying parser state across stream blocks. **Measured (laptop, Ryzen 5 7530U,
3 runs):** planning a 20,855,611-byte, 210,000-row file (the sample repeated 21×) into 42 chunks takes
1.28–1.36 s, peak Python allocation 104.3 MB (`tracemalloc`). `split-csv` has 512 MB and 300 s.
**Estimate:** the arm64 Lambda at 512 MB has a fraction of one vCPU, so expect several times the
laptop time; the deployed duration is recorded in T22. Streaming is the upgrade if the cap is raised
past what fits in memory.

**Failures `split-csv` reports itself.** Empty file, over the cap, no header, bad header (missing or
repeated columns, not CSV, not UTF-8), header but no data rows, and an object deleted before the
split each become one `{batch_id, error}` control message. A header-only file needs this most:
it would give zero chunks, and the batch would otherwise stay `pending` forever. A key that is not
exactly `upload_key(batch_id)` (lower-case canonical UUID) is only logged, because load-chunk would
refuse its messages and there is no batch to fail. An object replaced since the event
(`PreconditionFailed`) is skipped, because the newer upload has its own event. S3 and SQS errors
propagate: Lambda retries the asynchronous invocation twice, then sends the event to
`split-failures`.

**Sending.** `SendMessageBatch` in groups of 10 (the SQS maximum); entries SQS reports as failed are
sent once more, and anything still unsent raises so the whole invocation is retried. Re-sent chunks
are harmless because the ledger ignores duplicates.

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
`INSERT INTO users SELECT DISTINCT ON (user_id) … ORDER BY user_id, seq
ON CONFLICT (user_id) DO UPDATE SET … WHERE (<data columns>) IS DISTINCT FROM (<EXCLUDED data columns>)
RETURNING (xmax = 0)`.

**Corrected in T18.** The original text compared `users.* IS DISTINCT FROM EXCLUDED.*`. That row
includes `batch_id`, `created_at` and `updated_at`, which always differ for a new batch, so every row
would be rewritten on an identical re-upload. The comparison now covers the six data columns only.
**Measured:** with the guard removed (a mutation probe), the identical re-upload moved all 10,000
users to the new batch and the test failed with `assert 0 == 10000`; with it, the re-upload reports
`inserted 0, updated 0, unchanged 5000` per chunk. `seq` (file order) replaces `line_no DESC`, so the
upsert keeps the same row as validation (the first occurrence), and `ORDER BY user_id` makes
concurrent chunks take row locks in the same order, which should prevent deadlocks between chunks
that share ids (estimate, not load-tested; see Chunk loader). `RETURNING (xmax = 0)` is the common PostgreSQL idiom for telling inserted from updated rows; it
feeds the per-chunk log counts only.

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
engine's actual call count is reported only from a measured run (T36/T37). Measured in T35 on the sample batch: 2 calls and 3,655 tokens for 2,221 borderline pairs, and 0 calls on
the next run (section "Workflow B Stage 3").

## Crawl targets

**Choice (measured in T27, 2026-10-21, from the n8n EC2 instance's own IP over SSM, desktop browser User-Agent, redirects followed).**
Three primary targets plus one spare. Each serves its criteria text in static HTML to a plain GET, and
`urllib.robotparser` reports the path as allowed for `*`.

| Role | Page (final URL after redirects) | HTML bytes | Criteria text in static HTML (verbatim) |
|---|---|---|---|
| Primary | [ICICI](https://www.icici.bank.in/personal-banking/loans/personal-loan/eligibility) | 1,242,503 | "Minimum monthly income of ₹30,000 and total of 2 years of work experience for salaried individuals"; "A credit score of 700 and above is preferred"; "Minimum 18 years for salaried applicants and 23 years for self-employed" |
| Primary | [HDFC](https://www.hdfc.bank.in/personal-loan/eligibility-criteria) | 1,096,086 | "Age: 21 to 60 years"; "Minimum monthly net income of ₹25,000"; employees of private limited companies and public sector undertakings |
| Primary | [IDFC FIRST](https://www.idfcfirst.bank.in/personal-banking/loans/personal-loan) | 2,667,536 | "Age: Your age should be between 21 to 60 years"; "CIBIL Score: You should have a CIBIL Score of 710 or above"; "Salaried or Self-Employed"; "rates starting from 9.99% p.a." |
| Spare | [BankBazaar](https://www.bankbazaar.com/personal-loan-eligibility.html) | 219,149 | Table: "Age limit 21 - 68 years", "Minimum Net Monthly Income Rs.5,000 and above", "CIBIL score of 750 or more", "Maximum EMI Up to 65% of Income" |

**Facts found while probing.**
- Every bank moved to a `bank.in` domain and 301-redirects the old `.com` URL (ICICI, HDFC, Kotak,
  IDFC FIRST). The crawler must follow redirects and the site list stores the final URL.
- robots.txt, read from the EC2 IP: ICICI, HDFC (`www.hdfc.bank.in`, which resolves the earlier
  403-unverified note), BankBazaar and IDFC FIRST all return 200 and allow the target path for `*`.
  The only HDFC rule for `*` is `Disallow: /homeloans-cug`.
- Interest rates are not in the criteria text of ICICI or HDFC. ICICI only embeds `minInterest 9.99`,
  `maxInterest 17` in a calculator JSON blob, which is too brittle to select. HDFC's page has no rate
  text. IDFC FIRST and Kotak print "9.99% p.a." / "10.99%" in prose. Products without a rate keep
  `interest_rate_min/max` NULL and a lower `parse_confidence` in T30; that is the honest input to
  Stage 2's borderline rule, not something to guess.
- Credit score floors: ICICI ("700 and above is preferred"), IDFC FIRST (710) and, found by T28's
  extraction, HDFC (FAQ text: "minimum credit score of 720"; "above 720 is ideal"). The T27 probe had
  missed HDFC's because it lives in an accordion FAQ, not the eligibility list. HDFC's 720 is
  worded as a requirement in one line and as "ideal" in another, which makes it a natural borderline
  case for Stage 2/3.

**Selectors (confirmed in T28 against the live DOM, from the EC2 IP).** Each site has one CSS selector
in the workflow's `Config · Crawl targets` node; the HTML Extract node reads it per item.

| Site | Selector | Lines kept (2026-10-21 run) |
|---|---|---|
| ICICI | `span.step-bullet` | 13 |
| HDFC | `span.description, span.accordion-faq_description, div.accordion-faq_description p` | 18 |
| IDFC FIRST | `h1.hd1, li.eligi-hover-content, div.gsa-ir-desc p, div.gfnfnb-desc p.txt` | 6 |
| BankBazaar (spare, disabled) | `table.w-full tr` | 23 |

Class names on these sites are generated and can change, so a selector only narrows the page to the
eligibility region. The decision of what counts as a criterion is text-anchored in the
`Normalize · Criteria lines` node: keep lines with income, age, score, employment or rate wording that
also contain a number or an employment word, drop bracketed image paths, bullets, boilerplate
("disclaimer", "terms and conditions") and month/year strings, then de-duplicate and sort. If a
redesign breaks a selector the run does not fail silently: the site gets `status = no_criteria_found`.

**Rejected.**
- Kotak: the personal-loan page (820,923 bytes) has the rate ("Starting at 10.99% p.a.") and the
  amount but no income, age or score criteria in static HTML, so it adds nothing for matching.
- Bajaj Finserv, Paisabazaar and Axis: their static HTML was mostly navigation text, so criteria
  would need a headless browser (earlier probe).
- Using BankBazaar as a primary target: it is an aggregator whose generic floor (₹5,000) is not a
  lender's product; kept as the spare and as a cross-check of the 750 score and 65% EMI figures.

**Change detection.** Hash only the extracted, normalised criteria text with month/year strings
removed (for example "in Oct'26" on IDFC FIRST), never the full HTML; pages carry dates that would
change the hash daily. Page sizes of 1-2.7 MB mean only the extracted lines are stored or hashed.

**Why these thresholds help the demo (estimate).** ₹25k/₹30k income floors and 700/710 score floors
fall inside the sample's ranges (income 25k-150k, score 650-800), so the funnel will have a real
borderline band.

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
  that failure visible. T21 added an alarm on each (see "DLQ handling (T21)").

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

## Chunk loader: outcomes, limits and sizing

**Choice (T18).** `load-chunk` handles each SQS message in four steps: `start_loading` (autocommit) →
ranged S3 read + validation → one transaction (claim the chunk in the ledger, COPY into staging,
upsert, store rejects, add the counts) → `try_complete` after the commit. The S3 read and validation
run before the transaction, so the transaction holds locks only for database work; a redelivered
chunk costs one wasted ranged GET, which is rare.

**Every message ends in exactly one of three outcomes:**

| Outcome | When | What happens |
|---|---|---|
| Acknowledged | chunk loaded; duplicate delivery; batch already failed or finished | nothing more |
| Acknowledged, batch `failed` | split control message; object replaced (`PreconditionFailed`), range invalid or short read; columns missing; chunk count differs from the stored one; the database refuses the data (SQLSTATE class 22 or 23) | `upload_batches.error` names the chunk and the reason; later chunks of that batch are skipped without reading S3 |
| Retried (`batchItemFailures`) | connection, network, timeout, deadlock or other database errors; S3 throttling or unreachable; an unparseable message | SQS redelivers that message only; after 5 receives it moves to `ingest-dlq` (on the 5th receive the loader first marks the batch `failed`, T21) |

Rejected: retrying every error. A chunk whose bytes or data can never load would use all 5 receives
(up to an hour with the 720 s visibility timeout) before the user sees a failure. Rejected: failing
the batch on every error. One network blip would kill a 40-chunk upload that a retry would finish.

**Missing object (measured + cited).** With `s3:ListBucket`, a missing key returns `NoSuchKey`
(measured with the admin user). The `load-chunk` role has only `s3:GetObject` on `uploads/*`, and
without `ListBucket` S3 answers a missing key with `403 AccessDenied`
([GetObject permissions](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html)). That
case is therefore retried and ends in the DLQ instead of failing at once. The only cause in this
design is the 7-day lifecycle rule, so it is accepted rather than solved by granting `ListBucket`.

**Reject report.** Every reject is counted in `chunk_loads` and `upload_batches.rows_rejected`; the
first 100 per chunk are stored in `rejected_rows` with the file line number, the reason and the raw
text (≤ 1,000 characters). A per-chunk cap is deterministic under parallel chunks; a per-batch "first
N" would need a lock or a count that concurrent chunks can race on. A 20 MB upload is about 40 chunks,
so at most ~4,000 stored rows (estimate). NUL and bytes that are not UTF-8 are replaced with U+FFFD
before storing, because a Postgres `text` column cannot hold them.

**Invalid UTF-8.** Bytes are decoded with `surrogateescape`, and any record containing an undecodable
byte becomes a `not valid UTF-8` reject. Rejected: strict decoding, which fails the whole chunk on one
byte, and `errors="replace"`, which would silently store a corrupted name.

**`row_count` mismatch** between the message and the records read is logged as a warning, not a
failure: split-csv and Python's `csv` module may count an unparseable record differently, and the
ledger counts what was actually loaded or rejected.

**Sizing (measured + estimate).** A 5,000-row chunk of the sample is ~0.5 MB (measured: 496,503 and
496,618 bytes). The local run (PostgreSQL 16 in Docker on the dev machine) took 283–286 ms per chunk
for the first load and 144–146 ms for the unchanged re-upload. That is not Lambda-on-RDS throughput;
T22/T37 measure that. The 120 s timeout leaves a large margin for a cold start, the TLS handshake and
a slower `db.t4g.micro`, and keeps the visibility timeout (6×) at 12 minutes. 512 MB because Lambda
allocates CPU in proportion to memory
([memory and CPU](https://docs.aws.amazon.com/lambda/latest/dg/configuration-memory.html)), and
validation is CPU-bound Python; a chunk's bytes, text and parsed rows use a few MB (estimate).

**Concurrent chunks with the same `user_id` (estimate, not load-tested).** The upsert takes row locks
in `user_id` order, so two chunks that share ids wait for each other instead of deadlocking. If a
deadlock happened anyway, its SQLSTATE `40P01` is in the retried class.

**Not in T18.** The POST to n8n when `try_complete` wins was added in T19; see [Completion trigger](#completion-trigger-one-post-from-the-winner).

## First deployment (T22): measured results and one shortcut

**Deployed and verified (measured, `clickpe-loan-engine-dev`, `ap-southeast-2`).** `sls deploy` took 280 s.
The smoke test (`scripts/smoke_test.sh`) calls the `getUploadUrl` Function URL, posts the CSV to S3 with
the returned presigned fields (HTTP 204), then polls `batchStatus` until the batch is `processed`:

| Upload | Chunks | Result | `splitCsv` | `loadChunk` per chunk |
|---|---|---|---|---|
| `good_users.csv` (5 rows) | 1 | `processed`, 5 ok | 175 ms | 98 ms |
| `data/users.csv` (10,000 rows, 993,191 B) | 2 | `processed`, 10,000 ok, 0 rejected | 217 ms | 288 ms and 250 ms |
| same file again | 2 | 0 inserted, 0 updated, 10,000 unchanged | | 146 ms and 177 ms |
| `malformed_users.csv` (11 rows) | 1 | `processed`, 1 ok, 10 rejected with line numbers | 107 ms | 80 ms |

From batch creation (`created_at`) to `processed` (`updated_at`) took 5.7 s (5 rows, includes cold starts), 6.9 s (10,000 rows) and 2.3 s (malformed fixture). Peak memory: `loadChunk` 112 MB of 512 MB, `splitCsv`
110 MB of 512 MB, `getUploadUrl` 103 MB of 256 MB, `batchStatus` 66 MB of 256 MB. `loadChunk` init was 306 ms
on a cold start. After all uploads `ingest`, `ingest-dlq` and `split-failures` each held 0 messages. This
confirms from inside the VPC the paths that were only simulated before: S3 ranged reads through the Gateway
Endpoint, TLS-verified connections to the private RDS instance, and the SQS event source mapping.

**Shortcut: the Lambdas connect as the RDS master user `clickpe`.** `serverless.yml` first named a
least-privilege `loans_app` role that was never created on RDS. For the demo the config now matches the
instance (`dbName` and `dbUser` both `clickpe`). The connection is still private, TLS-verified and limited by
security group to the Lambda SG, but the role can do more than the loader needs. The upgrade is a role with
`INSERT`/`UPDATE`/`SELECT` on the ingest tables only, tracked for the T45 security review.

**RDS ingress.** The Lambda security group is created by the stack, so the RDS group rule is added after the
first deploy, by SG reference only:
`aws ec2 authorize-security-group-ingress --group-id sg-0f0ca5e2b7cb5e1c3 --ip-permissions "IpProtocol=tcp,FromPort=5432,ToPort=5432,UserIdGroupPairs=[{GroupId=<LambdaSecurityGroupId output>}]"`.

## Completion trigger: one POST from the winner

**Choice (T19).** After its commit, the `load-chunk` invocation whose `try_complete` UPDATE returns a row
POSTs `{"batch_id": "<uuid>"}` with an `X-Webhook-Secret` header to n8n at
`http://172.31.26.164:5678/webhook/match-batch` (SSM `/clickpe/n8n/webhook_url`). Every other caller logs
`completion_checked` with `won: false` and posts nothing. The client is the standard library's `urllib`, so
the package gains no dependency (`lambdas/shared/notify.py`).

**Retry policy.** 5 s timeout per attempt, 3 attempts, 0.5 s and 1 s back-off; worst case ≈ 16.5 s inside the
120 s Lambda timeout. Retried: connection errors, timeouts, 429 and 5xx. Not retried: any other status
(401 wrong secret, 403 outside the IP allowlist, 404 workflow not published), because none of them can
change within seconds.

**A failed POST is logged, not handed back to SQS.** The message is acknowledged and the batch stays
`processed`; the Lambda logs `webhook_failed` at ERROR with the attempts, last status and error. Returning
the message to SQS would not help: the redelivery finds the batch no longer `loading`, skips it, and can
never win the completion again. Recovery is `scripts/retrigger_batch.sh <batch_id>`. It checks through the
`batchStatus` Function URL that the batch is `processed`, then re-POSTs from the n8n instance with SSM Run
Command. The instance reads the secret from SSM with its own role and passes it to `curl` on stdin, so the
secret is never in command parameters, SSM command history or a process argument list.

**Duplicates are expected downstream.** A retry after a timeout delivers twice if n8n received the first
POST but its answer was lost, and the retrigger script can be run twice. Workflow B (T32) must start with
the conditional `processed → matching` UPDATE and stop when it gets no row back (layer 4 of
[Webhook security](#webhook-security-four-layers)).

**Known gap.** If the Lambda dies after `try_complete` commits but before the POST, the batch stays
`processed` with no trigger, and no redelivery can send it. It is visible as a `processed` batch with no
`pipeline_runs` row, and the retrigger script fixes it.

**Rejected: a transactional outbox** (a `notify_pending` row written with the completion, plus a scheduled
sweeper). It closes the gap above automatically, but adds a table and a schedule for a window of a few
milliseconds per batch. Listed as the production upgrade. **Rejected: retrying through SQS**, for the reason
above.

**Measured (T19).** Local, PostgreSQL 16 + a real HTTP receiver: 10 batches × 5 chunks, every chunk
delivered twice, 10 concurrent workers per batch behind a barrier → 100 chunk deliveries, 90 losing
completion checks, exactly 10 POSTs. With the completion guard weakened to
`status IN ('loading', 'processed')`, the same test sees 2–4 POSTs per batch. Live, deployed stack with a
temporary n8n receiver at `match-batch` (IP allowlist + SHA-256 check of the secret header, 401 on
mismatch):

| Upload | Chunks | Completion checks lost | Winner chunk | Webhook | n8n executions |
|---|---|---|---|---|---|
| `good_users.csv` | 1 | 0 | 0 | HTTP 200, 1 attempt | 1 |
| sample × 3 (30,000 rows) | 6 | 5 | 5 | HTTP 200, 1 attempt | 1 |
| same file | 6 | 5 | 0 | HTTP 200, 1 attempt | 1 |
| same file | 6 | 5 | 1 | HTTP 200, 1 attempt | 1 |
| `good_users.csv`, n8n stopped | 1 | 0 | 0 | 3 attempts, `Connection refused`, `webhook_failed`; batch `processed`, queue empty | 0 |
| retrigger of that batch after restart | | | | HTTP 200 | 1 |

**Open item for T32/T45 (T32 decision: [Workflow B entry](#workflow-b-entry-claim-count-and-record-in-one-statement)).** n8n saves the Webhook node's output, which includes the request headers, so
`X-Webhook-Secret` lands in execution data on the n8n volume (the same instance and trust boundary as the
encryption key; pruned after 168 h). A Header Auth credential does not change this. T32 decides how
Workflow B avoids keeping it.

## Product structuring: strict schema, then distrust the answer

**Choice (T30).** Workflow A sends each lender's normalised criteria lines to Groq `openai/gpt-oss-120b`
with a strict JSON-schema response (`temperature 0`, `reasoning_effort low`, `include_reasoning false`,
`max_completion_tokens 1000`) through a direct HTTP Request node. T26's LLM Gateway is not built; when it
is, the HTTP node is replaced by an Execute Workflow call and the `Route` node keeps its three outputs.
The schema has nine required fields, all nullable except one boolean, named after `loan_products` columns.
The model's answer is then re-checked in a Code node (`Coerce · Validate product`), because a schema
guarantees the shape, not the truth:

- units are coerced (`₹25,000/month`, `9.99% p.a.`, `0.3 lakh`, `60 years` become plain numbers) and
  ranges are enforced: the database CHECK ranges, plus a plausibility floor of ₹1,000 monthly income;
- minimum ≤ maximum for age, score and rate; employment limited to the three canonical values, never an
  empty list (an empty array matches nobody, so the schema forbids it);
- **grounding:** every extracted number must occur in the source text (digits, with `,` grouping and
  `k` / `lakh` / `crore` expansions). An ungrounded number rejects the product; it is never set to NULL,
  because a NULL criterion means "unconstrained" and would silently widen eligibility;
- `parse_confidence` is computed from completeness, not asked of the model: weights income 0.30,
  credit score 0.25, age 0.20, interest rate 0.15, employment 0.10; capped at 0.60 when the model sets
  `has_conditional_criteria` (thresholds that differ by employment type, work-experience or employer
  conditions the columns cannot hold). Where thresholds conflict the model is told to use the loosest bound,
  so Stage 1 never drops a user who might qualify; Stage 2 (T34) treats low confidence as "borderline".

Anything that fails (HTTP 429, any other HTTP error, network error, truncated or non-JSON content,
schema or range violation, ungrounded number, no criteria found, fetch failure) is written to `crawl_runs`
with status `failed` and the reason, and never reaches `loan_products`. Every Groq call, successful or not,
is written to `llm_calls` (purpose `crawl_structuring`, tokens, server-side latency).

**Rejected.**
- *Asking the model for a confidence score.* Self-reported confidence is uncalibrated; completeness of the
  extracted fields is something the next stage can reason about and a reviewer can recompute.
- *Letting the model convert or infer* (annual to monthly income, "preferred" to a softer score). The prompt
  forbids it; conversions that matter happen in code where they can be tested.
- *n8n's Information Extractor / AI Agent nodes.* No strict schema, no status-code branching, no control
  over the 429 path (see "LLM provider: Groq").
- *Retry On Fail on the two Postgres write nodes.* See the finding below.

**Measured (2026-10-21, n8n on the EC2 instance, real Groq calls).** Execution 27, the three primary lenders:

| Lender | Income | Score | Age | Rate | Employment | Conditional | `parse_confidence` | Prompt / completion tokens | Server latency |
|---|---|---|---|---|---|---|---|---|---|
| ICICI Bank | 30,000 | ≥ 700 | 18–65 | NULL | Salaried, Self-Employed | yes | 0.60 | 1,562 / 264 | 612 ms |
| HDFC Bank | 25,000 | ≥ 720 | 21–60 | NULL | Salaried | yes | 0.60 | 979 / 259 | 570 ms |
| IDFC FIRST | NULL | ≥ 710 | 21–60 | from 9.99 | Salaried, Self-Employed | no | 0.70 | 652 / 196 | 434 ms |

ICICI's own page gives contradictory ages (18, 23, "18 to 58", a tenure limit of 65); the loosest bound
and `conditional = yes` is the honest result. Three calls, 3,193 prompt and 719 completion tokens in total.
The extracted text hashes identically across three executions (15, 17, 27), which is what T29 relies on.

**Drills (real API responses, each leaves the other lenders untouched).**

| Drill | What happened | Where it ended |
|---|---|---|
| Wrong credential (found, not planned) | `groq-api` held the bare key, Groq answered 401 for all three | `Mark · Groq call failed` → `crawl_runs`, `llm_calls` status 401 |
| `max_completion_tokens` 30 | Groq answers **HTTP 400** when a strict-schema reply is cut off, not a 200 with `finish_reason=length` | `Mark · Groq call failed` → `crawl_runs`, `llm_calls` status 400 |
| ICICI forced to return `min_credit_score 1200`, `min_age 60 > max_age 21`, employment `Student`, income 45,000 | HTTP 200, schema bypassed with JSON mode | `Coerce` rejected with 7 reasons; `Check · Product valid` 2 true / 1 false; HDFC and IDFC structured |
| Criteria text repeated 14× per prompt | First call (4,213 prompt tokens) 200, second (7,053 requested) **HTTP 429**, `retry-after` 21 s: "TPM limit 8000, used 3725, requested 7053" | `Mark · Groq rate limited` → `crawl_runs` with Groq's message |

Also exercised locally against 17 fixture answers (unit strings, ranges as strings, out-of-range, ungrounded,
min > max, fractional age, unknown group, empty array, all NULL, non-JSON, truncated, missing key, array
instead of object, no choices): each is accepted or rejected as designed.

**Findings worth knowing.**
- **Retry On Fail re-ran a successful INSERT.** On n8n 2.44.4, the `crawl_runs` insert node with Retry On Fail
  (3 tries, 5 s) executed three times on success (ids 1–3, 4–6, 7–9 in `crawl_runs`, five seconds apart), so
  every failure was logged three times; the same query with retry off ran once (27 ms). The `llm_calls`
  insert with identical retry settings ran once. The cause was not isolated. Both Postgres write nodes now
  have no retry: a database error fails loudly (and, once T25 exists, alerts through Workflow E) instead of
  risking a duplicate write. Retry On Fail stays only on the HTTP calls (network errors).
- `usage.completion_tokens` from gpt-oss includes hidden reasoning (a probe showed 129 of 234 completion
  tokens were reasoning), so `llm_calls.completion_tokens` is what Groq bills. Groq also returns
  `usage.total_time` in seconds, which is stored as server-side latency (n8n exposes no request timing).
  `prompt_tokens` for the identical ICICI prompt was 794 on one run and 1,562 on another, so per-call token
  figures are quoted as measured, not as constants.
- The `groq-api` Header Auth credential from T24 stored the key without the `Bearer ` prefix and had never
  been tested against Groq; it was fixed in place (`GET /models` 200 from the instance afterwards).
- The `crawl_runs` and `llm_calls` tables contain rows from these drills (including the duplicated inserts
  above); they are real events from T30 development, not seed data.

## Product storage and lifecycle: one statement per site, retire by run history

**Choice (T31).** A product that passes `Coerce · Validate product` is written by one Postgres statement
(`Upsert · loan_products + crawl_runs`) made of four CTEs:

- `incoming` holds the parameters and computes `content_hash` as `sha256` of the criteria text inside
  Postgres, so the hash is defined in one place and T29 can compare against it;
- `existing` and `outcome` read the row as it was before the statement (CTEs share one snapshot) and decide
  `inserted`, `reactivated` and `changed`, where `changed` means the hash or any structured field differs;
- `upserted` is `INSERT … ON CONFLICT (source, product_name) DO UPDATE` and always sets `active = true` and
  `last_seen_at = now()`; the row id is stable, and `is_seed` is never touched (seed rows carry
  `source = 'seed'`, so a crawl cannot collide with them);
- `logged` inserts the `ok` row into `crawl_runs` in the same statement, so a product row and its run row
  cannot disagree and a failed write leaves neither.

**Lifecycle.** A product is never deleted. The node `Retire · Product after 3 failed runs` runs after each
failure is logged and looks at that source's last three `crawl_runs` rows; if all three are `failed` it sets
`active = false` for the source's non-seed product. The next good crawl reactivates the same row. "Run" means
a `crawl_runs` row, not a calendar day, so manual demo runs and the daily schedule count alike, and a product
is not retired by a single bad day. The threshold is the constant `max_missed_runs` at the top of the query.
Failure includes a site being down: we cannot tell "the lender dropped the product" from "the page moved",
and for matching the safe answer to both is to stop recommending a product we can no longer verify.

**Rejected.**
- *A "run once after all sites" node (Merge, then retire).* Measured: in n8n 2.44.4 with execution order
  `v1`, the Merge fired once per arriving branch (twice in a run with a database failure and a fetch failure),
  so the supposed single retire ran twice. The rule is per source anyway, so it moved next to the failure log.
- *Time-based retirement* (`last_seen_at` older than N days): a site outage over a long weekend would retire
  products that are still on offer.
- *The Postgres node's built-in Insert or Update operation:* it cannot set `last_seen_at = now()`, compute the
  hash, read the previous row or write the `crawl_runs` row in the same transaction.

**Measured (execution ids from `execution_entity` on the EC2 instance).**

| Drill | Result |
|---|---|
| First run, 3 lenders | 3 inserted (ids 11–13), `changed = true`, 3 `ok` rows in `crawl_runs`, `loan_products` 5 seed + 3 crawled |
| Identical re-run (execution 32) | same ids, `inserted = false`, `changed = false`, `last_seen_at` moved, 8 rows and 8 distinct keys |
| Site 404 plus a forced CHECK violation on ICICI's write (execution 44) | HDFC and IDFC upserted, ICICI routed to `Mark · Upsert failed`, 404 site to `Mark · Fetch failed`; both logged in `crawl_runs`; execution status `success` |
| ICICI URL broken for 3 runs (executions 41–43) | `silent_for_3_runs` false, false, then true with `retired_count = 1`; HDFC and IDFC upserted every time |
| Next good run (executions 40, 45) | ICICI `reactivated = true`, same id 11, nothing deleted |

**Findings worth knowing.**
- **One failed write stopped every other site.** With the Postgres node's default `queryBatching: single`, the
  first failing item aborted the node: HDFC and IDFC were never written. `queryBatching: independently` runs
  one statement per item and lets the error output carry only the failed item. The success path of
  `Log · crawl_runs failure` still uses the default, which is acceptable for an append-only insert.
- On the error output the database message is not readable (`$json.error.message` is undefined); the
  `description` field holds the row detail ("Failing row contains …"), which is what the log stores, cut to
  300 characters. The full error remains in the n8n execution.
- `loan_products.id` has gaps (11, 12, 13, then 17+ in drill runs): a statement that fails or conflicts still
  consumes identity values, as in any PostgreSQL `GENERATED BY DEFAULT` column. The ids are not meaningful.
- `updated_at` moves on every crawl because `last_seen_at` is written to the same row and the table's trigger
  fires on any update. "Did the product change?" is answered by `crawl_runs.changed` and `content_hash`, not
  by `updated_at`.
- `content_hash` covers the criteria text only (T29 compares it before calling the LLM). If the model or
  prompt changes and the same text yields different structured fields, the hash stays equal. T35's verdict
  cache must therefore also key on the structured fields, not on `content_hash` alone.
- The crawl log has one row per source per run, not per product; two products from one source would share
  one retirement history. Today every source has one product.

## Workflow B entry: claim, count and record in one statement

**Choice (T32).** `POST /webhook/match-batch` is a Webhook node with Header Auth (`webhook-secret`), the
VPC-CIDR IP allowlist and a Respond to Webhook node. After `batch_id` is checked against a lower-case UUID
pattern, one SQL statement does three things: `UPDATE upload_batches SET status = 'matching' WHERE id = $1
AND status = 'processed'`, count `users_in_batch × active_products`, and `INSERT INTO pipeline_runs`. The
final `SELECT` starts from the counts and `LEFT JOIN`s the inserted run, so it always returns exactly one
row; `run_id` is NULL when nothing was claimed. Replies: 202 with `{batch_id, run_id, total_pairs,
users_in_batch, active_products}`, 400 malformed id, 409 batch not `processed`, 500 database error. The
reply is sent before the funnel stages, so the Lambda's 5 s timeout never waits on matching.

**Why one statement.** A claim followed by a separate run insert can fail between the two and leave a batch
in `matching` with no `pipeline_runs` row, and nothing would move it back. Data-modifying CTEs commit or
roll back together.

**Replay safety.** The claim is the guard (layer 4 of [Webhook security](#webhook-security-four-layers)): the
second delivery of the same batch finds `status = 'matching'`, updates nothing and gets 409. The Lambda
treats 409 as non-retryable, which is right: the first delivery already won. A 5xx is retried by the Lambda
(3 attempts), and a failed claim changes nothing, so the retry is safe.

**What "users in batch" means.** `users.batch_id` is the batch that last inserted or changed the user (the
upsert is guarded by `IS DISTINCT FROM`). An identical re-upload therefore has 0 users in its own batch and
`total_pairs = 0`; those users were matched when they first arrived. Consequence, stated honestly: a user
who arrived before a product existed is not re-matched when the product is added later. Re-matching on a
product change is not built. A zero-pair batch still moves to `matching`, so T36 must always finish a run,
including when there is nothing to match.

**Rejected.**
- *Separate nodes for claim, count and run insert.* Readable on the canvas, but not atomic (above).
- *`Always Output Data` on the Postgres node to cope with the empty result of a lost claim.* Measured with a
  throwaway copy whose query was `SELECT 1/0`: the forced database error came back as **409**, not 500,
  because the empty item left on the success output hid the error output. A broken database would have looked
  like a replay and the Lambda would not have retried. The always-one-row `LEFT JOIN` removes the need; the
  same drill then returned 500.
- *Retry On Fail on the claim node.* After a successful claim a retry finds the batch in `matching` and
  reports a false 409; the Lambda's own retry covers real failures. (Same lesson as T30's INSERT.)
- *Matching in the webhook's own response.* Would hold the Lambda's connection for the length of the funnel.

**Secret in saved executions (open item from T19).** n8n stores the Webhook node's output, headers included,
so every execution on the volume contains `X-Webhook-Secret` (confirmed in `execution_data` of this workflow;
n8n 2.44.4 has no per-node "do not save" option). Chosen: keep saving executions, because they are the
evidence reviewers can open, and accept the risk inside its boundary: the data sits on the same encrypted-at-rest
EBS volume and instance as the n8n encryption key, executions are pruned after 168 h, and the secret is only
accepted from the VPC. Mitigation for the demo: rotate `/clickpe/n8n/webhook_secret` and the `webhook-secret`
credential after the recording, and never open the Webhook node's output panel on camera. Turning off
`EXECUTIONS_DATA_SAVE_ON_SUCCESS` for this workflow would remove the exposure and the evidence; listed for T45.

**Measured (2026-10-21, n8n 2.44.4 on `i-02ffa9d08e8403a4a`, Lambda `loadChunk` in the VPC).**

| Probe | Result |
|---|---|
| No header / wrong secret | HTTP 403 `Authorization data is wrong!`, no execution created |
| Right secret from `127.0.0.1` (outside the allowlist) | HTTP 403 `IP is not allowed to access the webhook!` |
| `batch_id` not a UUID / upper-case UUID / empty body | HTTP 400 each |
| Well-formed unknown `batch_id` | HTTP 409, no `pipeline_runs` row |
| Real upload of 200 new users (batch `4d5d548f…`) | Lambda `webhook_sent` status 202 on attempt 1; one execution; `pipeline_runs` row `total_pairs = 1600` = 200 users × 8 active products; batch `matching` |
| Same batch POSTed again | HTTP 409; still exactly 1 `pipeline_runs` row |
| Forced `SELECT 1/0` in a throwaway copy | HTTP 500 `could not start matching run` |

`active_products = 8` is the 5 labelled seed products plus the 3 crawled ones; Workflow B matches against
both until the seed rows are deactivated or kept on purpose (decision for T33). Decided in T33: deactivated, see the next section.

## Workflow B Stage 1: SQL pre-filter that keeps near misses

**Choice (T33, approved by the user).** Three decisions, then one statement.

1. **Seed products take no part in matching.** The 5 seed rows (ids 1–5) were set `active = false` by
   literal id on RDS, and `db/seed_products.sql` now inserts new seed rows inactive. Its upsert never touches
   `active`, so re-seeding cannot switch them back on. `active` stays the one switch read by both the T32
   claim count and Stage 1, and no email can offer a made-up "Seed ·" product. For the sample batch
   `total_pairs` drops from 80,000 to 30,000 (10,000 users × 3 crawled products).
2. **Candidate pairs stay in Postgres.** Stage 1 is one `INSERT … SELECT` into a new table,
   `match_candidates(run_id, user_id, product_id, near_miss_criteria)` (migration `0002`). n8n gets one
   summary row, not 14,165 items. n8n holds every item in memory and saves every node's output in SQLite on a
   2 GB `t4g.small`; at T37's 100k users that would be over 100k items per node. Consequence for T34: the
   Code node decides the rules per product, and SQL applies them to the pairs.
3. **Near misses are kept, tagged with the criteria they missed.** Income and credit-score floors and the
   score ceiling get a 5% margin (`near_miss_margin`, a named value in the statement's first CTE). Age and
   employment stay strict. The LLM stage exists to judge wording that columns cannot hold, such as ICICI's
   "a credit score of 700 and above is **preferred**" and HDFC's "above 720 is **ideal**". A strict
   pre-filter would drop the very users those words are about before anyone could ask.

**The statement.** Batch users × active products, `NULL` criterion = no limit, written to
`match_candidates`. `near_miss_criteria` is `{}` for a strict pass, or for example `{min_credit_score}`. A
second node, `Record · Stage 1 funnel`, writes `stage1_pairs`, `stage1_near_miss` (new column, migration
`0002`) and `stage_ms.stage1`.

**Why a separate record node (found by measurement).** The first version did the insert and the
`pipeline_runs` update in one statement and recorded **153 ms**. `EXPLAIN ANALYZE` of the same work showed
**556 ms**: the three foreign-key checks on `match_candidates` (about 125 ms each for 14,165 rows) run at the
end of the statement, after its `clock_timestamp()` had been read. The record node now measures from Stage 1's
`statement_timestamp()` to after its commit, on the database clock. The fixed live run recorded **578 ms**,
and the plan in [`stage1-explain.md`](stage1-explain.md) gives 567 ms.

**Idempotent, so Retry On Fail is safe here** (unlike the T30 INSERT and the T32 claim). `ON CONFLICT DO
NOTHING` on `(run_id, user_id, product_id)`, counts taken from the table rather than from what this call
inserted, and the first measured `stage1` time is kept. Re-running both statements on RDS for run 7 inserted
0 rows, gave the same counts and kept `stage1_ms = 578`. Without the keep-first rule an earlier re-run had
replaced 561 ms with 79 ms, which would have shown the cost of a no-op.

**Failure branch.** Both nodes retry 3 times with 2 s between tries, then go to `Fail · Mark batch failed
(Stage 1)`. That node moves the batch `matching → failed` with `error = 'matching stage 1 failed: <message>'`
and sets `finished_at` on the run; a batch in any other state is left alone. Measured with a throwaway copy
(`t33faildrill01`, Stage 1 replaced by `SELECT 1/0`): 202 from the claim, the Stage 1 node ran 4,047 ms
(3 tries), then the batch was `failed` with `matching stage 1 failed: division by zero`, the run closed,
`stage1_pairs` stayed NULL (not measured) and 0 candidates were written. The execution is saved as `success`
because the error was handled, so Workflow E (T25) will not see it; the batch's `error` column is the record.

**Measured (2026-10-21, RDS PostgreSQL 16.9, sample batch `9d278e88…`, run 7).**

| Product | Pairs | Strict | Near miss |
|---|---|---|---|
| ICICI Bank (11) | 5,903 | 4,425 | 1,478 |
| HDFC Bank (12) | 2,583 | 1,840 | 743 |
| IDFC FIRST Bank (13) | 5,679 | 4,140 | 1,539 |
| **Total** (of 30,000) | **14,165** | **10,405** | **3,760** |

Near misses by criteria: `{min_credit_score}` 3,718, `{min_monthly_income}` 29, both 13. These numbers are
identical to a count made with an independent query before the node was built. 6,088 of the 10,000 users have
at least one candidate.

Hand check of 3 users against the stored criteria:
- `bb0d9e4a…` (₹60,000, score 760, age 34, Salaried) is a strict pass for all three.
- `03b9e667…` (₹65,000, score 690, age 44, Self-Employed) is a near miss on `min_credit_score` for ICICI
  (690 < 700, ≥ 665) and IDFC FIRST (690 < 710, ≥ 674.5). HDFC excludes it (Salaried only).
- `003190f1…` (₹37,000, score 790, age 36, Business) gets nothing.

**Finding for T34/T35.** No crawled product lists `Business` in `allowed_employment`, so all 3,240 Business
users in the sample (32%) are out at Stage 1. ICICI's text evaluates self-employed applicants on "business"
vintage, so treating business owners as self-employed is arguable. It is a Workflow A structuring question,
not a Stage 1 one, and is recorded rather than changed silently here.

**Rejected.**
- *Strict-only pre-filter* (the original spec): simpler, but the LLM would then only ever see users who
  already pass every column, so soft thresholds could never be relaxed.
- *Pairs as n8n items*: simplest for T34's Code node; does not scale on this instance (above).
- *Dropping the `user_id` / `product_id` foreign keys* to save about 0.27 s per 14k rows: integrity and
  cascading cleanup are worth more than that at this scale.

## Workflow B Stage 2: rule cards in code, classification in SQL

**Choice (T34, four decisions approved by the user).** A Code node turns each product into a *rule card*;
one set-based `UPDATE` applies the cards to every pair Stage 1 left in `match_candidates`. Each pair becomes
`clear_match`, `clear_reject` or `borderline`. n8n handles 3 items (one per product), never the 14,165 pairs.

| Rule | Applies to | Result |
|---|---|---|
| Indicative EMI above 65% of monthly income | any pair whose product publishes a rate | `clear_reject` |
| Strict pass (no near miss) | every product | `clear_match`, with the EMI or "affordability not checked" in the reason |
| Near miss, product `parse_confidence` ≥ 0.70 | fully structured products | `clear_reject`: the threshold is applied as written, no LLM |
| Near miss, product `parse_confidence` < 0.70 | partly structured products | `borderline`, tagged for Stage 3 |

1. **Low confidence makes only near misses borderline (decision A).** ICICI's and HDFC's confidence is capped at
   0.60 because their pages add work-experience and employer-type conditions, and the CSV has no such columns.
   An LLM cannot judge a user's work history from income, score, age and employment either, so sending their
   strict passes to Stage 3 would spend tokens confirming what the columns already say (about 8,486 borderline
   pairs instead of 2,221). Their strict passes become `clear_match`, and the reason says the result is
   indicative and the lender's full conditions still apply.
2. **Skip-LLM rule at 0.70 (decision B).** IDFC FIRST is the one fully structured product, and its page words
   the score floor firmly ("You should have a CIBIL Score of 710 or above"), so its near misses are rejected
   without the LLM. ICICI ("700 and above is preferred") and HDFC ("above 720 is ideal") keep theirs for Stage 3.
   `parse_confidence` is a `real`; the load query rounds it to 2 decimals before the comparison, because 0.7
   stored as `real` is 0.699999988 and fails `>= 0.7` in SQL (found when an independent cross-check disagreed
   on all 1,539 IDFC near misses; a test now pins the cutoff edge).
3. **EMI assumption (decision C).** ₹5,00,000 over 60 months, the top of IDFC FIRST's published EMI calculator
   range ("loans from ₹1 lakh to ₹5 lakh over 24 to 60 months"), at the product's top published rate, else its
   starting rate. Cap: EMI up to 65% of income, from BankBazaar's published guidance (see "Matching and the
   Optimization Treasure Hunt"). A product with no published rate is marked "affordability not checked"; no
   fallback rate is invented. Using IDFC's *starting* rate is optimistic, but it changes no verdict on this data:
   the lowest income in the sample is ₹25,000, and the EMI would need a rate above **30.24% p.a.** to exceed
   65% of it (₹16,250); at 9.99% it is ₹10,621.06. So the EMI rule rejects **0 pairs** on the sample, which is
   reported as measured, not tuned away. It stays because a product with a published high rate, or a low-income
   batch, would trigger it (a test with a 40% product rejects ₹1 below the affordable income and accepts at it).
4. **No "within 5% above a threshold" borderline (decision D).** Passing a stated threshold is not ambiguous;
   the ambiguous side, within 5% below, is already Stage 1's near miss.

**What Stage 3 receives.** Every borderline pair carries `borderline_reason` (`near_miss:<criteria>`, sorted and
joined with `+`), `trigger_feature` (`credit_score` when a score criterion was missed, else `monthly_income`) and
`trigger_value` (the user's value). These are the cohort key fields from "Matching and the Optimization Treasure
Hunt"; T35 adds the band and employment. Every pair also gets a readable `stage2_reason`, for example
"Near miss: credit score 690 vs minimum 700. The product is only partly structured (parse confidence 0.60), so
Stage 3 judges the lender's wording."

**Completeness is enforced by the database.** Migration `0003` adds a CHECK that
`stage2_clear + stage2_borderline + stage2_reject = stage1_pairs`. A pair the cards did not cover stays
unclassified, the record node violates the CHECK, and the run fails instead of quietly losing pairs (tested by
dropping one card).

**Idempotent, so Retry On Fail again.** The `UPDATE` skips pairs whose six Stage 2 columns already hold the
computed values (`IS DISTINCT FROM`), the counts are read from the table, and the first `stage2` time is kept.

**Measured (2026-10-21, RDS PostgreSQL 16.9, sample batch `9d278e88…`, run 10, n8n 2.44.4).**

| Product | Confidence | `clear_match` | `clear_reject` | `borderline` |
|---|---|---|---|---|
| ICICI Bank (11) | 0.60 | 4,425 | 0 | 1,478 (score 1,436 · income 29 · both 13) |
| HDFC Bank (12) | 0.60 | 1,840 | 0 | 743 (score) |
| IDFC FIRST Bank (13) | 0.70 | 4,140 | 1,539 | 0 |
| **Total** (of 14,165) | | **10,405** | **1,539** | **2,221** |

`stage_ms`: `{"stage1": 558, "stage2": 625}`. An independent query that classifies from `near_miss_criteria` and
the product's rounded confidence agrees on 14,165 of 14,165 pairs. Borderline trigger values: 11 distinct credit
scores (665–715) and 1 income (₹29,000), so T35's cohorts will be few. Re-running the Stage 2 statements for run 10
on RDS updated 0 pairs, returned the same counts and kept `stage2 = 625` although it was given a start time in the
year 2000.

**Failure branch.** Same pattern as Stage 1: `Fail · Mark batch failed (Stage 2)` moves `matching → failed` with
`matching stage 2 failed: <message>` and closes the run. Drill with a throwaway copy (`t34faildrill01`, Classify
replaced by `SELECT 1/0`) on a throwaway empty batch: webhook 202, batch `failed` with
`matching stage 2 failed: division by zero`, run closed after 4,196 ms (3 tries, 2 s apart), Stage 2 counts NULL.
The drill batch and its run were deleted afterwards and the drill workflow unpublished (path 404).

**Rejected.**
- *All pairs of low-confidence products borderline* (the literal spec): about 8,486 borderline pairs whose open
  questions (work history, employer) no model can answer from this data.
- *Rules as SQL only*: the EMI arithmetic and the per-product policy read better and test more directly as a
  small function; SQL keeps the per-pair work set-based.
- *Pairs as n8n items*: same reason as Stage 1.
- *A fallback interest rate for products that publish none*: it would be a number with no source.

**Known gap.** ICICI requires self-employed applicants to be 23 or older, but Workflow A stored the loosest bound
(18), so 110 ICICI candidate pairs (run 7) are self-employed 22-year-olds, and those that pass strictly become
`clear_match`. The fix belongs in
Workflow A (per-employment age fields), not in a Stage 2 special case.

## Workflow B Stage 3: cohort verdicts on the lender's wording

**Choice (T35, five decisions approved by the user).** Stage 3 asks the LLM only the questions the columns
cannot answer, once per *cohort* of similar pairs, and never twice for the same lender text. The 2,221
borderline pairs of the sample are all near misses on a threshold that the lender words softly or firmly
somewhere in its text: ICICI says "a credit score of 700 and above is **preferred**", HDFC says both "above
720 is **ideal**" and "you **need** a minimum credit score of 720". Whether a near miss is still eligible is a
reading of that wording, which is what an LLM is for.

1. **Cohort key (decision A).** `verdict version | product | borderline reason | employment | one band per
   missed criterion`, with credit scores in 10-point bands and income in ₹1,000 bands, each labelled with the
   lender's figure, for example
   `v1|product 11|near_miss:min_credit_score|Salaried|credit score 690-699 vs minimum 700`. A pair that misses
   two criteria gets both bands. The model is asked about the **worst value** of each band (690 here, or the
   top of the band for a maximum), so one verdict is safe for every member. Measured on the 2,221 borderline
   pairs of run 10:

   | Key | Cohorts |
   |---|---|
   | Exact values | 32 (and unbounded for income at scale) |
   | **Bands (chosen)** | **20** |
   | Reason only, no band | 7 (one verdict would cover scores 665 to 699) |

   The key carries the threshold, so a re-structured product with a new threshold gets new keys (T31 open item 6).
2. **Packing (decision B).** One request per product with up to 16 cohorts, so the lender text (1.3–2 KB) is
   sent once per request. The response is strict Structured Outputs: `{verdicts: [{cohort_id, eligible,
   reason}]}` with `cohort_id` an enum of exactly the ids in that request; `temperature 0`, `reasoning_effort
   low`, `max_completion_tokens` = 600 + 100 per cohort. Measured with a probe of the two real requests before
   building: 16 cohorts → 1,493 prompt + 762 completion tokens, 4 cohorts → 1,017 + 294. The budget estimate
   (prompt characters ÷ 3 plus the completion cap) gave 4,042 and 2,386, about 1.8× the actual, which is the
   intended side to err on.
3. **Cross-run cache (decision C).** `cohort_verdicts` is keyed by `(cohort_key, product content_hash)`. A new
   batch with users in the same bands costs zero calls; a changed lender page (new hash) or a new prompt
   (`verdict_version`, set in the `Form cohorts` statement) asks again. The first verdict stored wins
   (`ON CONFLICT DO NOTHING`), so two concurrent runs cannot overwrite each other.
4. **No guessing (decision D).**
   - *Budget guard*: before anything is sent, the Code node reads the tokens this model used in the last
     24 h from `llm_calls` and sends a request only if its estimate fits 150,000 tokens (of Groq's 200,000 per
     day, leaving room for Workflow A) and the run stays within 30 calls. Cohorts that do not fit become
     `unresolved_budget` with the arithmetic in their reason.
   - *Pacing*: requests go out one at a time, 20 s apart. Tokens per minute (8,000) bind, not requests, and a
     packed request measured up to 2,366 tokens.
   - *Failures*: HTTP 429 (reason includes `retry-after`), any other HTTP status, no response, non-JSON,
     no verdicts array, a missing or duplicated `cohort_id` → that cohort is `unresolved_error` with the
     reason. Waiting out a 429 and falling back to `gpt-oss-20b` are the LLM Gateway's job (T26, not built).
   - Unresolved pairs are never matched; they keep their reason, and the next run asks for them again because
     nothing was cached for them.
5. **Storage and completeness (decision E).** Migration `0004` adds `cohort_key`, `stage3_outcome`
   (`eligible`, `not_eligible`, `unresolved_budget`, `unresolved_error`) and `stage3_reason` to
   `match_candidates`, three counters to `pipeline_runs`, and a CHECK that the four outcomes add up to
   `stage2_borderline`, as Stage 2 does. A pair the fan-out missed fails the run instead of disappearing
   (tested). `llm_calls` gains `run_id`, so the ledger shows exactly which run spent which tokens.

**Nodes.** `Stage 3 · Form cohorts` (one SQL statement: label pairs, list cohorts with member counts and cache
state, lender texts, 24 h usage) → `Stage 3 · Build LLM requests` (Code: pack, budget) → `Check · Any cohort to
ask Groq` → `Stage 3 · One item per request` → `LLM · Judge cohorts (Groq)`, with `Log · llm_calls (Stage 3)` on
a side branch → `Stage 3 · Read verdicts` (Code: validate) → `Stage 3 · Store verdicts + fan out` (one statement)
→ `Record · Stage 3 funnel`. The only join of two branches is the IF's false output and the Groq path meeting at
`Read verdicts`, and exactly one of them carries an item, so no Merge node is needed (T31 found that Merge does
not wait). SQL nodes are idempotent and retry 3 × 2 s; any error marks the batch `failed` with
`matching stage 3 failed: <message>`.

**Finding: stale planner statistics (measured, fixed).** In the first live run (run 12) `Stage 3 · Form cohorts`
took **16,061 ms**; the same statement under `EXPLAIN ANALYZE` a few minutes later took 147 ms. Stage 1 had just
inserted the run's 14,165 pairs, and autovacuum analyzed `match_candidates` only at 12:26:18, 55 s later, so the
planner still saw almost no rows for the run and chose a nested loop that rescanned the run's pairs for each of
the 2,221 borderline pairs. T33 had already recorded a 313-row estimate for 14,165. Fix: a new node,
`Stage 1 · Refresh planner statistics`, runs `ANALYZE match_candidates` right after the Stage 1 insert (184 ms).
n8n returns one `{success: true}` item for a statement without rows (checked in its source, `utils.js`), so the
chain continues; `Stage 2 · Load product rules` now reads `run_id` from `Record · Stage 1 funnel` by name. With
the fix: Form 168 ms (run 13).

**Measured (2026-10-21, RDS PostgreSQL 16.9, sample batch `9d278e88…`, n8n 2.44.4, `openai/gpt-oss-120b`).**

| Run | What | Cohorts | Cache hits | Calls | Tokens | Eligible | Not eligible | Unresolved | `stage3` |
|---|---|---|---|---|---|---|---|---|---|
| 12 | first live run | 20 | 0 | 2 | 3,655 | 1,436 | 785 | 0 | 38,138 ms (16.1 s Form before the fix, 21.7 s Groq incl. 20 s pacing) |
| 13 | same batch again, statistics fix in | 20 | 20 | 0 | 0 | 1,436 | 785 | 0 | 422 ms |
| 14 | drill: budget 1 token, version `drill` | 20 | 0 | 0 | 0 | 0 | 0 | 2,221 budget | 407 ms |
| 15 | drill: Store replaced by `SELECT 1/0` | | | | | | | | batch `failed`, run closed after 6.0 s (3 tries) |
| 16 | final state for T36 | 20 | 20 | 0 | 0 | 1,436 | 785 | 0 | 417 ms |

Funnel for the sample: 30,000 pairs → 14,165 candidates (Stage 1) → 10,405 clear match / 1,539 clear reject /
2,221 borderline (Stage 2) → 20 cohorts → **2 LLM calls, 3,655 tokens** → 1,436 eligible / 785 not eligible.
Asking per borderline pair would have been 2,221 calls (2.2 days of the 1,000-requests/day quota); per pair of
the whole batch, 30,000.

**What the model decided.** All 8 ICICI cohorts that miss only the score are eligible ("700 and above is
preferred" is a preference, not a minimum), down to the 660–669 band. Every cohort that misses ICICI's income
(₹29,000 vs ₹30,000) is not eligible ("Minimum monthly income of ₹30,000" is a requirement), including the 6 that
also miss the score. All 4 HDFC cohorts are not eligible: the firm sentence "you need a minimum credit score of
720 to be eligible" outweighs "above 720 is ideal", as the prompt's rule 2 asks. The verdicts are indicative, like
everything this engine sends; a stricter reading of "preferred" would be a prompt change and a new
`verdict_version`.

**Cross-check (run 16, independent SQL).** For all 2,221 borderline pairs the key's product, reason and
employment equal the pair's, the score and income bands re-derived from the user's raw values contain the user,
and the stored outcome and reason equal the cached verdict for `(cohort_key, content_hash)`: 2,221 of 2,221 each.

**Rejected.**
- *One call per borderline pair*: 2,221 calls for the sample, and the answers would repeat.
- *Bands on raw income × score × age* (the original plan): 1,028–5,528 cohorts per product (section "Matching
  and the Optimization Treasure Hunt").
- *Asking about the band as a whole*: a "yes" for 690–699 could then cover a 690 the model would have refused.
- *A loop with Merge to wait out 429s inline*: the retry and model fallback belong in the reusable LLM Gateway
  (T26); building them here would be thrown away, and pacing keeps the sample far from the limit.
- *A fixed `ANALYZE` schedule or waiting for autovacuum*: the statement that needs the statistics runs one
  second after the insert.

**Known gaps.**
- No live 429 for Stage 3: the branch is tested with the real 429 body and `retry-after` header observed in T30.
- The two probe calls made from a laptop before building (3,566 tokens) are not in `llm_calls`.
- When the prompt changes, `verdict_version` in `Form cohorts` must be bumped by hand; nothing enforces it.

## Workflow B persist: matches written from the database, final count read back

**Choice.** Two nodes after Stage 3. `Persist · Insert matches` copies every `clear_match` pair (`stage` = `rules`, reason from Stage 2) and every Stage 3 `eligible` pair (`stage` = `llm`, reason from the cohort verdict) from `match_candidates` into `matches` in one set-based `INSERT … SELECT … ON CONFLICT (user_id, product_id) DO NOTHING`. `Persist · Finalize run + mark matched` is one statement that sets `final_matches` to the number of qualifying pairs that really have a row in `matches`, stores `stage_ms.persist`, sets `finished_at` and moves the batch `matching → matched`. Migration `0005_final_matches` adds the CHECK `final_matches = stage2_clear + stage3_eligible`.

**Rejected.** (a) Reading pairs into n8n and inserting from a Code node: moves up to hundreds of thousands of rows through n8n memory for no gain. (b) `final_matches` computed from the same filter as the insert: it would repeat the insert's logic, so a bug in it would be invisible. Reading back through a join on `matches` and checking it against the Stage 2 and Stage 3 counts makes a lost pair fail the run. (c) `ON CONFLICT DO UPDATE`: would overwrite `notified_at` and `reason` of an existing match and could re-email a user.

**Why.** An existing match keeps its `batch_id` and `notified_at`, so a user who shows up in two batches is never emailed twice for the same product (Workflow C reads `notified_at IS NULL`). `unresolved_*` and `not_eligible` pairs are never stored: an unanswered question is not a match. Both nodes are idempotent, so Retry On Fail is safe on them. `persist` is timed from the insert's `statement_timestamp()` to after its commit, so foreign-key checks are included (the Stage 1 lesson).

**Hand-off.** `Notify · Run Workflow C` (added in T38) follows `Persist · Finalize run + mark matched` and starts Workflow C without waiting for it, so a slow or failing notification never changes how the matching run is reported.

**Measured (RDS, 10,000-user sample, run 17, then run 18 on the same batch).** 11,841 matches = 10,405 `rules` + 1,436 `llm`, for 6,017 distinct users; persist 504 ms the first time, 82 ms the second; the second run inserted 0 rows, made 0 LLM calls and still reports 11,841.

---

## Workflow C: compose and recipient guard

**Choice.** `C · Notification` is a sub-workflow (Execute Workflow Trigger) that Workflow B starts after the batch is `matched`. Stages: read and validate `batch_id` → load and validate the settings → claim `matched → notifying` with one conditional UPDATE → one SQL statement selects the first `max_emails_per_run` users (ordered by `user_id`) that still have unnotified matches in this batch on active products, with all their offers as JSON → a Code node writes subject, HTML and plain text and redirects every user to one of the test inboxes → a second Code node, the guard, throws unless every recipient is exactly one of those inboxes → release `notifying → matched`. Any error after the claim marks the batch `failed` with the message and ends in a Stop and Error node, so the execution itself shows as failed. This task composes and checks; it sends nothing and marks nothing notified. Sending, `notified_at`, the `DRY_RUN` branch and the `notified` status are T39.

**Settings in a table, not `$env`.** Migration `0006_app_config` creates `app_config(key, value jsonb, description, updated_at)` with exactly three keys: `dry_run` (boolean), `test_inbox_aliases` (non-empty array) and `max_emails_per_run` (whole number 1 to 9999). CHECK constraints enforce the types, so a bad value is refused when it is written, and the validate node refuses a missing or malformed row before anything is claimed. There is no default in code: with `DRY_RUN` unreadable, the run stops instead of guessing. Seed values are the safe ones: `dry_run = true`, the three SES-verified identities, 5 emails. `$env` is not used because `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` (the container environment holds the encryption key).

**Redirect and guard are two separate pieces.** The redirect picks `aliases[first 8 hex digits of user_id mod number of aliases]`, so a user always lands in the same inbox and the load spreads over all three. The guard does not trust that code: it re-reads the allowed list from the config node, not from the composed item, and requires every `to` to be a string equal to one of them (so `A@x.com`, `a@x.com,b@y.com` and `"a@x.com "` all fail), no `cc` / `bcc` / `replyTo` on any message and no more messages than the cap. It reports the count of problems and the first five. SES in sandbox is a third, AWS-side layer: it only delivers to the three verified identities.

**Rejected.** (a) One Postgres row per user flowing through n8n items: with zero waiting users no item would reach the release step and the batch would stay `notifying`. The select is an aggregate that always returns one row (an empty list when nothing waits), and the Code nodes keep one "run" item with an `emails` array; T39 splits it for sending. (b) Putting the allowed list into the composed item and letting the guard read it there: a bug in the compose step would then also widen the guard. (c) `waitForSubWorkflow: true` in B: B would be reported as failed because of an email problem, although matching succeeded. (d) Computing the redirect in SQL: the rule would be hidden in a query where it is harder to read and test than in the Code node next to the guard.

**Safety of the content.** Everything that came from a crawl or the CSV (lender, product, reason, user name, original address) is HTML-escaped; links are used only when the stored URL starts with `http://` or `https://`; a reason is cut to 240 characters. The original address appears once, in the `Intended for:` line, never as a recipient. Every subject starts with `[TEST]` and every body says it was redirected. The body carries the indicative-eligibility disclaimer.

**Limits.** Unnotified matches of products that became inactive are not offered (they stay unnotified). The composed run item is about 2 KB per email (one measured email: 1,165 characters of HTML plus the text), so a cap of 6,017 would be about 12 MB (estimate, not run); the demo cap is 5. The sub-workflow must be published, not just imported: n8n 2.44.4 answers an unpublished callee with `Workflow is not active and cannot be executed` (found on the first live run).

**Measured (RDS and the EC2 n8n, batch of the 10,000-user sample with 11,841 matches for 6,017 users).** Compose query execution: 12 ms at the demo cap of 5 and 228 ms at a cap of 6,017 (`EXPLAIN ANALYZE`). A live run composed 5 of 6,017 waiting users in 464 ms of node time plus a 1.5 s start of the first Code node (execution 74), checked all 5 and released the batch. A drill with the compose step addressing the original email was blocked by the guard (2 problems), the batch went `failed` with the message and the execution status was `error` (execution 76); the same batch again ended at `Stop · Nothing to do` with 0 claimed (execution 78). Workflow B then started Workflow C by itself on a throwaway batch (executions 79 and 80). Local: 84 new tests; 15 mutation probes on the exported workflow each fail at least one test.

## Workflow C sending: SES at the sandbox rate, send then mark

**Choice.** After the guard, `Send · Dry run?` sends a dry run to the T38 release (batch back to `matched`, nothing sent). A live run with nobody waiting goes straight to `Finish`. Otherwise `Send · One item per email` splits the run item, and `Send · Loop emails (one at a time)` (Loop Over Items, batch size 1) drives `Send · SES email` → `Send · Mark notified` → `Send · Pace 1 s (SES sandbox rate)` for each email. `Finish · notifying to notified` then moves the batch to `notified` and reads its counts back from the database: users and matches notified since the claim time (the claim now returns `now()`), and users still waiting. Migration `0007_from_address` adds the sender as a fourth `app_config` key with a CHECK that it is one address. The validate node refuses a missing or malformed sender, so it is not hard-coded in a node.

**SES access.** The native AWS SES node with `authentication: assumeRole` and the `aws-ses-assume-role` credential: the EC2 instance role assumes the SES-only role, so there are no static keys. The node takes one body part, HTML or text; the HTML is sent. The plain-text version stays in the run item, where a dry run shows it. The role's policy names the three verified identities as resources. A drill with an unverified sender was refused with `403 Forbidden` by IAM before SES judged the address (measured, execution 88).

**Send, then mark.** The mark is one UPDATE for exactly this user and the product ids that were in this email, and only where `notified_at IS NULL`. It is idempotent, so it may retry. It reads the email through n8n's paired item (`$('Send · One item per email').item`), never `.first()`, which would mark the first user on every pass (a wiring test and a mutation probe pin this). If n8n dies between a send and its mark, a manual rerun can send that one email again. No user is ever recorded as notified without a send.

**Status with a cap.** `notified` means "this run sent everything it was allowed to". `max_emails_per_run` (5 in the demo) and the sandbox's 200 messages per 24 h hold the rest back. `Finish` reports them as `users_still_waiting`, so the number is visible. To continue, set the batch back to `matched` and run C again: selection skips notified matches, so it carries on with the next users by `user_id`.

**Rejected.** (a) Mark, then send (at most once): a crash after the mark would record an email that was never sent, and the UI would report it as delivered. (b) Sending every item through one SES node call: nothing paces the calls, and the sandbox allows 1 message per second. (c) An HTTP Request to the SES v2 API to send HTML and text together: request signing through the Assume Role credential in that node is untested here, while the native node was tested in T24. Plain-text delivery is the cost. (d) A ledger table of SES message ids: not built. The ids are in the mark node's output and the execution data, which n8n prunes (`EXECUTIONS_DATA_PRUNE=true`).

**Retries.** SES and the mark use Retry On Fail (3 tries, 2 s). On n8n 2.44.4 the retries run before the error output: the refused send took 4,634 ms, which is 3 attempts with two 2 s waits (measured). After an error response a retry cannot duplicate an email. After a timeout whose request SES did accept, it could (not observed). Claim, release, fail and finish do not retry; they change state once.

**Measured (EC2 n8n, RDS, real SES sandbox).** Dry run, throwaway batch of 2 synthetic users: release path, 0 sent (execution 82). Live, same batch: 2 SES message ids, 3 matches marked, marks 1.22 s apart, batch `notified` (execution 84). Same batch set back to `matched` and run again: 0 waiting, 0 sent, `Finish` straight from `Send · Anything to send?` (execution 86). Unverified-sender drill: batch `failed` with the message, match still unnotified, execution `error` (execution 88). Real 10,000-user sample batch, cap 5: 5 emails (SES node 181 to 412 ms each, mark 14 to 33 ms), 10 matches marked, 6,012 users still waiting, batch `notified`, 8.4 s for the whole execution (execution 90). Local: 29 new tests; 17 mutation probes on the exported workflow each fail at least one test.

**Deliverability (observed).** The emails reach the Gmail test mailbox but Gmail files them in Spam (user screenshot, `docs/screenshots/t39-gmail-drill-email-in-spam.png`). Likely cause, not verified from the headers: the sender is a `@gmail.com` address sent through SES, so the message is not DKIM-signed for `gmail.com` and fails DMARC alignment. Production fix: an SES domain identity on an owned domain with Easy DKIM, SPF through a custom MAIL FROM domain and a DMARC record. Designed, not implemented (no domain in this project).

## DLQ handling (T21)

- **Where the batch is failed:** `loadChunk` itself, on the fifth receive (`MAX_RECEIVES`, pinned equal to `maxReceiveCount` by `tests/unit/test_dlq_config.py`). Rejected alternative: a Lambda consuming `ingest-dlq`, which needs another VPC function, role and ENI cost just to run one UPDATE. If the database is the thing that is down, the UPDATE cannot be recorded; this is logged as `give_up_unrecorded` and the DLQ alarm is the only signal.
- **Alarms:** `ApproximateNumberOfMessagesVisible > 0` on `ingest-dlq` and `split-failures`, 60 s period. They have no SNS action, so they show in the console and `describe-alarms` but nobody is paged; that is stated in the README.
- **Redrive:** `scripts/redrive_dlq.sh` uses `sqs start-message-move-task`. It cannot revive a failed batch (`start_loading` refuses it, the chunk is logged `chunk_skipped` and acknowledged), so it helps only when the batch is still `loading`, for example after a transient outage that did not exhaust the other chunks.
- **Finding from the drill:** the loader role has `s3:GetObject` but no `s3:ListBucket`, so S3 answers a missing key with `AccessDenied`, which the loader treats as retryable, not `NoSuchKey`. A replaced or deleted object therefore burns five receives before failing the batch instead of failing at once. Granting ListBucket on `uploads/*` would fix that; not done, recorded here.
