# Progress

| ID | Task | Status | Date | Notes |
|----|------|--------|------|-------|
| T01 | Inspect sample CSV | DONE | 2026-10-20 | 10,000 rows, 0 malformed; emails not unique |
| T02 | AWS account + IAM | DONE | 2026-10-20 | IAM user `clickpe-admin`, CLI profile `clickpe`; $10 monthly budget set |
| T03 | SES test identities | DONE | 2026-10-20 | 3 identities verified in ap-southeast-2; region changed from ap-south-1 (account is SCP region-locked) |
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
- Budget: "My Monthly Cost Budget" $10.00, status OK, $0.00 spent (user screenshot, Budgets console). The default "My Zero-Spend Budget" was deleted.
- Open items: root MFA not confirmed by the user; region must be `ap-south-1` (console was on Sydney at one point); confirm console account matches CLI account `376834080732`.
- Incident: the first secret access key was pasted into chat; the user deleted it and created a new one. Only the new key is in use.
- Rubric: none directly (setup; enables Cloud Architecture tasks). `docs/rubric-evidence.md` does not exist yet — created in T05.
- Explain it back:
  - Q: Why an IAM user instead of root credentials? A: Root can't be scoped or easily revoked; an IAM user with its own key can be rotated or deleted without touching the account.
  - Q: Why a named CLI profile (`clickpe`)? A: Keeps this project's keys separate from any other AWS account and makes every command explicit via `--profile`.
  - Q: What did the leaked-key incident teach? A: Secrets go only into `aws configure` in a local terminal; a pasted key must be treated as compromised and deleted at once.

### T03 — SES test identities (2026-10-20)
- Files: none in the repo for SES itself; region decision updated in CLAUDE.md §2 (and T02/T03/T10 task text).
- Blocker found and resolved: `create-email-identity` in ap-south-1 failed with an explicit deny from SCP `p-veigobeu` (org `o-0wd49xhiqy`, management account `348258987630`). Probing showed EC2/Lambda/RDS/SQS/SES all denied in ap-south-1 and us-east-1, allowed only in ap-southeast-2. The account was created through the AWS Projects console, which locks a project to its region (Projects → loan-eligiblity-engine → Additional info → Region: ap-southeast-2; not editable). The user decided to stay in Sydney. CLI profile `clickpe` default region is now `ap-southeast-2`. This supersedes the T02 note "region must be ap-south-1".
- Evidence:
  - `aws sesv2 list-email-identities --profile clickpe` → `mrrssoni12@gmail.com`, `mrrssoni12+one@gmail.com`, `mrrssoni12+two@gmail.com`, all `"VerificationStatus": "SUCCESS"`, `"SendingEnabled": true`
  - `aws sesv2 get-account --profile clickpe` → `"Production": false` (sandbox), `Max24HourSend: 200`, `MaxSendRate: 1.0`
- `TEST_INBOX_ALIASES` (for the T38 guard): `mrrssoni12@gmail.com,mrrssoni12+one@gmail.com,mrrssoni12+two@gmail.com`
- Constraints for Workflow C: sandbox can only send to verified identities; at most 1 email/s and 200 per 24 h, so the T39 Wait node must keep sends at ≤ 1/s.
- Rubric: Cloud Architecture (safe email path: sandbox + verified test inbox only). `docs/rubric-evidence.md` does not exist yet; it is created in T05.
- Explain it back:
  - Q: Why is the system deployed in Sydney and not Mumbai? A: The demo account is an AWS Projects account that an SCP locks to ap-southeast-2. Every needed service is available there and the region is one config value. Production would use ap-south-1 for latency and RBI data-localisation of borrower data.
  - Q: Why keep SES in the sandbox instead of requesting production access? A: The sandbox only delivers to verified identities, so even a bug cannot email a real person from the CSV. That is a hard AWS-side safety net under the T38 recipient guard.
  - Q: Why three aliases of one Gmail inbox? A: Gmail ignores the `+tag`, so all mail lands in one inbox, but the aliases are distinct SES identities. That lets the demo show users being spread across different recipients without owning several mailboxes.
