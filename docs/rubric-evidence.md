# Rubric evidence tracker

Live map from each grading line to the evidence a reviewer can see in this repo.
Every entry names the task, the file or artifact, and what it proves. Numbers
come only from real runs; the command that produced them is in `PROGRESS.md`.

Legend: ✅ in repo and verified · 🟡 partial · ⬜ planned (not yet built)

---

## n8n Workflow Design (30 pts)

Sophistication, robustness, efficiency, creative nodes, Optimization Treasure Hunt.

| Status | Evidence | Where | Task |
|---|---|---|---|
| ✅ | Measured Groq free-tier limits (30 RPM, 1K RPD, 8K TPM) and the arithmetic showing per-pair LLM calls are infeasible (10,000 × 5 = 50,000 calls vs 1,000/day) | `docs/decisions.md` → "LLM provider: Groq"; `PROGRESS.md` T04 | T04 |
| ✅ | Data shape analysis: 9,869 distinct (income, score, age, employment) tuples in 10,000 users, and 1,028–5,528 raw-band cohorts per product, so the design keys cohorts by borderline reason and caches verdicts instead | `docs/data-notes.md`, `docs/decisions.md` → "Matching and the Optimization Treasure Hunt" | T01, T07 |
| ✅ | Treasure Hunt strategy: LLM at ingest gated by content hash, SQL + rules first, skip-LLM rule, reason-keyed cohorts, `cohort_verdicts` cache, budget guard; counterfactual 30,000 calls = 30 days of quota | `docs/decisions.md` | T07 |
| ✅ | Crawl targets probed live (HTTP status, robots.txt, criteria present in static HTML) | `docs/decisions.md` → "Crawl targets" | T07 |
| ✅ | Funnel and cost tables in the schema: `pipeline_runs` (per-stage counts, NULL until measured), `cohort_verdicts` (cache keyed by product content hash), `llm_calls` (per-call token ledger) | `db/schema.sql` | T08 |
| ⬜ | Global error workflow (Workflow E) | `n8n/workflows/` | T25 |
| ⬜ | Reusable LLM Gateway sub-workflow | `n8n/workflows/` | T26 |
| ⬜ | Crawl + change detection + structuring (Workflow A) | `n8n/workflows/` | T27–T31 |
| ⬜ | Multi-stage matching funnel with measured numbers (Workflow B) | `n8n/workflows/`, `pipeline_runs` | T32–T36 |
| ⬜ | Benchmark at 100k rows | `scripts/benchmark.md` | T37 |
| ⬜ | Notification with recipient guard (Workflow C) | `n8n/workflows/` | T38–T39 |

## Cloud Architecture & Integration (20 pts)

Serverless quality, secure n8n ↔ AWS integration, scalable ingestion.

