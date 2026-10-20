# Progress

| ID | Pri | Task | Status | Date | Notes |
|----|-----|------|--------|------|-------|
| T01 | P0 | Inspect sample CSV | DONE | 2026-10-20 | 10,000 rows, 0 malformed; emails not unique |
| T02 | P0 | AWS account + IAM | DONE | 2026-10-20 | IAM user `clickpe-admin`, CLI profile `clickpe`; $10 monthly budget set |
| T03 | P0 | SES identities | DONE | 2026-10-20 | 3 identities verified in ap-southeast-2; region changed from ap-south-1 (account is SCP region-locked) |
| T04 | P0 | Groq key | DONE | 2026-10-20 | gpt-oss-120b chosen (20b fallback); 30 RPM / 1K RPD / 8K TPM / 200K TPD |
| T05 | P0 | Repo skeleton | DONE | 2026-10-20 | Layout per CLAUDE.md §3; task IDs renumbered to match CLAUDE.md §6 |
| T06 | P0 | Quality tooling | TODO | |  |
| T07 | P0 | Decisions doc ⚖️ | TODO | |  |
| T08 | P0 | Schema ⚖️ | TODO | |  |
| T09 | P0 | Migrations + seed | TODO | |  |
| T10 | P0 | serverless.yml base ⚖️ | TODO | |  |
| T11 | P0 | RDS | TODO | |  |
| T12 | P0 | EC2 for n8n | TODO | |  |
| T13 | P0 | Migrate RDS | TODO | |  |
| T14 | P0 | Shared modules | TODO | |  |
| T15 | P0 | get-upload-url | TODO | |  |
| T16 | P0 | Validation module ⚖️ | TODO | |  |
| T17 | P1 | split-csv Lambda (outside VPC) ⚖️ | TODO | |  |
| T18 | P0 | load-chunk Lambda (inside VPC) | TODO | |  |
| T19 | P0 | Completion → n8n trigger | TODO | |  |
| T20 | P0 | batch-status Lambda | TODO | |  |
| T21 | P1 | DLQ handling + alarm | TODO | |  |
| T22 | P0 | Deploy + smoke test | TODO | |  |
| T23 | P0 | docker-compose | TODO | |  |
| T24 | P0 | n8n credentials | TODO | |  |
| T25 | P1 | Workflow E — global error handler | TODO | |  |
| T26 | P1 | Groq sub-workflow (LLM Gateway) | TODO | |  |
| T27 | P0 | Crawl targets ⚖️ | TODO | |  |
| T28 | P0 | Workflow A: fetch + extract | TODO | |  |
| T29 | P1 | Workflow A: change detection | TODO | |  |
| T30 | P0 | Workflow A: structuring via LLM Gateway | TODO | |  |
| T31 | P0 | Workflow A: upsert + lifecycle | TODO | |  |
| T32 | P0 | Workflow B: webhook + run setup | TODO | |  |
| T33 | P0 | Workflow B: Stage 1 SQL pre-filter ⚖️ | TODO | |  |
| T34 | P0 | Workflow B: Stage 2 deterministic rules ⚖️ | TODO | |  |
| T35 | P0 | Workflow B: Stage 3 cohort LLM evaluation ⚖️ | TODO | |  |
| T36 | P0 | Workflow B: persist + metrics + chain | TODO | |  |
| T37 | P1 | Benchmark at scale | TODO | |  |
| T38 | P0 | Workflow C: compose + recipient guard | TODO | |  |
| T39 | P0 | Workflow C: send + mark notified | TODO | |  |
| T40 | P0 | Upload page | TODO | |  |
| T41 | P2 | UI polish | TODO | |  |
| T42 | P0 | End-to-end run | TODO | |  |
| T43 | P0 | Idempotency + failure drills | TODO | |  |
| T44 | P1 | Test coverage pass | TODO | |  |
| T45 | P1 | Security review | TODO | |  |
| T46 | P1 | Cost table | TODO | |  |
| T47 | P0 | Export workflows | TODO | |  |
| T48 | P0 | Architecture diagram | TODO | |  |
| T49 | P0 | README | TODO | |  |
| T50 | P0 | Video script | TODO | |  |
| T51 | P0 | Rehearsal | TODO | |  |
| T52 | P0 | Record + upload | TODO | |  |
| T53 | P0 | Final rubric audit | TODO | |  |
| T54 | P0 | Submit | TODO | |  |

Statuses: `TODO`, `IN PROGRESS`, `DONE`, `SKIPPED (reason)`, `BLOCKED (reason)`. ⚖️ = architectural choice; needs the user's "go" before coding.

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

