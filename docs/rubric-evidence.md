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
| ✅ | Data shape analysis: 3 employment values and coarse income/score/age steps give few cohorts, so cohort batching can cut LLM calls | `docs/data-notes.md` → "Implications" | T01 |
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
| ⬜ | `serverless.yml`: presigned upload, S3 → SQS → Lambda fan-out, DLQ, least-privilege IAM | `infra/serverless.yml` | T10, T15, T17–T21 |
| ⬜ | Private RDS, no-NAT VPC design, n8n on EC2 in the same VPC | `infra/`, `docs/decisions.md` | T11–T12 |
| ⬜ | Webhook secret on Lambda → n8n calls | `lambdas/`, `n8n/workflows/` | T19, T32 |

## Backend & Code Quality (30 pts)

Correct ingestion, clean, modular, commented code.

| Status | Evidence | Where | Task |
|---|---|---|---|
| ✅ | Column profile and validation rules derived from the real CSV | `docs/data-notes.md` | T01 |
| ✅ | Modular layout: one package per Lambda plus a pure `shared/` package | `lambdas/` | T05 |
| ⬜ | Lint, format, type-check and test gates (`make check`) | `pyproject.toml`, `Makefile` | T06 |
| ⬜ | Schema with CHECK constraints, migrations, seed data flagged `is_seed` | `db/` | T08–T09 |
| ⬜ | Validation with reject report; COPY bulk load; idempotent upsert | `lambdas/shared/`, `lambdas/load_chunk/` | T16–T18 |
| ⬜ | Tests with coverage ≥ 80% on shared + validation | `tests/` | T44 |

## Docs & Presentation (20 pts)

Diagram, README, video.

| Status | Evidence | Where | Task |
|---|---|---|---|
| 🟡 | Design decisions doc started (LLM provider section) | `docs/decisions.md` | T04, T07 |
| ⬜ | Mermaid architecture diagram matching deployed reality | `docs/architecture.md`, `README.md` | T48 |
| ⬜ | README with copy-pasteable setup and measured design decisions | `README.md` | T49 |
| ⬜ | Video script and recording | `docs/video-script.md` | T50–T52 |
