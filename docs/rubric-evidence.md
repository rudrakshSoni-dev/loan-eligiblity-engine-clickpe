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
| ⬜ | Splitter, deploy + smoke test | `lambdas/`, `scripts/smoke_test.sh` | T17, T19–T22 |
| ✅ | Private RDS: `db.t4g.micro` PG 16.9, not publicly accessible, encrypted gp3, single-AZ, deletion protection, SG with no CIDR ingress; public DNS resolves only to a private IP and a laptop gets `No route to host`; endpoint in SSM. From EC2: `verify-full` connection on TLSv1.3, `sslmode=disable` rejected by `pg_hba` ("no encryption"), `rds.force_ssl = 1` in `default.postgres16`, `max_connections` = 79 | `infra/rds.md`; `PROGRESS.md` T11 | T11 |
| ✅ | No-NAT VPC design: n8n on `t4g.small` in the default VPC's public subnet (outbound via the free Internet Gateway), SG with zero inbound rules, access only through SSM Session Manager, IMDSv2 required, encrypted gp3, instance role limited to `AmazonSSMManagedInstanceCore`; RDS 5432 open to the n8n SG by reference only | `infra/ec2/setup.sh`, `infra/ec2.md`; `PROGRESS.md` T12 | T12 |
| ✅ | Schema and seed applied to the private RDS instance from inside the VPC over verified TLS: 11 tables, re-run applies 0 migrations and 0 seed rows, 5 seed products flagged `is_seed` | `infra/ec2/migrate.sh`; `PROGRESS.md` T13 | T13 |
| ⬜ | Webhook secret on Lambda → n8n calls | `lambdas/`, `n8n/workflows/` | T19, T32 |

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
| ⬜ | Tests with coverage ≥ 80% on shared + validation | `tests/` | T44 |

## Docs & Presentation (20 pts)

Diagram, README, video.

| Status | Evidence | Where | Task |
|---|---|---|---|
| ✅ | Design decisions doc: 19 sections, each with choice / rejected / why, every claim labelled cited / measured / estimate; approved | `docs/decisions.md` | T04, T07 |
| ⬜ | Mermaid architecture diagram matching deployed reality | `docs/architecture.md`, `README.md` | T48 |
| ⬜ | README with copy-pasteable setup and measured design decisions | `README.md` | T49 |
| ⬜ | Video script and recording | `docs/video-script.md` | T50–T52 |