### T04 — Groq API key (2026-10-20)
- Files: docs/decisions.md (new, "LLM provider: Groq" section), .gitignore (`.env`, `.env.*` ignored; `!.env.example` kept)
- Found and fixed: `.env` was not gitignored before this task. Fixed before the key was written to disk. The key was entered with `read -rs` in the user's terminal and never shown in chat; `.env` is mode 600.
- Evidence:
  - `git check-ignore -v .env` → `.gitignore:5:.env	.env`
  - `GET /openai/v1/models` → chat models `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`, `allam-2-7b` (no Llama chat models on this account)
  - `POST /openai/v1/chat/completions` (key from `$GROQ_API_KEY`, JSON mode, temperature 0) → `http=200 time=0.709s` on gpt-oss-120b, output `{"min_monthly_income":25000,"interest_rate_min":10.5,"interest_rate_max":24}`; gpt-oss-20b → `http=200 time=0.741s`, same JSON
  - Response headers: `x-ratelimit-limit-requests: 1000`, `x-ratelimit-limit-tokens: 8000`, matching the console Limits page (user screenshot): gpt-oss-120b / 20b / qwen3.8-27b all 30 RPM, 1K RPD, 8K TPM, 200K TPD
  - Same call with `reasoning_effort: "low"` → completion tokens 153 → 79, identical JSON
- Secrets scan: only prose matches (PROGRESS.md incident note, .gitignore comment); no keys.
- Quality gates: no Python touched (tooling not set up yet).
- Rubric: n8n Workflow Design (Treasure Hunt: the measured limits are why cohort batching and change detection are needed). `docs/rubric-evidence.md` does not exist yet; it is created in T05.
- Note: task IDs in this file differ from CLAUDE.md §6 from T05 on (e.g. CLAUDE.md T06 "Quality tooling" has no row here). To reconcile in T05; decisions.md refers to tasks by name to stay correct either way.
- Explain it back:
  - Q: Why gpt-oss-120b instead of the smaller 20b? A: Both have identical free-tier limits (30 RPM, 1K RPD, 8K TPM), so the smaller model buys no throughput; the larger one is the better judge. 20b is the fallback because Groq limits are per model, giving a second quota on a 429.
  - Q: Why set `reasoning_effort: "low"`? A: gpt-oss bills hidden reasoning as completion tokens. On the test prompt, low effort cut completion tokens from 153 to 79 with identical output, roughly doubling how many calls fit in the 8K tokens/min budget.
  - Q: Could you just ask the LLM about every user–product pair? A: No. 10,000 users × 5 products = 50,000 calls against a 1,000 requests/day quota, i.e. 50 days. That is why matching filters in SQL and rules first and sends only borderline cohorts to the LLM.

### T05 — Repo skeleton (2026-10-20)
- Files: `.gitignore` (Python/coverage/serverless/n8n runtime/editor entries added), `.env.example` (new, placeholders only), `docs/rubric-evidence.md` (new), `docs/data-notes.md` (housekeeping note updated), `PROGRESS.md` (table rebuilt), package `__init__.py` docstrings under `lambdas/` and `tests/`, `.gitkeep` in `infra/iam`, `infra/ec2`, `db`, `n8n/workflows`, `ui`, `scripts`, `docs/screenshots`, `tests/fixtures`
- Task IDs: the table now uses CLAUDE.md §6 IDs (T01–T54) with a priority column. T01–T04 kept their IDs. Older log entries that cite later task numbers used the old scheme; e.g. the T01 note "bad-row CSVs in /tests/ (T15)" is now T16 (Validation module).
- Evidence:
  - `git check-ignore -v .env data/users.csv` → `.gitignore:7:.env	.env` and `.gitignore:4:data/	data/users.csv`
  - `git check-ignore .env.example` → not ignored (template is committed)
  - `find . -path ./.git -prune -o -print` → `infra/{iam,ec2}`, `lambdas/{get_upload_url,split_csv,load_chunk,batch_status,shared}`, `db`, `n8n/workflows`, `ui`, `scripts`, `docs/screenshots`, `tests/{unit,fixtures}`, matching CLAUDE.md §3
  - Secrets scan: matches only in prose, variable names and `<placeholder>` values in `.env.example`
- Quality gates: only docstring-only `__init__.py` files exist; ruff/mypy/pytest are set up in T06.
- Not created yet, owned by later tasks: `pyproject.toml` (T06), `n8n/.env.example` (T23), `docs/architecture.md` (T48).
- Reminder for the user: make the GitHub repo private and invite `ujjwalkala-clickpe`, `HarshSrivastav-Dailype`, `ManishBiswal-clickpe`, `tushar-clickpe`.
- Rubric: Backend (modular layout), Cloud (secrets hygiene). Tracker created: `docs/rubric-evidence.md`.
- Explain it back:
  - Q: Why `.gitkeep` files and docstring `__init__.py` files instead of empty folders? A: Git does not track empty directories, so without them a fresh clone would not show the layout. Real packages get an `__init__.py` with a docstring so mypy and pytest resolve imports like `lambdas.shared.config`.
  - Q: Why is `.env.example` committed while `.env` is ignored by two patterns (`.env`, `.env.*`)? A: The example documents every variable a developer needs, with placeholders only. The wildcard also catches `.env.local` or `.env.prod`, and the `!.env.example` exception keeps the template tracked.
  - Q: Why gitignore the whole `data/` folder? A: The sample CSV holds emails and income data, and the synthetic 100k files are large. Neither belongs in git history, and once a file is committed, deleting it later does not remove it from history.
