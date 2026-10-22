# Loan Eligibility Engine

Submission for the Clickpe.ai engineering-intern assignment.

An admin uploads a CSV of users in a browser. The file goes straight to S3, is split into 5,000-row chunks, and is loaded in parallel into a private PostgreSQL database by Lambda. When the last chunk lands, exactly one webhook starts an n8n pipeline that matches every user against loan products crawled from lender websites. A funnel of SQL, deterministic rules and a heavily cached LLM stage decides who is eligible. Matched users are emailed through SES, redirected to a test inbox only.

Everything below was run on a real AWS account (`ap-southeast-2`). Numbers come from real runs, and the command or task that produced each one is in [PROGRESS.md](PROGRESS.md). What is designed but not built is listed under [Limitations](#limitations).

| Measured on the 10,000-user sample CSV | Value |
|---|---|
| Upload → `processed` (2 chunks, 10,000 rows) | 6.9 s |
| Upload → `notified`, whole pipeline end to end | 41.5 s |
| User × product pairs | 30,000 |
| After the SQL pre-filter | 14,165 |
| Resolved by rules without an LLM | 11,944 (10,405 clear match + 1,539 clear reject) |
| Borderline pairs sent to the LLM stage | 2,221, as 20 cohorts, in 2 Groq calls (3,536 tokens) |
| Final matches | 11,841 for 6,017 users |
| Re-upload of the same file | 0 rows inserted, 0 updated, 0 LLM calls, 0 emails |

## Architecture

![Architecture: browser upload to S3, SQS fan-out to load-chunk, private RDS, n8n workflows A, B, C and E on EC2, SES to the test inbox](docs/screenshots/loan-eligiblity-engine.svg)

Editable source: [docs/architecture.excalidraw](docs/architecture.excalidraw). The Mermaid diagram below is the detailed version, including the Error Workflow links.

Full detail, private-versus-public table and the list of designed-but-not-built items: [docs/architecture.md](docs/architecture.md).

```mermaid
flowchart TB
    user(["Browser<br/>ui/index.html"])
    lenders[("Lender sites<br/>ICICI, HDFC, IDFC FIRST")]
    groq[["Groq API<br/>strict JSON schema"]]
    inbox(["Test Gmail inbox<br/>+one / +two aliases"])
    admin(["Admin laptop<br/>SSM Session Manager"])

    subgraph aws["AWS ap-southeast-2"]
        direction TB

        subgraph pub["Outside the VPC"]
            split["Lambda split-csv<br/>512 MB, 300 s"]
        end

        s3[("S3 uploads bucket<br/>uploads/{batch_id}.csv<br/>private, TLS only, 7-day expiry")]
        q[["SQS ingest-queue<br/>one message per 5,000-row chunk"]]
        dlq[["SQS ingest-dlq<br/>after 5 receives"]]
        sf[["SQS split-failures<br/>split-csv onFailure destination"]]
        ses["Amazon SES<br/>sandbox"]
        ssm["SSM Session Manager"]

        subgraph vpc["Default VPC 172.31.0.0/16 (no NAT Gateway)"]
            direction TB
            s3gw{{"S3 Gateway Endpoint<br/>free"}}

            subgraph lsg["Lambda SG: egress 5432, 5678, S3 prefix list"]
                load["Lambda load-chunk<br/>ESM batch 1, MaximumConcurrency 3"]
                getUrl["Lambda get-upload-url<br/>Function URL (public, CORS)"]
                status["Lambda batch-status<br/>Function URL (public, CORS)"]
            end

            subgraph rdsg["RDS SG: no inbound except Lambda SG and n8n SG"]
                rds[("RDS PostgreSQL 16<br/>db.t4g.micro, private<br/>TLS verified")]
            end

            subgraph ec2["EC2 t4g.small, n8n in Docker, no inbound rules"]
                direction TB
                wfA["Workflow A<br/>Product discovery"]
                wfB["Workflow B<br/>Matching"]
                wfC["Workflow C<br/>Notification"]
                wfE["Workflow E<br/>Error handler"]
                wfG["Workflow G<br/>LLM Gateway (sub-workflow)"]
            end
        end
    end

    user -- "1. POST get-upload-url" --> getUrl
    getUrl -- "create batch (pending)" --> rds
    user -- "2. presigned POST: key, text/csv, size policy" --> s3
    s3 -- "ObjectCreated" --> split
    split -- "ranged read, quote-aware scan" --> s3
    split -- "chunk messages" --> q
    split -. "async failure" .-> sf
    q -- "SQS event source mapping" --> load
    q -- "maxReceiveCount 5" --> dlq
    load -- "ranged GET" --> s3gw
    s3gw --> s3
    load -- "COPY to staging, upsert users, chunk ledger" --> rds
    load -- "last chunk: HTTP POST :5678<br/>Bearer JWT, HS256, 60 s" --> wfB
    user -- "poll GET batch-status" --> status
    status -- "read-only counts, funnel" --> rds

    wfA -- "daily 06:00 IST crawl" --> lenders
    wfA -- "Execute Workflow: structure criteria" --> wfG
    wfA -- "upsert loan_products, crawl_runs" --> rds
    wfB -- "Stage 1 SQL, Stage 2 rules, Stage 3 cohorts" --> rds
    wfB -- "Execute Workflow: uncached cohorts only" --> wfG
    wfG -- "strict schema; 429: retry-after wait, then 20b fallback" --> groq
    wfG -- "24 h budget read, one llm_calls row per attempt" --> rds
    wfB -- "Execute Workflow" --> wfC
    wfC -- "matches, app_config" --> rds
    wfC -- "AssumeRole clickpe-n8n-ses-role" --> ses
    wfA -. "Error Workflow" .-> wfE
    wfB -. "Error Workflow" .-> wfE
    wfC -. "Error Workflow" .-> wfE
    wfG -. "Error Workflow" .-> wfE
    wfE -- "n8n_errors row" --> rds
    wfE -- "one alert email, test alias" --> ses
    ses -- "redirected recipients only" --> inbox
    admin -- "port forward 5678" --> ssm
    ssm -.-> ec2
```

## Repo map

| Path | What it holds |
|---|---|
| [serverless.yml](serverless.yml) | The whole AWS ingestion stack: bucket, queues, four Lambdas, IAM roles, security group, S3 Gateway Endpoint, alarms. RDS and the n8n host are created by the scripted CLI commands in `infra/`, so `sls remove` can never delete them |
| [lambdas/](lambdas) | `get_upload_url`, `split_csv`, `load_chunk`, `batch_status` (thin handlers) and `shared/` (pure, unit-tested logic) |
| [db/](db) | `schema.sql`, numbered migrations, `seed_products.sql`, the checksummed migration runner `migrate.py` |
| [n8n/](n8n) | `docker-compose.yml` and the five exported workflows: A (product discovery), B (matching), C (notification), E (error handler) and G (LLM Gateway) |
| [ui/](ui) | One static page, no framework |
| [infra/](infra) | Step-by-step records and scripts for RDS, EC2, n8n, and the IAM policy documents |
| [scripts/](scripts) | `smoke_test.sh`, `benchmark_run.sh`, `benchmark.md`, `gen_synthetic_users.py`, `measure_naive_llm.py`, `rds_query.sh`, `redrive_dlq.sh`, `retrigger_batch.sh`, `serve_ui.sh`, `set_db_role_passwords.sh`, `verify_workflow_import.sh`, `check_package.py` |
| [tests/](tests) | Unit tests, PostgreSQL-backed integration tests, CSV fixtures |
| [docs/](docs) | `decisions.md` (every choice, the rejected option and the evidence), `architecture.md`, `data-notes.md`, `stage1-explain.md`, `rubric-evidence.md`, screenshots |
| [PROGRESS.md](PROGRESS.md) | Per-task log with commands and trimmed output for every number in this README |

## Prerequisites

- An AWS account and a CLI profile named `clickpe`. This account is locked by an organisation SCP to `ap-southeast-2`; the region is one value in `serverless.yml`.
- Three SES identities verified in that region: a Gmail address and its `+one` and `+two` aliases. SES stays in the sandbox, which is a second guard against mailing real users.
- A Groq API key.
- Local tools: Node.js 22, `uv`, Docker, `jq`, `curl`, Python 3.12, and the AWS CLI v2 with the Session Manager plugin (every RDS and n8n command goes through SSM).
- The sample `users.csv` in `data/`. The folder is gitignored because the file is personal data.

```bash
git clone https://github.com/rudrakshSoni-dev/loan-eligiblity-engine-clickpe.git
cd loan-eligiblity-engine-clickpe
make install
```

## Deploy AWS

The account's default VPC is used, so no VPC is created. Replace the IDs in `serverless.yml` (`vpcId`, `subnetIds`, `mainRouteTableId`, `s3PrefixListId`) if you deploy to another account.

Secrets live in SSM Parameter Store as SecureStrings and are resolved at deploy time. Create them once. The database host and webhook URL are placeholders until RDS and EC2 exist:

```bash
export AWS_PROFILE=clickpe AWS_REGION=ap-southeast-2 AWS_PAGER=""
aws ssm put-parameter --name /clickpe/db/host --type String --value placeholder --overwrite
aws ssm put-parameter --name /clickpe/db/password --type SecureString --value "$(openssl rand -hex 24)" --no-overwrite
aws ssm put-parameter --name /clickpe/n8n/webhook_url --type String --value http://placeholder:5678/webhook/match-batch --overwrite
aws ssm put-parameter --name /clickpe/n8n/webhook_secret --type SecureString --value "$(openssl rand -hex 32)" --no-overwrite
aws ssm put-parameter --name /clickpe/db/app_ingest_password --type SecureString --value "$(openssl rand -hex 32)" --no-overwrite
aws ssm put-parameter --name /clickpe/db/app_n8n_password --type SecureString --value "$(openssl rand -hex 32)" --no-overwrite
```

`/clickpe/db/password` belongs to the RDS master user `clickpe`, which only runs migrations and operator queries. The Lambdas log in as `app_ingest` and n8n as `app_n8n` (created by migration `0009_app_roles`). `webhook_secret` is the HS256 key that signs the Lambda's 60-second webhook token; it is never sent.

1. **RDS.** Run the commands in [infra/rds.md](infra/rds.md). It creates a private `db.t4g.micro` PostgreSQL 16 instance and writes its endpoint to `/clickpe/db/host`.
2. **EC2 for n8n.** Launch the `t4g.small` instance with the commands under "Launch commands" in [infra/ec2.md](infra/ec2.md) (rebuilt from the live instance, not re-run), then run `infra/ec2/setup.sh` on it through SSM Run Command (the exact command is in that file). The instance has no inbound rules.
3. **Webhook URL.** Put the instance's private IP into `/clickpe/n8n/webhook_url`:

    ```bash
    aws ssm put-parameter --name /clickpe/n8n/webhook_url --type String --overwrite \
      --value http://<ec2-private-ip>:5678/webhook/match-batch
    ```

4. **Deploy the stack:**

    ```bash
    make package
    npx serverless deploy
    ```

5. **Open the database and n8n ports by security-group reference.** The three `authorize-security-group-ingress` commands (5432 from n8n and from the Lambda group, 5678 from the Lambda group) are at the end of "Launch commands" in [infra/ec2.md](infra/ec2.md).
6. **Migrate the schema from inside the VPC** with `infra/ec2/migrate.sh`, sent through SSM as described in [infra/ec2.md](infra/ec2.md). Running it twice applies 0 migrations the second time. The 5 seed products are flagged `is_seed` and labelled "Seed ·" in their names. Then give the two application roles their passwords from SSM:

    ```bash
    scripts/set_db_role_passwords.sh
    ```

   It sends PostgreSQL a SCRAM-SHA-256 verifier computed on the instance, never the password, and ends with `PASS` once both roles log in over verified TLS.
7. **Smoke test:**

    ```bash
    scripts/smoke_test.sh data/users.csv
    ```

   It calls the Function URLs, uploads with a presigned POST, polls until `processed`, and fails unless `rows_ok + rows_rejected` equals the CSV row count.

## Launch n8n and configure credentials

n8n runs as the exact image `docker.n8n.io/n8nio/n8n:2.44.4` from [n8n/docker-compose.yml](n8n/docker-compose.yml). The compose file is sent to the instance and started as shown in [infra/n8n.md](infra/n8n.md) ("Start / update"). The encryption key is generated on the instance and never leaves it.

Open the editor through an SSM port forward. There is no internet path to it:

```bash
N8N_INSTANCE_ID=i-02ffa9d08e8403a4a
aws ssm start-session --profile clickpe --region ap-southeast-2 --target "$N8N_INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["5678"],"localPortNumber":["5678"]}'
```

`i-02ffa9d08e8403a4a` is the demo instance; in another account use your own instance id. Without `--region` (or `AWS_REGION`) the CLI stops with `NoRegion`. The command needs the AWS Session Manager plugin installed locally; leave the terminal open while you use the editor. If something on your machine already listens on port 5678 (for example a local n8n), `localhost:5678` opens that instead: change only `localPortNumber` to `5679` and browse to `http://localhost:5679`. `portNumber` stays `5678`, because that is where n8n listens on the instance.

Browse to `http://localhost:5678`, create the owner account and enable 2FA under Settings → Personal (this step is done in the browser). Then create four credentials by name, because workflows refer to the names only. Screenshots with values masked are in [docs/screenshots/](docs/screenshots).

| Credential | Type | Notes |
|---|---|---|
| `rds-postgres` | Postgres | RDS host from SSM, database `clickpe`, user `app_n8n` with the password from `/clickpe/db/app_n8n_password`, SSL `require`, Ignore SSL Issues off. The container trusts the RDS CA through `NODE_EXTRA_CA_CERTS` |
| `aws-ses-assume-role` | AWS (Assume Role) | Use System Credentials on; role `clickpe-n8n-ses-role`. The EC2 instance role assumes an SES-only role, so there are no static AWS keys. Policies are in [infra/iam/](infra/iam) |
| `webhook-jwt` | JWT Auth | Key type Passphrase, algorithm HS256, secret from SSM `/clickpe/n8n/webhook_secret`. [infra/n8n.md](infra/n8n.md) ("Security review (T45)") creates it from SSM with the CLI, so the value is never typed or shown |
| `groq-api` | Header Auth | Header `Authorization`, value `Bearer <key>` |

## Import the workflows

The public API is off, so workflows are imported with the n8n CLI inside the container through SSM Run Command. The exact commands for import, publish and restart are in [infra/n8n.md](infra/n8n.md) ("Importing and running a workflow", "Publishing Workflow B", "Workflow C"). Order matters:

1. Import and publish Workflow E (`wferrorhandler01`), because the others name it as their Error Workflow and n8n skips one that is not published.
2. Import and publish the LLM Gateway (`wfllmgateway01`), because A and B call it by id and a callee must be published.
3. Import and publish Workflow C (`wfcnotification01`), because B calls it by id.
4. Import and publish Workflow B (`wfbmatching001`), then restart n8n so the webhook is registered.
5. Import Workflow A (`wfaproductdisc01`). It runs daily at 06:00 IST, or on demand with `n8n execute`.

`docker exec n8n n8n list:workflow --active=true` must list B, C, E and the LLM Gateway.

To prove the exported files load into a clean n8n without touching your instance:

```bash
scripts/verify_workflow_import.sh
```

## Run the demo

1. Run Workflow A once so `loan_products` holds real products, not only seed data.
2. Start the UI against the deployed Function URLs. This writes a local `ui/config.js` and serves `http://localhost:8000`, the only CORS origin:

    ```bash
    scripts/serve_ui.sh
    ```

3. Choose `data/users.csv`. The page checks the extension, size (20 MB) and header row, uploads with a progress bar, and shows the timeline `uploading → loading x/y chunks → processed → matching → matched → notified`, the row and reject counts, and the funnel with per-stage milliseconds.
4. Emails are not sent until `dry_run` is turned off in the database. Sending is capped by `max_emails_per_run` and every recipient is redirected to the three verified test inboxes:

    ```sql
    UPDATE app_config SET value = 'false' WHERE key = 'dry_run';
    UPDATE app_config SET value = 'true' WHERE key = 'dry_run';
    ```

    Run the first statement to send and the second to turn sending off again, for example with `scripts/rds_query.sh "<SQL>"`, which runs psql on the n8n host through SSM.

    Uploading a file the database already holds is a no-op by design: 0 rows inserted or updated, so 0 pairs, 0 matches and 0 emails. To see new matches and emails, upload users the database has never seen. A new seed gives new user ids, and every address ends in `@example.invalid`:

    ```bash
    uv run python scripts/gen_synthetic_users.py --rows 50 --seed 20261024 --output data/demo_new_users.csv
    ```
5. If n8n was down when a batch finished loading, the batch stays `processed`. Re-send the trigger with `scripts/retrigger_batch.sh <batch_id>`.

## Design decisions

Each choice, the option rejected and the evidence is in [docs/decisions.md](docs/decisions.md) (the decision log, with claims marked cited, measured or estimate). The ones a reviewer is most likely to ask about:

### Ingestion pattern

- **Presigned S3 POST, not a Lambda or API Gateway upload.** The browser uploads straight to S3, bypassing the 10 MB API Gateway and 6 MB Lambda payload limits. Only POST policies let S3 itself enforce the exact key, `text/csv` and a 1 B to 20 MB size range. Checked against real S3: valid file 204, 22 MB file `400 EntityTooLarge`, wrong type or key `403`.
- **S3 → `split-csv` → SQS → `load-chunk`.** The splitter walks the file with the same `csv.reader` the loader uses, so quoted newlines never break a chunk, and emits one message per 5,000 records with exact byte offsets. Each loader reads only its range, so a file's size is bounded by S3, not by one Lambda's timeout. Failed chunks retry individually and land in a DLQ after 5 receives.
- **COPY into a staging table, then one deduplicating upsert,** in one transaction per chunk. It compares data columns only, so re-uploading the identical file reports 0 inserted and 0 updated.
- **Concurrency is capped with the SQS event source mapping's `MaximumConcurrency: 3`.** Reserved concurrency is impossible here: AWS requires 100 unreserved units and this account's limit is 10 (measured). The cap also bounds RDS connections (`max_connections` is 79).
- **Exactly one trigger per batch.** Every chunk writes a `chunk_loads` ledger row in its own transaction. The invocation whose conditional `UPDATE … SET status='processed' WHERE status='loading' AND <ledger count> = total_chunks RETURNING id` gets a row back is the only one that calls n8n. Tested with 10 batches of 5 chunks delivered twice by 10 concurrent workers: exactly 10 POSTs. A mutation probe that weakens the guard gives 2 to 4 POSTs per batch.
- **Validation rejects, it does not stop.** Bad rows are stored in `rejected_rows` with the exact file line number and every broken field; good rows in the same file still load. A malformed fixture loaded 1 row and stored 10 rejects.

### No-NAT VPC design

A NAT Gateway and interface endpoints cost money for no benefit here. Lambdas that send to SQS (`split-csv`) run outside the VPC and never touch RDS. Lambdas that need RDS run inside the VPC and need no internet: S3 goes through the free Gateway Endpoint, SQS delivery to `load-chunk` is done by the Lambda service, and presigning is local signing. n8n sits in a public subnet with an outbound-only public IP, so it reaches Groq, the lender sites, SES and SSM through the free Internet Gateway while accepting nothing inbound.

### Crawling strategy

Three lenders are crawled with a plain GET from the n8n instance's own IP: ICICI, HDFC and IDFC FIRST. BankBazaar is a disabled spare. Each page's robots.txt was parsed per path and allows it. Every bank now redirects to a `bank.in` domain, so the site list stores final URLs. One CSS selector per site only narrows the page to the eligibility region; a text-anchored normaliser decides what counts as a criterion, and a redesign that breaks a selector produces `no_criteria_found` instead of a silent empty result. Kotak was rejected because its static HTML has no income, age or score criteria. Per-site failure branches mean one dead site never stops the others (drill: HDFC unreachable, ICICI and IDFC FIRST still upserted). Products are never deleted; after 3 consecutive failed crawls a product becomes inactive and is reactivated by the next good crawl. **Change detection (T29):** before any Groq call, Postgres compares the SHA-256 of the normalised criteria text with the stored `content_hash`; an unchanged page only bumps `last_seen_at` and logs `crawl_runs` with `changed = false, llm_calls = 0`. Measured on the instance: three unchanged lenders made 0 Groq calls (executions 131, 139), one forced change made exactly 1 (execution 133), and a failing lookup fell back to the LLM for all 3 instead of skipping them (execution 135).

### Optimization Treasure Hunt

The obvious design asks an LLM about every user and product pair. The measured Groq free-tier limits make that impossible: 30 requests a minute, 1,000 a day, 8,000 tokens a minute, 200,000 tokens a day, per model. For 10,000 users and 3 products that is 30,000 calls, which is 30 days of the daily quota for one upload.

So the engine spends tokens only on what columns cannot express:

1. **LLM at ingest, not at match time.** Workflow A structures a product's criteria once, with a strict JSON schema (`temperature 0`, `reasoning_effort low`).
2. **Stage 1, SQL.** One set-based `INSERT … SELECT` pairs users and active products on the hard criteria (NULL means no limit) and keeps near misses within 5% of an income or score threshold. Pairs stay in Postgres.
3. **Stage 2, rules.** An indicative EMI check (₹5,00,000 over 60 months at the published rate, capped at 65% of income, a figure BankBazaar publishes) and a classifier set in SQL: `clear_match`, `clear_reject` or `borderline`. Products with `parse_confidence` of at least 0.70 resolve borderline pairs without an LLM.
4. **Stage 3, cohorts.** Borderline pairs are grouped by product, borderline reason, employment and a coarse band of the triggering feature, not by raw values, which would give 1,028 to 5,528 cohorts per product on this data (measured). One strict-schema request per product. Every Groq call in the system goes through one LLM Gateway sub-workflow, which checks the answer against the schema, waits out a 429 for Groq's `retry-after` (at most 60 s, 3 times), then falls back to `gpt-oss-20b`, refuses calls the 24 h budget cannot cover, and writes one `llm_calls` row per attempt.
5. **Cache.** `cohort_verdicts` is keyed by cohort and the product's content hash, so a product change invalidates its verdicts and a re-upload costs zero calls.
6. **Budget guard.** Pairs left when the token or call budget is spent are recorded as `unresolved_budget`, never guessed.

Measured on the real CSV. Counts and tokens are from the end-to-end run (Workflow B execution 94); stage times are from the T33 to T36 runs on RDS:

| Stage | Result |
|---|---|
| All pairs (10,000 users × 3 active products) | 30,000 |
| Stage 1 SQL | 14,165 candidates (10,405 strict, 3,760 near miss), 578 ms |
| Stage 2 rules | 10,405 clear match, 1,539 clear reject, 2,221 borderline, 625 ms |
| Stage 3 cohorts | 2,221 pairs → 20 cohorts → 2 Groq calls, 3,536 tokens |
| Verdicts | 1,436 eligible, 785 not eligible |
| Final | 11,841 matches for 6,017 users |
| Same batch again | 0 inserted, 0 LLM calls, 20 of 20 cohort cache hits |

Per-pair asking would be 2,221 calls for the borderline pairs alone. Per-stage timings are stored in `pipeline_runs.stage_ms` and shown in the UI. Finding a stale planner statistic that made cohort forming take 16 s, and adding an `ANALYZE` node that brought it to 168 ms, is in [docs/decisions.md](docs/decisions.md) → "Workflow B Stage 3".

**At 100,000 users** (synthetic data, [scripts/benchmark.md](scripts/benchmark.md)): the file went from the end of the upload to `processed` in 20.8 s (20 chunks, 3 concurrent loaders, mean 340 ms per chunk) and the batch was `matched` 72.3 s after the upload started. The funnel was 300,000 pairs → 139,918 → 102,371 clear match / 15,165 clear reject / 22,382 borderline → 22 cohorts → **1 Groq call** (20 cohorts came from the cache) → 116,850 matches; Stage 1 took 5,955 ms and Stage 2 5,714 ms, about 10× the 10,000-user times. Asking the LLM about every pair would be 300,000 calls and 278.4 M tokens (1,392 days of the daily token quota), priced from 10 measured single-pair calls at 928.1 tokens each. Re-uploading the same file inserted and updated 0 rows. A cold-cache run at 100,000 users was not made.

## Security

- **Upload.** Presigned POST pinned to one key, content type and size range, valid 5 minutes. The bucket blocks all public access, enforces TLS and expires uploads after 7 days.
- **Database.** RDS is not publicly accessible; public DNS resolves only to a private address, and a laptop gets `No route to host`. `rds.force_ssl` is on, `sslmode=disable` is rejected, and clients verify the RDS CA (`verify-full`); every live client session reads TLSv1.3 in `pg_stat_ssl`. Port 5432 is open to the Lambda and n8n security groups by reference only.
- **Least-privilege database roles (T45).** The Lambdas log in as `app_ingest` and n8n as `app_n8n`, each with only the table privileges its SQL needs (no DELETE, TRUNCATE or DDL, connection limits 10 and 20). Workflow B refreshes planner statistics through a `SECURITY DEFINER` function, because PostgreSQL 16 lets only the table owner ANALYZE. A test plans every SQL statement in the exported workflows as `app_n8n`, so a missing grant fails the build.
- **n8n.** The security group has zero inbound rules from the internet. The editor is reachable only through an SSM Session Manager port forward, with one owner account that has 2FA on (`mfaEnabled = 1` in n8n's user table, checked in T45). Port 5678 accepts the webhook from the Lambda security group alone. The container runs as the non-root `node` user, unprivileged.
- **Webhook, four layers.** Security group, n8n IP allowlist (VPC CIDR), a JWT signed by the Lambda (HS256, valid 60 s, naming the batch), and a claim that refuses unless the batch is `processed` (a replay gets 409). Workflow B also refuses a token whose `batch_id` differs from the body's. The key itself never travels, so the request headers n8n saves in each execution hold only an expired, single-batch token.
- **IAM.** One role per Lambda, no wildcard actions. The only `*` resource is the three network-interface actions every VPC Lambda requires. The EC2 instance role assumes an SES-only role limited to three verified identities, so there are no static AWS keys.
- **Email safety.** Every recipient is redirected to the verified test aliases, a guard node re-reads the allowed list and throws on any other recipient, any cc, bcc or reply-to, or more messages than the cap. The guard blocked a deliberately wrong address in a drill, and SES would refuse unverified identities anyway.
- **Secrets.** SSM SecureStrings, resolved at deploy. They are also present as literals in the deployed CloudFormation template, which is documented in `docs/decisions.md` → "Secrets".
- **Public by design.** The `get-upload-url` and `batch-status` Function URLs are `AuthType NONE`, because the browser has no AWS credentials. CORS is pinned to the UI origin, `lambda:InvokeFunction` requires `InvokedViaFunctionUrl`, and the upload is bounded by the POST policy. API Gateway with auth and throttling is the production upgrade.
- **Security review (T45).** Every item was checked against the live account, with the command and its output recorded in `docs/decisions.md` → "Security review (T45)". It fixed three findings: the webhook secret stored in n8n executions (replaced by signed tokens, key rotated), the Lambdas and n8n logging in as the RDS master user (now separate roles), and the missing account-level S3 Block Public Access (now on). Open residual risks are listed there with their fix. The main ones: the n8n host can read the SSM SecureStrings through `AmazonSSMManagedInstanceCore`; the admin IAM user has an access key and no MFA; there is no CloudTrail trail beyond the 90-day event history.

## Cost

No NAT Gateway, no Multi-AZ, no provisioned IOPS, no interface VPC endpoints, and nothing larger than `t4g.small`. Prices are `ap-southeast-2` list prices read from the AWS Price List API on 2026-10-22; the arithmetic, every unit price and the sources are in `docs/decisions.md` → "Cost (T46)". Cost Explorer showed $0 for October, so these are list prices, not invoices.

| Line | $ / month |
|---|---|
| EC2 `t4g.small` (n8n), 730 h | 15.48 |
| EBS 20 GB gp3 | 1.92 |
| Public IPv4 on the n8n host | 3.65 |
| RDS `db.t4g.micro`, Single-AZ | 18.25 |
| RDS 20 GB gp3 | 2.76 |
| 2 CloudWatch alarms | 0.20 |
| Lambda, SQS, S3, SES sandbox | under 0.01 |
| **Demo stack, running all month** | **42.26** |
| Same stack at 1M users a month (ten 100,000-row files), without email | about 42.3 |
| Plus SES if every matched user were mailed (601,700 recipients at $0.10 per 1,000) | 60.17 |

The fixed cost is the database and the n8n host (91%); usage-based items are cents. The design choices that keep it there, priced: one NAT Gateway would add $43.07 a month before any data; asking Groq about every pair at 1M users would cost $585.18 on `gpt-oss-120b` (measured 804 + 124.1 tokens per pair), and about $43.66 even for borderline pairs only, against under $0.01 for the cohort pipeline. Not run: anything above 100,000 users, so whether a `db.t4g.micro` copes at 1M is untested, and the 1M-user totals assume it does.

## Testing

```bash
make check
```

runs `ruff check`, `ruff format --check`, `mypy` (strict) and `pytest` with a 95% branch-coverage floor on all of `lambdas` (the four handlers and `lambdas/shared`).

Tests that need PostgreSQL create a throwaway database per test and are skipped without a server:

```bash
docker run -d --rm --name pg -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:16
TEST_DB_HOST=127.0.0.1 TEST_DB_PORT=55432 TEST_DB_PASSWORD=test make check
```

Result of the last run (T44, 2026-10-22): `All checks passed!`, `99 files already formatted`, `Success: no issues found in 82 source files`, **`691 passed`** and **100.00% branch coverage** of `lambdas` (1,209 statements, 222 branches, 0 missed). Without a database, `448 passed, 243 skipped` and 98% (the uncovered lines are in `load_chunk/handler.py`, covered by the database tests).

The SQL and Code nodes inside the exported workflows are tested where they live: the exported SQL runs on PostgreSQL 16 and the exported Code nodes run under Node.js inside pytest. Mutation probes (weakening a guard on purpose) were run for the critical paths, and each one failed at least one test.

## Limitations

Stated plainly, because these are known:

- **DLQ alarms have no notification target (T21).** The CloudWatch alarms on `ingest-dlq` and `split-failures` go to ALARM (drilled) but notify nobody yet. Redriving with `scripts/redrive_dlq.sh` cannot revive a batch that is already `failed`: the loader skips it, so the file must be uploaded again.
- **Workflow E sees only unhandled failures (T25).** It records failed automatic executions of A, B, C and the LLM Gateway in `n8n_errors` and sends one alert to a test alias. A failure a workflow handles itself (for example Workflow B marking a batch `failed` and ending normally) is not an n8n error, so E does not see it. E must be published, not only imported: n8n 2.44.4 skips an unpublished Error Workflow.
- **The 20b fallback was proven only on a throwaway copy (T26).** A real 429 ("TPM: Limit 8000, Used 4797, Requested 5049", `retry-after` 14 s) was waited out live and the retry answered. The switch to `gpt-oss-20b` was drilled with waits disabled in a copy of the gateway. A verdict produced by the 20b model is cached like any other.
- **Change detection is keyed on the criteria text only (T29).** If the prompt or model changes, an unchanged page is not re-structured until its `content_hash` is cleared or the text changes.
- **Demo data.** The 5 seed products are fake and labelled so. Only three lenders are crawled. A lender's published rate is missing for ICICI and HDFC, so their rows have a lower `parse_confidence` and an EMI check of "not checked".
- **Matches are indicative.** The eligibility rules use public criteria text and stated assumptions; they are not a credit decision.
- **Sandbox email.** SES is in the sandbox and the test emails landed in Spam in the Gmail inbox (screenshot in `docs/screenshots/`); the likely cause is missing DKIM on the sender and the fix is documented.
- **Single region.** The account is SCP-locked to `ap-southeast-2`. The production target would be `ap-south-1` for latency and RBI data localisation.
- **Scale measured only to 100,000 users** (`scripts/benchmark.md`). The design is chunked and bounded, but nothing larger has been run, and the 1M-user cost figures are arithmetic on those measurements.

## Future work

- Close the residual risks of the security review.
- API Gateway with authentication and throttling in front of the Function URLs.
- A transactional outbox for the n8n trigger instead of the documented retrigger script.
- Multi-AZ RDS, Secrets Manager with rotation, and DKIM on a verified domain for SES production access.
- Step Functions Inline Map for fan-out, the runner-up considered in `docs/decisions.md`.
- RDS, the n8n host and the SES role as a separate, termination-protected CloudFormation stack instead of the scripted CLI commands in `infra/`.
