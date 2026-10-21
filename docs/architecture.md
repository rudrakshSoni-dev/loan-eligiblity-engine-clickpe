# Architecture

Region `ap-southeast-2`, stack `clickpe-loan-engine`, default VPC `vpc-0cddb8b4387b5bbdc` (`172.31.0.0/16`).
Every box below exists in `serverless.yml`, `infra/` or `n8n/workflows/`; items not built are drawn dashed and
listed under "Designed, not implemented".

## System diagram

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

## Private versus public

| Component | Reachable from the internet? | Control |
|---|---|---|
| S3 bucket | No (public access blocked, TLS-only policy); upload only through a 5-minute presigned POST | Exact key, `text/csv`, `content-length-range` 1 B to 20 MB |
| `get-upload-url`, `batch-status` Function URLs | Yes, `AuthType NONE`, CORS pinned to the UI origin | Documented as public; production upgrade is API Gateway with auth and throttling |
| `split-csv`, `load-chunk` | No URL; invoked by S3 and SQS only | Resource policy for S3, event source mapping for SQS |
| RDS | No (private address only, `PubliclyAccessible false`) | SG allows 5432 from the Lambda SG and n8n SG only; `rds.force_ssl` on, `verify-full` from clients |
| n8n webhook `:5678` | No | SG allows it from the Lambda SG only; VPC-CIDR allowlist; HS256 JWT signed per call (60 s, names the batch); Workflow B refuses unless the batch is `processed` |
| n8n editor | No (zero inbound rules) | SSM Session Manager port forward to `localhost:5678` |

## Why there is no NAT Gateway

- Lambdas that send to SQS (`split-csv`) run outside the VPC and never touch RDS.
- Lambdas that need RDS (`load-chunk`, `get-upload-url`, `batch-status`) run inside the VPC and need no internet:
  S3 goes through the free Gateway Endpoint, SQS delivery to `load-chunk` is done by the Lambda service, and
  presigning is local signing.
- n8n sits in a public subnet with an outbound-only public IP, so it reaches Groq, the lender sites, SES and SSM
  through the free Internet Gateway while accepting nothing inbound.

## Data flow, one batch

1. UI calls `get-upload-url`; the batch row is `pending`.
2. UI uploads straight to S3; `ObjectCreated` triggers `split-csv`, which emits one SQS message per 5,000-row chunk
   with exact byte offsets and `total_chunks`.
3. `load-chunk` (at most 3 concurrent) writes a `chunk_loads` ledger row, validates, COPYs into a temporary staging
   table and upserts `users` in one transaction. A redelivered chunk finds its ledger row and exits.
4. The invocation whose conditional `loading → processed` UPDATE returns a row POSTs `{batch_id}` to Workflow B,
   exactly once per batch.
5. Workflow A, on its own daily schedule, compares each lender page's criteria hash with `loan_products.content_hash`
   and calls Groq (through the LLM Gateway) only for pages that changed.
   Workflow B: Stage 1 SQL pre-filter, Stage 2 deterministic rules, Stage 3 cohort verdicts (cache first, Groq for
   misses only, through the LLM Gateway), then inserts `matches`, finalizes `pipeline_runs` and calls Workflow C.
6. Workflow C composes emails, redirects every recipient to `TEST_INBOX_ALIASES`, aborts if any recipient is outside
   that list, then sends through SES unless `dry_run` is true, and marks `notified_at`.
7. If A, B, C or the LLM Gateway fails an automatic execution, n8n starts Workflow E, which stores an `n8n_errors` row and sends one
   alert email to the first test alias.

## Designed, not implemented

These are not in the deployed system and are drawn nowhere above.

| Item | Task | State |
|---|---|---|
| CloudWatch alarm on `ingest-dlq` depth | T21 | Built and drilled: alarm, batch marked `failed` on the 5th receive, `scripts/redrive_dlq.sh` |
| Transactional outbox for the n8n trigger | n/a | Production upgrade; `scripts/retrigger_batch.sh` is the recovery path |
| API Gateway in front of the Function URLs, Multi-AZ RDS, Secrets Manager | n/a | Production upgrades only |