| Status | Evidence | Where | Task |
|---|---|---|---|
| ✅ | SES kept in sandbox; only 3 verified test identities can receive mail (AWS-side safety net) | `PROGRESS.md` T03 | T03 |
| ✅ | Region decision recorded with the SCP evidence and the production target (`ap-south-1`) | `PROGRESS.md` T03 | T03 |
| ✅ | Secrets never in the repo: `.env` gitignored, `.env.example` holds placeholders only | `.gitignore`, `.env.example` | T04, T05 |
| ✅ | Every architecture decision documented with the rejected alternative and a cited reason, incl. measured account constraint (Lambda concurrency 10 → reserved concurrency impossible → SQS `MaximumConcurrency`) and Step Functions as a considered runner-up | `docs/decisions.md` | T07 |
| 🟡 | `serverless.yml` (packaged and validated, not yet deployed): private TLS-only bucket with 7-day lifecycle; S3 → `splitCsv` → SQS `ingest` (visibility 6× loader timeout) → `ingest-dlq` after 5 receives; `loadChunk` ESM batch 1, `MaximumConcurrency 3`, partial batch failures; no reserved concurrency; free S3 Gateway Endpoint; Lambda SG egress limited to RDS / n8n / S3 prefix list; one IAM role per function with no wildcard actions (only `*` resource = the 3 ENI actions VPC Lambdas require); Function URL permissions with `InvokedViaFunctionUrl`; `validate-template` + `cfn-lint` clean; `splitCsv` async failures go to a `split-failures` queue; `make package` imports pg8000 and every handler from the built zip in a clean interpreter (caught a real cold-start crash) | `serverless.yml`, `docs/decisions.md` → "Infrastructure as code", "IAM"; `PROGRESS.md` T10 | T10 |
| ✅ | Presigned POST upload (`get-upload-url`): policy pins key `uploads/{batch_id}.csv`, `Content-Type`, 1 B–20 MB and a 5-minute expiry; checked against real S3 with `curl -F`: valid file `204`, 22 MB file `400 EntityTooLarge`, wrong type / changed key `403` with the failed condition; regional endpoint pinned after measuring a `307` from the global host | `lambdas/shared/uploads.py`, `lambdas/get_upload_url/handler.py`, `docs/decisions.md` → "Upload"; `PROGRESS.md` T15 | T15 |
| 🟡 | SQS loader (`load-chunk`, built and tested locally, not yet deployed): each message is acknowledged, fails its batch (split error, replaced object, invalid range, refused data) or is returned in `batchItemFailures` for retry → DLQ; ranged S3 reads with `IfMatch` checked on real S3 (wrong ETag → `PreconditionFailed`, past end → `InvalidRange`, ranges reassemble the 993,191-byte file exactly) | `lambdas/load_chunk/handler.py`, `lambdas/shared/chunks.py`, `docs/decisions.md` → "Chunking", "Chunk loader"; `PROGRESS.md` T18 | T18 |
| 🟡 | Splitter (`split-csv`, built and tested locally, not yet deployed): S3 event → size check → `GetObject` pinned to the event ETag → 5,000-record chunks with exact byte ranges → `SendMessageBatch` to `ingest`; runs outside the VPC and never touches RDS; file-level failures (empty, oversize, bad header, no data rows, deleted object) become one control message that fails the batch; replaced objects skipped; S3/SQS errors → async retry → `split-failures`. End to end with moto S3/SQS and PostgreSQL 16: 10,000-row sample → 2 chunks → `processed`, 10,000 users; shuffled + duplicated deliveries complete exactly once | `lambdas/split_csv/handler.py`, `lambdas/shared/splitting.py`, `tests/integration/test_split_to_load_db.py`, `docs/decisions.md` → "Chunking"; `PROGRESS.md` T17 | T17 |
| ✅ | Deployed and verified from outside: `sls deploy` (280 s) of the whole ingestion stack; `scripts/smoke_test.sh` goes Function URL → presigned POST (HTTP 204) → S3 event → `splitCsv` → SQS → VPC `loadChunk` → private RDS → `batchStatus` poll. 10,000-row sample → `processed` in 6.9 s, identical re-upload 0 inserted / 0 updated, malformed fixture 1 ok / 10 rejected with line numbers; `ingest`, DLQ and `split-failures` empty; REPORT lines give measured duration and memory for all four functions; RDS 5432 opened to the Lambda SG by reference only | `scripts/smoke_test.sh`, `serverless.yml`, `docs/decisions.md` → "First deployment (T22)"; `PROGRESS.md` T22 | T22 |
| ✅ | Completion → n8n trigger, deployed: only the invocation that wins the conditional `loading → processed` UPDATE POSTs `{batch_id}` with `X-Webhook-Secret` to n8n's private IP (5 s, 3 attempts, retries only network/timeout/429/5xx). Live: 4 batches → 4 `webhook_sent` (HTTP 200, 1 attempt) and 4 n8n executions; each 6-chunk batch logged 5 losing completion checks with a different winning chunk. Drill: n8n stopped → 3 refused attempts, `webhook_failed`, batch stays `processed`, queue empty → `scripts/retrigger_batch.sh` (re-POST from the n8n instance via SSM, secret never in command parameters) → HTTP 200 | `lambdas/shared/notify.py`, `lambdas/load_chunk/handler.py`, `scripts/retrigger_batch.sh`, `docs/decisions.md` → "Completion trigger", `infra/n8n.md`; `PROGRESS.md` T19 | T19 |
| ✅ | Private RDS: `db.t4g.micro` PG 16.9, not publicly accessible, encrypted gp3, single-AZ, deletion protection, SG with no CIDR ingress; public DNS resolves only to a private IP and a laptop gets `No route to host`; endpoint in SSM. From EC2: `verify-full` connection on TLSv1.3, `sslmode=disable` rejected by `pg_hba` ("no encryption"), `rds.force_ssl = 1` in `default.postgres16`, `max_connections` = 79 | `infra/rds.md`; `PROGRESS.md` T11 | T11 |
| ✅ | No-NAT VPC design: n8n on `t4g.small` in the default VPC's public subnet (outbound via the free Internet Gateway), SG with zero inbound rules, access only through SSM Session Manager, IMDSv2 required, encrypted gp3, instance role limited to `AmazonSSMManagedInstanceCore`; RDS 5432 open to the n8n SG by reference only | `infra/ec2/setup.sh`, `infra/ec2.md`; `PROGRESS.md` T12 | T12 |
| ✅ | Schema and seed applied to the private RDS instance from inside the VPC over verified TLS: 11 tables, re-run applies 0 migrations and 0 seed rows, 5 seed products flagged `is_seed` | `infra/ec2/migrate.sh`; `PROGRESS.md` T13 | T13 |
| ✅ | n8n runs pinned (2.44.4) and health-checked on the EC2 box with no inbound internet rules: editor 200 only through an SSM port forward, public IP times out; webhook 5678 open to the Lambda SG by reference; Webhook IP allowlist proven (200 for `172.31.0.0/16`, 403 for another CIDR); `$env` blocked in nodes because the container env holds the encryption key | `n8n/docker-compose.yml`, `infra/n8n.md`; `PROGRESS.md` T23 | T23 |
| 🟡 | Webhook secret on Lambda → n8n calls: Lambda sends `X-Webhook-Secret` from SSM; a temporary n8n receiver at `match-batch` proved the layers from inside the VPC: right secret 200, wrong or missing secret 401, caller outside the IP allowlist 403. Workflow B's own Header Auth check is T32 | `lambdas/shared/notify.py`, `infra/n8n.md`; `PROGRESS.md` T19 | T19, T32 |

