# Progress

| ID | Task | Status | Date | Notes |
|----|------|--------|------|-------|
| T01 | Inspect sample CSV | DONE | 2026-10-20 | 10,000 rows, 0 malformed; emails not unique |
| T02 | AWS account + IAM | DONE | 2026-10-20 | IAM user `clickpe-admin`, CLI profile `clickpe`; budget alert not yet confirmed |
| T03 | SES test identities | TODO | | |
| T04 | Groq API key | TODO | | |
| T05 | Repo skeleton | TODO | | |
| T06 | Decisions doc | TODO | | |
| T07 | Schema | TODO | | |
| T08 | Migration runner + seed | TODO | | |
| T09 | serverless.yml base | TODO | | |
| T10 | RDS instance | TODO | | |
| T11 | EC2 for n8n | TODO | | |
| T12 | Run migrations on RDS | TODO | | |
| T13 | Shared Lambda modules | TODO | | |
| T14 | Lambda get-upload-url | TODO | | |
| T15 | Lambda process-csv — parsing & validation | TODO | | |
| T16 | Lambda process-csv — bulk load | TODO | | |
| T17 | Lambda process-csv — trigger n8n | TODO | | |
| T18 | Lambda batch-status | TODO | | |
| T19 | Deploy + scaling note | TODO | | |
| T20 | docker-compose for n8n | TODO | | |
| T21 | n8n credentials | TODO | | |
| T22 | Pick crawl targets | TODO | | |
| T23 | Workflow A: fetch + extract | TODO | | |
| T24 | Workflow A: change detection | TODO | | |
| T25 | Workflow A: Groq structuring | TODO | | |
| T26 | Workflow A: upsert + error branch | TODO | | |
| T27 | Workflow B: webhook + batch fetch | TODO | | |
| T28 | Workflow B: Stage 1 SQL pre-filter | TODO | | |
| T29 | Workflow B: Stage 2 rules | TODO | | |
| T30 | Workflow B: Stage 3 Groq on borderline | TODO | | |
| T31 | Workflow B: persist matches + metrics | TODO | | |
| T32 | Workflow C: gather + compose | TODO | | |
| T33 | Workflow C: recipient redirection | TODO | | |
| T34 | Workflow C: send via SES + mark notified | TODO | | |
| T35 | Upload page | TODO | | |
| T36 | E2E run | TODO | | |
| T37 | Idempotency + bad input | TODO | | |
| T38 | Export workflows | TODO | | |
| T39 | Architecture diagram | TODO | | |
| T40 | README | TODO | | |
| T41 | Video script | TODO | | |
| T42 | Record + submit | TODO | | |

Statuses: `TODO`, `IN PROGRESS`, `DONE`, `BLOCKED (reason)`.

## Log
### T01 — Inspect sample CSV (2026-10-20)
- Files: docs/data-notes.md
- Findings: 10,000 rows, 7 columns, no nulls or malformed rows. `user_id` unique UUIDs; `email` only 2,632 distinct (shared by 2–5 users); income 25k–150k (steps of 1k); score 650–800 (steps of 5); age 22–50; employment: Salaried / Self-Employed / Business.
- Housekeeping: `users.csv` is at repo root, should move to `data/` and `data/` be gitignored (T05).
- Explain it back:
  - Q: Why not make `email` unique or the upsert key? A: 7,368 rows share an email with another user; only `user_id` is unique, so upserting on email would merge distinct users.
  - Q: Why does the data shape matter for the LLM stage? A: Only 3 employment values and few income/score/age levels mean users fall into few cohorts, so one Groq call can cover many users.
  - Q: The sample has no bad rows, so how is validation tested? A: With synthetic bad-row CSVs in /tests/ (T15), since the real file cannot exercise the reject paths.

### T02 — AWS account + IAM (2026-10-20)
- Files: none (console + local CLI config only; credentials live in `~/.aws`, never in the repo)
- Evidence:
  - `aws sts get-caller-identity --profile clickpe` →
    `"Account": "376834080732"`, `"Arn": "arn:aws:iam::376834080732:user/clickpe-admin"`
- Open items: $10 budget alert and root MFA were not confirmed by the user; region must be `ap-south-1` (console was on Sydney at one point).
- Incident: the first secret access key was pasted into chat; the user deleted it and created a new one. Only the new key is in use.
- Rubric: none directly (setup; enables Cloud Architecture tasks). `docs/rubric-evidence.md` does not exist yet — created in T05.
- Explain it back:
  - Q: Why an IAM user instead of root credentials? A: Root can't be scoped or easily revoked; an IAM user with its own key can be rotated or deleted without touching the account.
  - Q: Why a named CLI profile (`clickpe`)? A: Keeps this project's keys separate from any other AWS account and makes every command explicit via `--profile`.
  - Q: What did the leaked-key incident teach? A: Secrets go only into `aws configure` in a local terminal; a pasted key must be treated as compromised and deleted at once.