## Backend & Code Quality (30 pts)

Correct ingestion, clean, modular, commented code.

| Status | Evidence | Where | Task |
|---|---|---|---|
| ✅ | Column profile and validation rules derived from the real CSV | `docs/data-notes.md` | T01 |
| ✅ | Modular layout: one package per Lambda plus a pure `shared/` package | `lambdas/` | T05 |
| ✅ | One-command quality gates: ruff lint (incl. no `print`, no bare/blind `except`, module docstrings) + format, mypy strict on all code, pytest with an 80% branch-coverage floor on `lambdas/shared`; a negative probe shows each gate failing | `pyproject.toml`, `Makefile`, `uv.lock`; `PROGRESS.md` T06 | T06 |
| ✅ | Schema: 10 tables, CHECK constraints derived from the sample (score, age, income, canonical employment, normalised email, product min ≤ max), `chunk_loads` idempotency ledger, `updated_at` trigger; 21 self-asserting constraint checks pass and all 10,000 sample rows pass the CHECKs | `db/schema.sql`, `tests/sql/schema_constraints.sql`; `PROGRESS.md` T08 | T08 |
| ✅ | Migration runner: checksummed `schema_migrations` ledger, all pending files + ledger rows in one transaction under an advisory lock, edited-after-apply files refused; second run applies 0 migrations. Seed: 5 products labeled `source='seed'` / `is_seed` / "Seed ·" / "SEED DATA.", upsert that changes 0 rows on re-run and never rewrites a non-seed row; 5 integration tests against PostgreSQL 16 | `db/migrate.py`, `db/seed_products.sql`, `tests/unit/test_migrate.py`, `tests/integration/test_migrate_db.py`; `PROGRESS.md` T09 | T09 |
| ✅ | Shared modules: fail-fast typed config (all problems in one error, secrets out of `repr`), cached verified-TLS pg8000 connection with reconnect (RDS CA bundle packaged, no env switch to plain), JSON logs with `stage`/`batch_id`/`duration_ms`, batch state machine with conditional UPDATEs and a chunk ledger; integration tests on PostgreSQL 16 show duplicate delivery is a no-op, a concurrent duplicate waits on the ledger key, and 6 concurrent finishers × 25 trials × 2 interleavings complete exactly once (a mutation probe that weakens the guard gives 6 winners); `lambdas/shared` coverage 97.89% | `lambdas/shared/`, `tests/unit/test_{config,db,logging,batches}.py`, `tests/integration/test_batches_db.py`; `PROGRESS.md` T14 | T14 |
| ✅ | Thin Function URL handler over a pure, signature-decoding-tested presign function; config built lazily so the packaged zip imports with no env; 405 for non-POST, 503 on a database error with no signed upload returned; `uploads.py` 100% covered, shared coverage 99.34% | `lambdas/get_upload_url/handler.py`, `tests/unit/test_{uploads,get_upload_url}.py`; `PROGRESS.md` T15 | T15 |
| ✅ | Pure, typed row validation: header matched by name (any order, BOM/case tolerant), per-line rejects listing every broken field with exact file line numbers (quoted newlines counted), normalisation without guessing, in-chunk duplicate ids; never looser than the schema, proven on PostgreSQL 16 by inserting all 10,000 validated sample rows and the accepted boundary rows in one statement, 4 negative controls, and a mutation probe (no email lowercasing → `users_email_check` failure); 7 CSV fixtures; module coverage 100% | `lambdas/shared/validation.py`, `tests/unit/test_validation.py`, `tests/integration/test_validation_db.py`, `tests/fixtures/`, `docs/decisions.md` → "Row validation"; `PROGRESS.md` T16 | T16 |
| ✅ | Chunk loader: typed chunk-message contract shared by both Lambdas; COPY into a transaction-scoped staging table, then one `DISTINCT ON` upsert that compares data columns only, so the 10,000-row sample loads in 2 chunks and an identical re-upload reports 0 inserted / 0 updated (a mutation probe without the guard moves all 10,000 users); ledger claim + rows + rejects + counts in one transaction; redelivery is a no-op; per-line reject report incl. invalid UTF-8 and NUL; refused data rolls back the chunk and fails the batch; `chunks.py` + `loading.py` 100% covered; 8 integration tests on PostgreSQL 16 | `lambdas/load_chunk/handler.py`, `lambdas/shared/{chunks,loading}.py`, `tests/integration/test_load_chunk_db.py`, `docs/decisions.md` → "Driver and load pattern", "Chunk loader"; `PROGRESS.md` T18 | T18 |
| ✅ | Status endpoint: read-only typed queries (counters, first 5 rejects, match and notified counts, latest funnel with unmeasured counters as `null`), thin GET handler with 400 / 404 / 405 / 503; 5 tests on PostgreSQL 16 incl. latest-run-wins and no leakage between batches; `status.py` 100% covered | `lambdas/shared/status.py`, `lambdas/batch_status/handler.py`, `tests/unit/test_batch_status.py`, `tests/integration/test_batch_status_db.py`; `PROGRESS.md` T20 | T20 |
| ✅ | Quote-correct chunking: boundaries come from the same `csv.reader` load-chunk uses, so cuts and line numbers agree by construction (a toggle-on-every-quote scanner was rejected with a failing input in the tests). Property tests on every fixture and a seeded random file with quoted CRLFs: chunks reassemble the file byte for byte, and per-chunk validation equals one-chunk validation; moto-backed handler tests; `splitting.py` + `chunks.py` 100% covered; 20.9 MB / 210,000 rows planned in 1.3 s (laptop) | `lambdas/shared/splitting.py`, `tests/unit/test_{splitting,split_csv}.py`, `docs/decisions.md` → "Chunking"; `PROGRESS.md` T17 | T17 |
| ✅ | Exactly-once completion trigger tested end to end: real handler, PostgreSQL 16 and a real local HTTP receiver; 10 batches × 5 chunks delivered twice by 10 concurrent workers → exactly 10 POSTs (100 chunk loads, 90 losing checks); a mutation probe that weakens the completion guard gives 2–4 POSTs per batch. Notify module tested over real sockets (retry on 5xx/timeout/refused, no retry on 401/403/404, secret never in results); `notify.py` 100% covered | `lambdas/shared/notify.py`, `tests/unit/test_notify.py`, `tests/integration/test_completion_trigger_db.py`, `tests/webhook_helpers.py`; `PROGRESS.md` T19 | T19 |
| ⬜ | Tests with coverage ≥ 80% on shared + validation | `tests/` | T44 |

## Docs & Presentation (20 pts)

Diagram, README, video.

| Status | Evidence | Where | Task |
|---|---|---|---|
| ✅ | Design decisions doc: 19 sections, each with choice / rejected / why, every claim labelled cited / measured / estimate; approved | `docs/decisions.md` | T04, T07 |
| ⬜ | Mermaid architecture diagram matching deployed reality | `docs/architecture.md`, `README.md` | T48 |
| ⬜ | README with copy-pasteable setup and measured design decisions | `README.md` | T49 |
| ⬜ | Video script and recording | `docs/video-script.md` | T50–T52 |
