# Progress

| ID | Pri | Task | Status | Date | Notes |
|----|-----|------|--------|------|-------|
| T01 | P0 | Inspect sample CSV | DONE | 2026-10-20 | 10,000 rows, 0 malformed; emails not unique |
| T02 | P0 | AWS account + IAM | DONE | 2026-10-20 | IAM user `clickpe-admin`, CLI profile `clickpe`; $10 monthly budget set |
| T03 | P0 | SES identities | DONE | 2026-10-20 | 3 identities verified in ap-southeast-2; region changed from ap-south-1 (account is SCP region-locked) |
| T04 | P0 | Groq key | DONE | 2026-10-20 | gpt-oss-120b chosen (20b fallback); 30 RPM / 1K RPD / 8K TPM / 200K TPD |
| T05 | P0 | Repo skeleton | DONE | 2026-10-20 | Layout per CLAUDE.md §3; task IDs renumbered to match CLAUDE.md §6 |
| T06 | P0 | Quality tooling | DONE | 2026-10-20 | `make check` = ruff lint + format, mypy strict, pytest + 80% coverage floor on `lambdas/shared` |
| T07 | P0 | Decisions doc ⚖️ | DONE | 2026-10-20 | Research-revised; approved by user. 13 plan changes (concurrency, ledger, presigned POST, SSM-only n8n, strict LLM schema, reason-keyed cohorts) |
| T08 | P0 | Schema ⚖️ | DONE | 2026-10-20 | 10 tables, 21 self-asserting constraint checks; all 10,000 sample rows pass the CHECKs |
| T09 | P0 | Migrations + seed | DONE | 2026-10-20 | Checksummed ledger + advisory lock; re-run applies 0 migrations, changes 0 seed rows; 5 seed products flagged |
| T10 | P0 | serverless.yml base ⚖️ | DONE | 2026-10-21 | Serverless v3; `sls package` + `validate-template` + `cfn-lint` clean; no `*` action on `*` resource; config moved to repo root. Opus review fixed a pg8000 import crash (`slim`) and silent `splitCsv` failures |
| T11 | P0 | RDS | DONE | 2026-10-21 | Private PG 16.9; from EC2: verify-full TLSv1.3 OK, sslmode=disable rejected, rds.force_ssl=1, max_connections=79 |
| T12 | P0 | EC2 for n8n | DONE | 2026-10-21 | `t4g.small` `i-02ffa9d08e8403a4a`, SG with no inbound rules, SSM session works, Docker 25.0.14 + Compose v2.29.7, 2 GB swap |
| T13 | P0 | Migrate RDS | DONE | 2026-10-21 | 11 tables on RDS via EC2; re-run applies 0 migrations, seeds 0; 5 seed products flagged |
| T14 | P0 | Shared modules | DONE | 2026-10-21 | config/db/batches/logging; 25 × 2 race trials → exactly 1 completion each; mutation probe → 6 winners; shared coverage 97.89% |
| T15 | P0 | get-upload-url | DONE | 2026-10-21 | Presigned POST verified on real S3: valid file 204; 22 MB file 400 EntityTooLarge; wrong type / key 403. Found and fixed global-endpoint 307 redirect |
| T16 | P0 | Validation module ⚖️ | DONE | 2026-10-21 | All 10,000 sample rows accepted (0 rejects) and stored under the real CHECKs; 7 fixtures; module coverage 100%; mutation probe caught by the DB test |
| T17 | P1 | split-csv Lambda (outside VPC) ⚖️ | DONE | 2026-10-21 | Boundaries from load-chunk's own csv parse; chunks reassemble every file byte for byte and per-chunk validation = one-chunk validation; split → moto SQS → load-chunk → PG16 loads the 10k sample in 2 chunks; 20.9 MB planned in 1.3 s locally |
| T18 | P0 | load-chunk Lambda (inside VPC) | DONE | 2026-10-21 | 10,000 rows in 2 chunks → 10,000 users; identical re-upload 0 inserted / 0 updated; redelivery no-op; ranged GET + IfMatch checked on real S3; shared coverage 100% with DB |
| T19 | P0 | Completion → n8n trigger | DONE | 2026-10-21 | Only the `try_complete` winner POSTs (5 s, 3 attempts); live: 4 batches → 4 POSTs, 4 n8n executions, 5 losing checks per 6-chunk batch; n8n-down drill → `webhook_failed`, retrigger script → 200; local race 100 deliveries → 10 POSTs, mutation → 2–4 per batch |
| T20 | P0 | batch-status Lambda | DONE | 2026-10-21 | GET ?batch_id= → counters, first 5 rejects, match/notified counts, latest funnel (NULL = not measured); 400/404/405/503; 5 DB tests on PG16; shared coverage 100% |
| T21 | P1 | DLQ handling + alarm | TODO | |  |
| T22 | P0 | Deploy + smoke test | DONE | 2026-10-21 | Stack deployed (280 s); smoke test passes; 10,000-row sample → `processed` in 6.9 s, identical re-upload 0 inserted / 0 updated; malformed fixture 1 ok / 10 rejected; queues and DLQ empty |
| T23 | P0 | docker-compose | DONE | 2026-10-21 | n8n 2.44.4 healthy on EC2; editor only via SSM tunnel (200), public IP times out; webhook allowlist 200 inside / 403 outside; owner account + 2FA still to be created in browser |
| T24 | P0 | n8n credentials | DONE | 2026-10-21 | 4 credentials; Postgres (verified TLS via mounted RDS CA) and AWS Assume Role (system credentials, SES-only role, no static keys) tests green |
| T25 | P1 | Workflow E — global error handler | TODO | |  |
| T26 | P1 | Groq sub-workflow (LLM Gateway) | TODO | |  |
| T27 | P0 | Crawl targets ⚖️ | DONE | 2026-10-21 | ICICI, HDFC, IDFC FIRST primary + BankBazaar spare; criteria in static HTML from the EC2 IP; robots allow all 4 paths; banks moved to `bank.in` (301) |
| T28 | P0 | Workflow A: fetch + extract | DONE | 2026-10-21 | 3 lenders HTTP 200 → 13 / 18 / 6 criteria lines; spare + 404 + DNS failure variant: 4 extracted, 2 routed to the failure branch; imported and run on EC2 via the n8n CLI |
| T29 | P1 | Workflow A: change detection | TODO | |  |
| T30 | P0 | Workflow A: structuring via LLM Gateway | DONE | 2026-10-21 | Direct Groq call (T26 not built); 3 lenders structured; drills: 401, 400, forced bad 200 rejected (7 reasons), real 429; every failure in `crawl_runs`, every call in `llm_calls`; Retry On Fail re-ran an INSERT 3× → removed |
| T31 | P0 | Workflow A: upsert + lifecycle | DONE | 2026-10-21 | One statement upserts `loan_products` and logs the `ok` run; re-run → same ids, 0 changed; 404 + forced DB error don't stop other sites; 3 failed runs → `active=false`, next good run reactivates; found and fixed 2 n8n behaviours (batching aborts siblings, Merge doesn't wait) |
| T32 | P0 | Workflow B: webhook + run setup | DONE | 2026-10-21 | Header-auth webhook + allowlist; one statement claims `processed → matching`, counts pairs, inserts `pipeline_runs`; live Lambda trigger → 202, replay 409, forced DB error 500 (drill found and fixed a swallowed-error bug) |
| T33 | P0 | Workflow B: Stage 1 SQL pre-filter ⚖️ | DONE | 2026-10-21 | Live on the 10k sample: 30,000 pairs → 14,165 candidates (10,405 strict + 3,760 near miss) in 578 ms, matches an independent count; pairs stay in Postgres (`match_candidates`); seeds inactive; idempotent re-run; forced-error drill → batch `failed` |
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

### T06 — Quality tooling (2026-10-20)
- Files: `pyproject.toml` (ruff, mypy, pytest, coverage config; uv dev group), `Makefile` (`install`, `check`, `lint`, `format-check`, `typecheck`, `test`, `fmt`), `uv.lock`, `.python-version` (3.12), `tests/unit/test_layout.py`
- Choices:
  - uv manages the dev env; `uv.lock` is committed so every machine gets the same tool versions (ruff 0.17.1, pytest 9.1.1, pytest-cov 7.1.0).
  - ruff rules go beyond the defaults to enforce CLAUDE.md §4 mechanically: `T20` (no `print`), `BLE` + `E722` (no blind/bare `except`), `D100`/`D104` (module and package docstrings), plus `I`, `UP`, `B`, `SIM`, `N`, `RUF`.
  - mypy `strict = true` on all code, not just `lambdas/shared`, because §4 requires full type hints everywhere. `files = ["lambdas", "tests"]`; `db` is added in T09 when `db/migrate.py` exists (mypy errors on a directory with no `.py` files).
  - Coverage measures `lambdas/shared` with branch coverage and `fail_under = 80`.
  - `tests/unit/test_layout.py` imports every Lambda package and checks its docstring. It is a real guard for the layout, and it gives pytest at least one test (pytest exits 5 when nothing is collected, which would fail `make check`).
- Evidence:
  - `make check` →
    - `ruff check .` → `All checks passed!`
    - `ruff format --check .` → `14 files already formatted`
    - `mypy` → `Success: no issues found in 9 source files`
    - `pytest --cov` → `5 passed in 0.12s`, `Required test coverage of 80.0% reached. Total coverage: 100.00%` (0 statements so far; the floor starts to bite in T14)
  - Negative probe (temporary `lambdas/shared/probe_tmp.py` with an untyped function, `print` and bare `except`, deleted after) →
    - ruff: `D100 Missing docstring`, `T201 print found`, `E722 Do not use bare except`
    - mypy: `error: Function is missing a type annotation [no-untyped-def]`
    - pytest: `FAIL Required test coverage of 80.0% not reached. Total coverage: 0.00%`
  - Secrets scan: matches only prose, variable names and `<placeholder>` values.
- Rubric: Backend & Code Quality (lint/format/type/test gates, coverage floor).
- Explain it back:
  - Built: one command, `make check`, that runs lint, format check, strict type check and tests with a coverage floor. Every later task must pass it before it is marked DONE.
  - Why this approach over the obvious alternative (flake8 + black + isort): ruff does all three in one fast tool with one config block. The custom rule set turns the code standards in CLAUDE.md §4 into failing checks instead of review comments.
  - Q: Why mypy strict everywhere instead of only on `lambdas/shared`? A: Handlers are thin, but they still parse events and pass data to `shared/`. A missing hint at that boundary is where type bugs get in, so it is cheaper to require hints everywhere from day one than to add them later.
  - Q: The coverage report says 100% with 0 statements. Isn't that meaningless? A: Yes, for now. The floor is wired up so that from T14 on, any shared module added without tests fails `make check`. The negative probe shows it failing at 0%.
  - Q: Why is there a test that only imports packages? A: It catches broken layout (a missing `__init__.py`, a renamed folder) that would otherwise only appear when serverless packages a Lambda. It also stops pytest from exiting with code 5 ("no tests collected") on the skeleton.

### T07 — Decisions doc (2026-10-20)
- Verify: user approved `docs/decisions.md` on 2026-10-20.
- Files: `docs/decisions.md` (rewritten: 19 sections, each choice / rejected / why, every claim labelled cited / measured / estimate), `docs/data-notes.md` (stale task IDs T07→T08, T15→T16; cohort claim corrected), `docs/rubric-evidence.md`, `CLAUDE.md` §2, §4 and task text T08, T10–T12, T14, T15, T17–T19, T23, T24, T26, T27, T34, T35, T45 (CLAUDE.md is gitignored, so these edits are local only)
- Method: four parallel research investigations (ingestion, network/security, database, n8n/LLM) against AWS / n8n / Groq / PostgreSQL docs; synthesis at `reports/Loan engine architecture decisions.md` (untracked, not for commit).
- Evidence:
  - `aws lambda get-account-settings --profile clickpe` → `"ConcurrentExecutions": 10`, `"UnreservedConcurrentExecutions": 10`
  - `uname -m` → `x86_64` (dev machine; Lambdas are arm64)
  - Cohort analysis of `data/users.csv`: 9,869 distinct (income, score, age, employment) tuples; raw-band cohorts 5,528 / 1,028 / 265 depending on band width
  - Crawl probe: ICICI, HDFC, BankBazaar eligibility pages return criteria to a plain GET (HDFC robots.txt → 403)
  - Secrets scan: only prose and placeholder matches; no `AKIA…` or `gsk_…` key patterns
  - `make check` → `All checks passed!`, `19 files already formatted`, `Success: no issues found in 9 source files`, `5 passed`, coverage floor reached (no Python touched)
- Plan changes applied (were wrong or weaker in the original §2):
  1. Reserved concurrency 5 → SQS ESM `MaximumConcurrency: 3` (reserved concurrency is impossible at account limit 10).
  2. DLQ `maxReceiveCount` 3 → 5; visibility timeout ≥ 6× loader timeout.
  3. Atomic `chunks_done` counter → `chunk_loads` ledger + conditional `loading→processed` UPDATE (counter double-counts on SQS redelivery).
  4. Presigned PUT → presigned POST with `content-length-range` (PUT has no documented size enforcement).
  5. Chunk messages carry exact quote-aware byte offsets; `split-csv` never touches RDS (bookkeeping travels in messages).
  6. Upsert adds `DISTINCT ON (user_id)` and `IS DISTINCT FROM`.
  7. pg8000 TLS verified against the RDS CA bundle; `rds.force_ssl` is already the PG16 default (verify, don't set).
  8. n8n editor via SSM port forward, no inbound internet ports; owner account + 2FA (basic auth removed in n8n 1.0); exact 2.x tag; explicit `N8N_BLOCK_ENV_ACCESS_IN_NODE`.
  9. Webhook: SG + IP allowlist + header secret + idempotent Workflow B.
  10. SES via EC2 instance role (Assume Role credential) first, IAM user fallback.
  11. Groq JSON mode → strict Structured Outputs; explicit 429 branch; `cohort_verdicts` cache; `llm_calls` ledger; budget guard.
  12. Cohort key → (product, borderline reason, triggering-feature band, employment).
  13. Step Functions Inline Map documented as the considered runner-up; Distributed Map ItemReader rejected.
- Correction to earlier logs: the T01 "users fall into few cohorts" answer is superseded by the measured 9,869 distinct tuples.
- Rubric: Docs (decisions with rejected alternatives and citations), Cloud (account-constraint-driven concurrency design, no-NAT network table, layered webhook security), n8n (Treasure Hunt strategy with measured cohort counts and counterfactual).
- Explain it back:
  - Built: a decisions document where every architecture choice names what was rejected and why, backed by a cited source or a measurement from this account, and a corrected plan in CLAUDE.md.
  - Why research-driven revision over the obvious "write up the plan as is": four details in the plan would have failed at deploy or under review (reserved concurrency, PUT size limit, counter double-count, raw-band cohorts exceeding the LLM budget). Finding them now costs minutes; finding them in T18 or T35 costs hours.
  - Q: Why not reserved concurrency to protect RDS? A: AWS lets you reserve only up to unreserved concurrency minus 100, and this account's limit is 10, so it cannot be set. The SQS event source mapping's `MaximumConcurrency: 3` caps pollers instead, which also avoids throttled messages drifting to the DLQ.
  - Q: How do you guarantee exactly one n8n trigger when chunks finish at the same time or SQS redelivers? A: Each chunk writes a ledger row keyed by (batch_id, chunk_no) in its own transaction, so a redelivery is a no-op. After commit, a conditional UPDATE moves the batch from `loading` to `processed` only when the ledger count equals total_chunks; Postgres row locking lets exactly one caller get a row back, and only that caller calls n8n.
  - Q: Why SQS instead of Step Functions, which gives a single finalize step for free? A: Both are correct; SQS already matches the task plan, needs no new plugin or ASL, and keeps every VPC Lambda free of AWS API calls. Step Functions is documented as the runner-up and would be chosen only with spare time after the SQS path passes the smoke test, mainly for its execution graph in the video.

### T08 — Schema (2026-10-20)
- Plan approved by the user ("go").
- Files: `db/schema.sql` (new), `tests/sql/schema_constraints.sql` (new)
- Choices:
  - 10 tables per CLAUDE.md §6 T08, created in one `BEGIN … COMMIT` (all or nothing). Re-run safety is T09's migrations ledger, so no `IF NOT EXISTS`.
  - Status columns are `text` + `CHECK`, not `ENUM`. Adding a value is a constraint swap, and a new ENUM value can't be used inside the transaction that adds it.
  - Added `users.name` (in the CSV, needed by Workflow C; missing from the §6 column list).
  - CHECKs looser than the observed data (score 300–900, age 18–100, income > 0) and `employment_status` limited to the 3 canonical values. `email` must already be lower-case and trimmed, so the DB enforces the T16 normalisation.
  - `loan_products`: min ≤ max for rate, score and age; `allowed_employment` must be a non-empty subset of the 3 values; NULL = unconstrained. `content_hash` must be 64 hex characters.
  - `pipeline_runs` counters stay NULL until their stage has run, so 0 always means a measured zero.
  - One `set_updated_at()` trigger on `upload_batches`, `users`, `loan_products`.
  - Indexes: the 4 from the spec plus `matches(batch_id)`, `pipeline_runs(batch_id)`, `llm_calls(batch_id)`.
  - Deferred: `n8n_errors` (T25), `app_config` (decided in T23).
  - Agreed behaviour: `users.batch_id` = the batch that last *changed* the row. An identical re-upload changes 0 rows, so Workflow B finds 0 new users and sends 0 emails (T43 idempotency).
- Evidence (throwaway `postgres:16` container, `PostgreSQL 16.15`, removed afterwards):
  - `psql -v ON_ERROR_STOP=1 < db/schema.sql` → applied; `\dt` → 10 tables (`chunk_loads, cohort_verdicts, crawl_runs, llm_calls, loan_products, matches, pipeline_runs, rejected_rows, upload_batches, users`); `\di` → 19 indexes (incl. PK/unique)
  - `psql -v ON_ERROR_STOP=1 < tests/sql/schema_constraints.sql` → exit 0; 21 bad rows rejected with the expected SQLSTATE (e.g. `ok credit score above 900 (rejected, 23514)`, `ok duplicate chunk delivery (rejected, 23505)`, `ok user_id not a UUID (rejected, 22P02)`, `ok unknown batch (rejected, 23503)`), plus `ok redelivered chunk is a no-op`, `ok updated_at set by trigger`, `ok product with all-NULL criteria accepted`. The script rolls back, so T13 can rerun it on RDS.
  - The first run failed on a typo in the test itself (`42701` duplicate column in the INSERT), which showed the harness rejects a wrong SQLSTATE. The test was fixed; the schema was not changed.
  - Real sample through every CHECK: `\copy` of `data/users.csv` into staging → `INSERT INTO users … SELECT` (trim, lower-case email) → `users_loaded = 10000`, rolled back
  - `make check` → `All checks passed!`, `19 files already formatted`, `Success: no issues found in 9 source files`, `5 passed`, coverage floor reached (no Python touched)
  - Secrets scan on `db/`, `tests/sql/` → no matches
- Rubric: Backend & Code Quality (schema with CHECK constraints, ledger tables, self-asserting constraint tests), n8n (Treasure Hunt tables: `pipeline_runs`, `cohort_verdicts`, `llm_calls`).
- Explain it back:
  - Built: the full Postgres schema. Ingestion bookkeeping (batches, chunk ledger, rejects), users, products, matches, and the tables that measure the matching funnel and the LLM cost. Plus a SQL test that proves each constraint rejects bad data.
  - Why this approach over the obvious alternative (loose columns, all checks in Python): validation in code gives good reject reasons, but only the database sees every write path, including n8n's Postgres nodes. CHECKs make a bad row impossible, not just unlikely, and the real sample proves they reject no valid data.
  - Q: Why isn't `email` unique? A: In the sample 7,368 rows share an email with another user (each address is used 2–5 times). Only `user_id` is unique, so it is the primary key and the upsert key.
  - Q: How does the schema make SQS redelivery safe? A: `chunk_loads` has primary key `(batch_id, chunk_no)`. A redelivered chunk's `INSERT … ON CONFLICT DO NOTHING RETURNING` gets no row back, so the Lambda acknowledges and exits without loading anything twice. The test script shows this.
  - Q: How does a product change invalidate cached LLM verdicts without a purge job? A: `cohort_verdicts` is keyed by `(cohort_key, product_content_hash)`. When Workflow A sees new criteria text, the product gets a new hash, so lookups for it miss and the old rows are simply never read again.

### T09 — Migrations + seed (2026-10-20)
- Files: `db/migrate.py` (new), `db/__init__.py` (new), `db/seed_products.sql` (new), `db/schema.sql` (own `BEGIN`/`COMMIT` removed, header updated), `tests/unit/test_migrate.py` (new), `tests/integration/__init__.py` + `tests/integration/test_migrate_db.py` (new), `pyproject.toml` (`pg8000` dependency; `db` added to mypy; pg8000 untyped-import override), `uv.lock`, `.env.example` (`DB_SSLROOTCERT`)
- Choices:
  - Ledger table `schema_migrations(version, checksum, applied_at)`. Migrations are an explicit, append-only tuple in `migrate.py`, not a glob, so order is visible in code review.
  - One transaction per run, under `pg_advisory_xact_lock`: every pending file and its ledger row commit together or not at all, and two concurrent runners apply in turn. Because of this, `schema.sql` no longer carries its own `BEGIN`/`COMMIT` (an inner COMMIT would end the transaction before the ledger row). To apply it by hand, use `psql -1`.
  - Drift guard: the SHA-256 of each applied file is stored. An edited applied file, or a database with versions the code doesn't know, is refused with no changes.
  - Seed: 5 products, labeled three ways (`source='seed'`, `is_seed=true`, "Seed ·" name prefix, plus "SEED DATA." at the start of the criteria text). Thresholds sit inside the sample's ranges. One product has an uncaptured free-text criterion (business vintage) for Stage 2's borderline path. One `INSERT … ON CONFLICT DO UPDATE … WHERE p.is_seed AND (…) IS DISTINCT FROM (…)`, so a re-run changes 0 rows and can never rewrite a crawled product. `content_hash` is computed in SQL (SHA-256 hex, same format as Workflow A).
  - Driver: pg8000 (same as the Lambdas). `DB_SSLROOTCERT` → `ssl.create_default_context(cafile=…)` (verifies chain and hostname). Without it the connection is plain, which RDS refuses (`rds.force_ssl`), so there is no silent unencrypted path. The TLS path runs for the first time in T13.
  - Seed products are `active = true`, so matching works before any crawl. Whether to deactivate them once real products exist is decided in T31.
- Evidence (throwaway `postgres:16` container, `PostgreSQL 16.15`, removed afterwards):
  - Run 1, `uv run python -m db.migrate --seed` → `{"stage": "migration_applied", "version": "0001_schema", "duration_ms": 29}`, `{"stage": "migrations_done", "applied": ["0001_schema"], "count": 1}`, `{"stage": "seed_done", "count": 5}`, exit 0
  - Run 2, same command → `{"stage": "migrations_done", "applied": [], "count": 0}`, `{"stage": "seed_done", "count": 0}`, exit 0
  - `SELECT … FROM loan_products` → 5 rows, all `source = seed`, `is_seed = t`, names `Seed · Salaried Personal Loan`, `Seed · Self-Employed Personal Loan`, `Seed · Premium Personal Loan`, `Seed · Starter Personal Loan`, `Seed · Business Loan Lite`
  - `schema_migrations` → `0001_schema | c1883e8530f1… | 2026-10-20 18:29:47+00`
  - `psql -v ON_ERROR_STOP=1 < tests/sql/schema_constraints.sql` on the migrated DB → exit 0, all T08 checks `ok` (regression check after removing `BEGIN`/`COMMIT`)
  - Missing env → `{"stage": "failed", "error": "missing environment variables: DB_HOST, …"}`, exit 1
  - `TEST_DB_HOST=127.0.0.1 … pytest tests -q` → `20 passed` (incl. 5 integration: re-run no-op, seed flagged and hashed, seed never rewrites a non-seed row, edited migration refused, failed migration rolls back everything)
- Quality gates (`make check`, no DB configured, so the 5 integration tests skip): `All checks passed!`, `24 files already formatted`, `Success: no issues found in 14 source files`, `15 passed, 5 skipped`, coverage floor reached (`lambdas/shared` still empty; floor bites in T14)
- Secrets scan: only variable names (`DB_PASSWORD`, `password=`) and the `TEST_DB_PASSWORD=...` usage example.
- Rubric: Backend & Code Quality (idempotent checksummed migrations, atomic apply, drift refusal, DB-backed tests), Docs/honesty (seed data labeled in four places).
- Explain it back:
  - Built: a migration runner that applies each schema file exactly once and records it with a checksum, plus 5 clearly labeled seed products, so every later environment (local, RDS in T13) is built by one command that is safe to repeat.
  - Why this approach over the obvious alternative (run `psql -f schema.sql` once, or use Alembic): a bare psql run fails or half-applies the second time, and nothing records what was applied. Alembic adds SQLAlchemy and a models layer the project doesn't use. ~150 lines of runner with a ledger, a lock and a checksum give the same guarantees for plain SQL files.
  - Q: What happens if someone edits `schema.sql` after it was applied to RDS? A: The stored SHA-256 no longer matches, so `migrate.py` refuses and changes nothing. Schema changes must be a new migration file (e.g. T25's `n8n_errors`), which keeps RDS and the repo provably in sync.
  - Q: Why did `schema.sql` lose its `BEGIN`/`COMMIT`? A: The runner applies a file and inserts its ledger row in one transaction. An inner `COMMIT` would commit the schema before the ledger row, so a crash between them would leave tables with no record and the next run would fail on `CREATE TABLE`. The integration test shows a failing migration rolls back all of it.
  - Q: Could the seed overwrite a real crawled product or cause fake matches to look real? A: No. The upsert's `WHERE p.is_seed` means it only rewrites seed rows (tested), and every seed row is marked `source='seed'`, `is_seed=true`, "Seed ·" in its name and "SEED DATA." in its criteria, so any email, UI or query can show or filter it.

### T10 — serverless.yml base (2026-10-21)
- Plan approved by the user ("go"): Serverless v3; placeholder SSM values for the DB host and n8n URL until T11/T12.
- Files: `serverless.yml` (new, repo root), `package.json` + `package-lock.json` (serverless 3.40.0, serverless-python-requirements 6.1.2), `infra/requirements-lambda.txt` (runtime deps exported from `uv.lock`), `lambdas/{get_upload_url,split_csv,load_chunk,batch_status}/handler.py` (501 stubs, replaced in T15/T17/T18/T20), `Makefile` (`make package`, `npm ci` in `make install`), `docs/decisions.md` (new section 20 "Infrastructure as code"; IAM section: ENI `*` explained)
- Deviation from CLAUDE.md §3: `serverless.yml` is at the repo root, not `infra/`. Serverless v3 rejects a config outside the working directory and ignores a symlink (its config lookup checks for a regular file), and it cannot package `../lambdas`. Both attempts' errors are in this session's output.
- Built:
  - Provider: python3.12, arm64, `ap-southeast-2`, profile `clickpe`, 14-day log retention, no reserved concurrency anywhere.
  - S3 `clickpe-loan-uploads-<account>-<stage>`: all four public-access blocks, SSE-S3, CORS POST from the UI origin only (`--ui-origin`, default `http://localhost:8000`), `uploads/` expire after 7 days, TLS-only bucket policy, `ObjectCreated` on `uploads/*.csv` → `splitCsv` (permission scoped by `SourceAccount` + `SourceArn`).
  - SQS `ingest` (visibility 720 s = 6 × the 120 s `loadChunk` timeout, SSE) → `ingest-dlq` after 5 receives, 14-day retention.
  - `loadChunk` ESM: `BatchSize 1`, `ScalingConfig.MaximumConcurrency 3`, `ReportBatchItemFailures`.
  - Network: S3 Gateway Endpoint on the default VPC main route table. Lambda SG egress only to 5432 and 5678 inside the VPC CIDR and 443 to the S3 prefix list `pl-6ca54005`. `splitCsv` runs outside the VPC; the other three run inside.
  - One IAM role per function with per-function statements: logs on its own log group only; `s3:PutObject`/`GetObject` on `uploads/*` only; SQS send or receive on the one queue.
  - Function URLs (`getUploadUrl` POST, `batchStatus` GET), CORS to the UI origin, `lambda:InvokeFunctionUrl` plus `lambda:InvokeFunction` with `InvokedViaFunctionUrl: true`.
  - SSM: `/clickpe/db/host` (String, placeholder), `/clickpe/n8n/webhook_url` (String, placeholder), `/clickpe/db/password` and `/clickpe/n8n/webhook_secret` (SecureString, `openssl rand`, never displayed). All created with `--no-overwrite`, version 1.
- Bugs found by verification, then fixed: (1) `get_upload_url`-style keys became `GetUnderscoreuploadUnderscoreurlLambdaFunction` logical IDs, so the hand-written `!Ref`s dangled; keys are now camelCase. (2) `aws cloudformation validate-template` → `Circular dependency between resources: [... UploadBucket, SplitCsvS3InvokePermission, SplitCsvLambdaFunction, SplitCsvRole ...]`; roles and env now use the deterministic bucket name instead of `!GetAtt UploadBucket.Arn`.
- Evidence:
  - `npx serverless package` → `✔ Service packaged (1s)`; zip 372,300 bytes containing `lambdas/`, `pg8000`, `scramp`, `asn1crypto`, `dateutil`, `six` (arm64 requirements cache)
  - Only warning: `at 'provider.runtime': must be equal to one of the allowed values [... python3.11 ...]`. The v3 schema predates 3.12; the template carries `python3.12` unchanged.
  - `aws cloudformation validate-template --template-body file://.serverless/cloudformation-template-update-stack.json` → valid (`The AWS CloudFormation template for this Serverless application`)
  - `uvx cfn-lint --regions ap-southeast-2` → exit 0; 4 × `W3005` (redundant DependsOn generated by the framework), no errors
  - Script over the template: `dangling refs: []`. Functions: python3.12 / arm64 / `ReservedConcurrentExecutions None`. ESM `{"BatchSize": 1, "FunctionResponseTypes": ["ReportBatchItemFailures"], "ScalingConfig": {"MaximumConcurrency": 3}}`
  - IAM review (script flags every `*` resource or `*`/`service:*` action): no wildcard actions. The only `Resource: "*"` is `ec2:Create/Describe/DeleteNetworkInterface` on the 3 VPC roles (required for VPC Lambdas; see decisions.md → IAM)
  - `git check-ignore -v .serverless/… node_modules` → both ignored (the packaged template contains resolved SecureString values)
  - Secrets scan: only `${ssm:/…}` references in `serverless.yml`
- Not verified yet: an actual `sls deploy`. The stack is deployed in T22, after RDS (T11) and EC2 (T12) exist. `validate-template` and `cfn-lint` check schema and references, not runtime behaviour.
- Quality gates (`make check`): `All checks passed!`, `28 files already formatted`, `Success: no issues found in 18 source files`, `15 passed, 5 skipped`, coverage floor reached
- SSM commands (for the README; replace placeholders in T11/T12 with `--overwrite`):
  ```bash
  aws ssm put-parameter --profile clickpe --name /clickpe/db/host --type String --value <rds-endpoint> --overwrite
  aws ssm put-parameter --profile clickpe --name /clickpe/db/password --type SecureString --value "$(openssl rand -hex 24)" --no-overwrite
  aws ssm put-parameter --profile clickpe --name /clickpe/n8n/webhook_url --type String --value http://<ec2-private-ip>:5678/webhook/match-batch --overwrite
  aws ssm put-parameter --profile clickpe --name /clickpe/n8n/webhook_secret --type SecureString --value "$(openssl rand -hex 32)" --no-overwrite
  ```
- Rubric: Cloud Architecture (presigned-POST-ready bucket, S3 → SQS → Lambda with DLQ and concurrency cap, Gateway Endpoint instead of NAT/interface endpoints, least-privilege per-function IAM, Function URL permissions, all in one IaC file).
- Explain it back:
  - Built: the whole AWS skeleton as code. A private, TLS-only upload bucket that triggers a splitter, a queue with a DLQ feeding a loader capped at 3 concurrent runs, a free S3 endpoint for VPC Lambdas, a locked-down security group, and one minimal role per function. It packages and validates; it deploys in T22.
  - Why this approach over the obvious alternative (framework defaults: one shared role, the `s3:` event with `existing: true`, `AWSLambdaVPCAccessExecutionRole`): defaults give every function every other function's permissions, add a custom-resource Lambda with its own role to wire S3 events, and grant `logs:*` on `*`. Hand-written roles and a bucket-level notification keep each grant visible and minimal at the cost of ~150 lines of YAML.
  - Q: Why does the visibility timeout say 720 and not 120? A: If a loader takes the full 120 s and the message becomes visible again too early, a second loader would process the same chunk in parallel. AWS recommends at least 6× the function timeout for SQS event sources, so 720 s. The chunk ledger makes a duplicate harmless anyway, but this avoids the wasted work and the extra receive counts that could push a healthy chunk to the DLQ.
  - Q: How do VPC Lambdas reach S3 without a NAT Gateway? A: A Gateway Endpoint adds a route for S3's prefix list to the VPC route table. It is free, and the security group allows 443 only to that prefix list. SQS is never called from inside the VPC: the Lambda service polls the queue for `loadChunk`, and `splitCsv`, which sends messages, runs outside the VPC.
  - Q: Your Function URLs are `AuthType NONE`. Isn't `Principal: "*"` on `lambda:InvokeFunction` dangerous? A: That permission carries `InvokedViaFunctionUrl: true`, so it allows only invocations that arrive through the URL, not direct `Invoke` API calls. The URLs themselves are public by design (the browser has no AWS credentials). The mitigations are CORS restricted to the UI origin, the S3 POST policy's size and key limits, and the documented API Gateway upgrade path.

#### T10 review — `serverless.yml` re-checked on Opus (2026-10-21)
- Requested by the user after T10: the model-picker preset for T10 is `opus @ high` and the task had been built on Sonnet.
- Files: `serverless.yml`, `scripts/check_package.py` (new), `Makefile` (`package` runs the import check), `pyproject.toml` (mypy covers `scripts/`), `docs/decisions.md`
- Fixed:
  1. **Critical: the packaged zip could not import pg8000.** `slim: true` removed every `dist-info` folder (`unzip -l … | grep -c dist-info` → `0`), and `scramp/__init__.py:12` does `__version__ = version("scramp")`. A system `python3` importing from the extracted zip → `importlib.metadata.PackageNotFoundError: No package metadata was found for scramp`. `getUploadUrl`, `loadChunk` and `batchStatus` would all have crashed at cold start, first visible in T22. Fix: `slim: false` plus `npx serverless requirements cleanCache` (the plugin had reused the slim build).
  2. **New guard, `scripts/check_package.py`.** It extracts the zip and imports `pg8000.native` and all 4 handlers in `python -I -S` with only the zip on `sys.path`. Its first version used `-I` only and wrongly passed on the broken zip, because the venv's site-packages supplied `scramp`'s metadata. With `-S`, the old zip → `{"stage": "package_imports_failed", … "pg8000.native": "importlib.metadata.PackageNotFoundError: No package metadata was found for scramp"}` (exit 1). New zip → `{"stage": "package_imports_ok", "count": 5, "failures": {}}`, 838,217 bytes, with `METADATA` for asn1crypto, pg8000, python_dateutil, scramp, six.
  3. **`splitCsv` failures were silent.** An async S3 invoke that kept failing was dropped after 2 retries and the batch stayed `pending`. Added `maximumRetryAttempts: 2`, `maximumEventAge: 3600` and an on-failure destination, queue `split-failures` (14-day retention, SSE). `SplitCsvRole` may `sqs:SendMessage` to it. Template: `SplitCsvLambdaEvConf` → `{"DestinationConfig": {"OnFailure": {"Destination": "arn:aws:sqs:ap-southeast-2:376834080732:clickpe-loan-engine-dev-split-failures"}}, "MaximumEventAgeInSeconds": 3600, "MaximumRetryAttempts": 2}`.
  4. **The upload size cap was defined only for `splitCsv`.** `getUploadUrl` needs the same value for the POST policy's `content-length-range` (T15). Moved to `custom.maxUploadBytes`, used by both (template shows `20971520` on each).
  5. **Documented the second copy of the secrets.** The packaged/deployed CloudFormation template holds the SecureString values as literals (decisions.md → Secrets).
- Checked and found correct (live account, 2026-10-21):
  - No S3 endpoint exists yet in `vpc-0cddb8b4387b5bbdc` (`describe-vpc-endpoints` → empty), so the Gateway Endpoint will not collide.
  - The main route table `rtb-00f1e10252170f96a` has only the `Main` association, so all 3 default subnets use it implicitly and the endpoint route reaches every Lambda subnet.
  - Lambda account concurrency is still 10.
  - The remaining items also hold: visibility 720 = 6 × 120 with DLQ retention (14 d) longer than source (4 d); ESM IAM; log ARNs match the generated log-group names; the SG egress list replaces AWS's default allow-all; DNS to the VPC resolver is not filtered by security groups; the Function URL `InvokedViaFunctionUrl` permission.
- Accepted, not changed (low; for README Limitations):
  - VPC, subnet and route-table IDs are hard-coded in `custom`. Correct for this account, but another account must edit 5 values.
  - The Gateway Endpoint keeps the default full-access policy, because the main route table is shared with the EC2 host.
  - `provider.profile: clickpe` is fixed, which suits a single developer.
- Evidence after the fixes: `make package` → `✔ Service packaged`, `package_imports_ok`; `validate-template` → valid; `cfn-lint` → exit 0, 4 × `W3005` only; `make check` → `All checks passed!`, `29 files already formatted`, `Success: no issues found in 19 source files`, `15 passed, 5 skipped`, coverage floor reached.
- Explain it back:
  - Q: Why didn't `validate-template` or `cfn-lint` catch the pg8000 crash? A: They check the CloudFormation template, not the code inside the zip. Only importing the packaged code in a clean interpreter shows it, which is why that check is now part of `make package`.
  - Q: Why a separate `split-failures` queue instead of reusing `ingest-dlq`? A: The two hold different things. `ingest-dlq` holds chunk messages that can be redriven back into `ingest`. `split-failures` holds Lambda's async-failure records (the S3 event plus an error), and redriving those into `ingest` would feed `loadChunk` a message it cannot parse.
  - Q: Why did the import check first pass on a broken zip? A: `-I` only drops env vars and the user site. The venv's own site-packages was still on the path, and `importlib.metadata` found `scramp`'s metadata there. `-S` removes site-packages entirely, so the zip is the only source, as in Lambda. The check was confirmed to fail on the old zip before being trusted.

### T11 — RDS (2026-10-21)
- Files: infra/rds.md (new: settings table, exact commands, privacy proof)
- AWS resources: SG `clickpe-rds-sg` (`sg-0f0ca5e2b7cb5e1c3`, no inbound rules), subnet group `clickpe-db-subnets`, instance `clickpe-db`; SSM `/clickpe/db/host` set (version 2)
- Incident: first run left `$SG` empty (group already existed), so `create-db-instance` fell into CLI help; the AWS pager also hid output. Fixed with `AWS_PAGER=""` and the literal SG ID; noted in `infra/rds.md`.
- Evidence:
  - `describe-db-instances` → class `db.t4g.micro`, engine 16.9, gp3 20 GB, encrypted, `MultiAZ false`, `PubliclyAccessible false`, `DeletionProtection true`, backups 1 day, parameter group `default.postgres16`, SG `sg-0f0ca5e2b7cb5e1c3`
  - `getent hosts <endpoint>` from laptop → `172.31.32.255` (private); TCP 5432 → `No route to host`
  - `describe-security-groups` → `IpPermissions: []`
- Completed in T12 from the EC2 host: `verify-full` connection on TLSv1.3, `sslmode=disable` rejected, `rds.force_ssl` = 1, `max_connections` = 79 (see the T12 entry). Still pending: 5432 ingress from the Lambda SG, added after `sls deploy` (T22).
- Quality gates: no Python touched. Secrets scan: endpoint is not a secret; password only read from SSM inside a command substitution.
- Rubric: Cloud Architecture (private RDS, SG-reference-only ingress, encrypted storage)
- Explain it back:
  - Q: How do you prove the database is private, not just firewalled? A: Public DNS returns only the private VPC address, so the internet has no route to it at all; the SG would be a second layer.
  - Q: Why open 5432 by security-group reference instead of the VPC CIDR? A: Only ENIs carrying the Lambda or n8n SG can connect; anything else launched in the VPC cannot, and IPs can change.
  - Q: Why not Multi-AZ or a bigger class? A: Demo scale and cost; COPY plus the MaximumConcurrency 3 cap keeps load low. Multi-AZ is the documented production upgrade.

### T12 — EC2 for n8n (2026-10-21)
- Files: `infra/ec2/setup.sh` (new), `infra/ec2.md` (new), `docs/rubric-evidence.md`, `PROGRESS.md`
- AWS resources: SG `clickpe-n8n-sg` (`sg-0fd3ef0dd40c9f8e3`, no inbound rules), role `clickpe-n8n-ec2-role` + instance profile `clickpe-n8n-ec2-profile` (`AmazonSSMManagedInstanceCore`), instance `i-02ffa9d08e8403a4a` (`t4g.small`, AMI `ami-0fd1d82a0cfcbc33c`, private IP `172.31.26.164`), ingress rule on `clickpe-rds-sg` 5432 from the n8n SG. The temporary `clickpe-cloudshell-tmp` SG used for an earlier check was revoked and deleted.
- Evidence:
  - `aws ssm describe-instance-information` → `i-02ffa9d08e8403a4a  Online` with `IpPermissions: []` on the n8n SG
  - `aws ssm start-session` opened an interactive shell as `ssm-user` on the instance
  - Run Command of `infra/ec2/setup.sh` → `Success`, `Docker version 25.0.14, build 0bab007`, `Docker Compose version v2.29.7`, `/swapfile file 2G`
  - From the instance, `psql … sslmode=verify-full sslrootcert=/opt/clickpe/global-bundle.pem` → `max_connections` 79; `pg_stat_ssl` → `ssl t`, `TLSv1.3`, `TLS_AES_256_GCM_SHA384`
  - `psql … sslmode=disable` → `FATAL: no pg_hba.conf entry for host "172.31.26.164", user "clickpe", database "clickpe", no encryption`
  - `aws rds describe-db-parameters --db-parameter-group-name default.postgres16` → `rds.force_ssl  1  system`
- Corrections made during the task: (1) `SHOW rds.force_ssl` returns `unrecognized configuration parameter` because it is an RDS parameter-group setting; the value was read through the RDS API and the `pg_hba` rejection proves enforcement. (2) The instance profile's creation output showed `"Roles": []` because it is printed before the role is attached; the launch with the profile succeeded and SSM registered the instance, which shows the role is attached. (3) The laptop had `PGPORT=5433` set; the in-VPC command now sets `port=5432` explicitly.
- Quality gates: no Python touched, `setup.sh` is shell only. Secrets scan: the DB password was read from SSM into the shell's memory with `read -rs` and was never written to a file or command parameter.
- Not done yet: 5678 ingress from the Lambda SG (the SG exists only after `sls deploy`, T22) and the SES-only role (T24).
- Rubric: Cloud Architecture (no-NAT VPC design, n8n with zero inbound ports reached through SSM, IMDSv2, SG-reference-only RDS ingress).
- Explain it back:
  - Built: an n8n host with no way in from the internet. SSM Session Manager is the only admin path, outbound goes through the free Internet Gateway, and the host reaches RDS over the private network using verified TLS.
  - Why this approach over the obvious alternative (a public IP with SSH or an open 5678 locked to my IP): an IP allowlist breaks when the laptop's IP changes and still exposes a port. SSM needs no inbound rule at all, authenticates through IAM, and keeps the editor off the internet. The cost is a plugin on the laptop and a port forward.
  - Q: How do you know unencrypted database access is blocked? A: A `sslmode=disable` connection from the instance is rejected by `pg_hba` with "no encryption", and the RDS parameter `rds.force_ssl` is 1.
  - Q: Why hop limit 2 on the instance metadata service? A: n8n will run in a Docker container, which adds a network hop. With the default limit of 1 the container cannot reach the instance role for the SES credentials in T24. IMDSv2 stays required, so the token requirement still blocks simple SSRF-style access.
  - Q: The instance has a public IP, so is it exposed? A: The IP is only for outbound traffic. The security group has no inbound rules, so nothing can connect to it. Using a private subnet instead would need a NAT Gateway, which costs about $32 a month and is excluded by the cost rules.

### T13 — Migrate RDS (2026-10-21)
- Files: `infra/ec2/migrate.sh` (new), `docs/rubric-evidence.md`, `PROGRESS.md`
- Method: `db/` and `migrate.sh` were shipped to `/opt/clickpe/migrate` on the EC2 host with SSM Run Command (schema SHA-256 matched the local file). `migrate.sh` builds a `python:3.12-slim` image with `pg8000==1.31.5` and runs `python -m db.migrate --seed` with the RDS CA bundle mounted, so the certificate is verified. The password was typed with `read -rs` in an SSM session and never written to a file or command parameter.
- Evidence (from the SSM session):
  - First run: `{"stage": "migration_applied", "version": "0001_schema", "duration_ms": 99}`, `{"stage": "seed_done", "count": 5}`
  - Second run: `{"stage": "migrations_done", "applied": [], "count": 0}`, `{"stage": "seed_done", "count": 0}`
  - `\dt` → `chunk_loads, cohort_verdicts, crawl_runs, llm_calls, loan_products, matches, pipeline_runs, rejected_rows, schema_migrations, upload_batches, users` (11 rows)
  - `SELECT count(*), bool_and(is_seed) FROM loan_products;` → `5 | t`
- Mistakes fixed along the way: (1) the first attempt pasted the `read` line and the following lines together, so `read` consumed the `export DB_HOST…` line as the password and no variables were set; nothing reached the database. (2) `sudo docker run -e VAR` lost the variables because `sudo` resets the environment; the script now uses `sudo -E`.
- Open finding for T14/T22: `serverless.yml` sets `dbName: loans` and `dbUser: loans_app`, but RDS has database `clickpe`, user `clickpe`, and no `loans_app` role. Must be aligned before the Lambdas connect (preferably a least-privilege `loans_app` role).
- Quality gates: no Python touched (shell script only). Secrets scan: only variable names in `migrate.sh`.
- Rubric: Backend (idempotent, checksummed migrations applied to the real database), Cloud (migration run from inside the VPC over verified TLS).
- Explain it back:
  - Built: the schema and seed applied to the private RDS instance from the EC2 host, with a repeatable script.
  - Why this over the obvious alternative (open RDS publicly or tunnel from the laptop): RDS stays private, and the EC2 host is already inside the VPC. A container avoids installing Python packages on the host.
  - Q: How do you know the migration is idempotent? A: The second run reported `applied: []` and `seed_done count 0`; the ledger stores a SHA-256 per file and refuses edited files.
  - Q: Why not pass the password to Run Command? A: SSM keeps command history, so the value would be stored; the interactive prompt keeps it in shell memory only.
  - Q: Why `sudo -E`? A: `sudo` resets the environment, so `docker run -e DB_HOST` would pass nothing; `-E` keeps the exported variables.

### T14 — Shared modules (2026-10-21)
- Files: `lambdas/shared/config.py`, `lambdas/shared/db.py`, `lambdas/shared/batches.py`, `lambdas/shared/logging.py`, `lambdas/shared/rds-global-bundle.pem` (all new); `tests/unit/test_config.py`, `tests/unit/test_db.py`, `tests/unit/test_logging.py`, `tests/unit/test_batches.py`, `tests/integration/test_batches_db.py` (new); `scripts/check_package.py` (shared modules + CA bundle added to the zip check)
- Choices:
  - `config.py`: one frozen dataclass per Lambda (`upload_url_config`, `split_csv_config`, `load_chunk_config`, `batch_status_config`), variable names exactly as in `serverless.yml`. A reader collects every problem, then raises one `ConfigError` listing them all, at cold start. `DbConfig`/`WebhookConfig` override `__repr__`, so the password and webhook secret never reach a log line.
  - TLS: the RDS global CA bundle (114 certificates, 3 for ap-southeast-2, SHA-256 `90a6f1a7…f21b`, fetched from `truststore.pki.rds.amazonaws.com`) ships inside `lambdas/shared/`. There is no environment value that disables TLS: `DB_SSLROOTCERT` can only point at another bundle. Plain connections exist only for tests, which build `DbConfig(ca_bundle=None)` in code. Note: `db/migrate.py` keeps its T09 behaviour (blank `DB_SSLROOTCERT` → plain, which RDS refuses).
  - `db.py`: `Database` caches one pg8000 connection per warm Lambda, checks it with `SELECT 1` before reuse, and replaces it once if it is dead or stuck in an aborted transaction. `transaction()` commits on success, rolls back on any exception, and never lets a failed ROLLBACK hide the original error.
  - `batches.py`: explicit `TRANSITIONS` table (`pending → loading → processed → matching → matched → notifying → notified`, `failed` from pending/loading/matching/notifying). An invalid transition raises `InvalidTransitionError` before any SQL is sent. Every change is `UPDATE … WHERE status = <expected> RETURNING`. The ledger is split into `claim_chunk` (first statement of the chunk transaction, `ON CONFLICT DO NOTHING`) and `finish_chunk` (last statement, adds the counts), because the counts are not known when the chunk is claimed, and claiming first makes a concurrent duplicate wait on the key instead of redoing the work. `start_loading` is called by every chunk message and refuses a chunk count that differs from the stored one. `try_complete` runs in autocommit **after** the commit, and also on duplicate deliveries, so a Lambda that crashed between commit and check is finished by its redelivery.
  - The schema status `splitting` is not in `TRANSITIONS`: `split-csv` runs outside the VPC and never writes to RDS (decided in T07), so nothing can set it.
  - `logging.py`: `JsonFormatter` swapped onto the Lambda runtime's existing root handler (keeps `request_id`); `log_event(logger, stage, **fields)`; `timed(...)` adds `duration_ms` and `outcome`, and logs failures at ERROR before re-raising.
- Evidence (throwaway `postgres:16` container on 127.0.0.1:55432, password generated into a mode-600 scratch file, both removed afterwards):
  - `TEST_DB_HOST=127.0.0.1 TEST_DB_PORT=55432 … pytest tests/integration -q` → `15 passed` (5 T09 + 10 new)
    - `test_invalid_transition_is_rejected_and_the_row_is_unchanged`, `test_stale_transition_changes_nothing`
    - `test_duplicate_chunk_delivery_is_a_no_op` → batch row `['loading', 2, 1, 10, 1]`, one ledger row
    - `test_concurrent_duplicate_waits_for_the_first_delivery` → the second claim is still blocked after 0.5 s; it returns False when the first commits and True when the first rolls back
    - `test_completion_checked_inside_the_transaction_would_be_missed` → both in-transaction checks return False and the batch stays `loading`; after commit one check wins
    - `test_redelivery_after_a_crash_before_the_check_finishes_the_batch` → `['processed', 2, 2, 20, 2]`
    - `test_concurrent_finishers_complete_exactly_once[checks-aligned]` and `[interleaved]` → 6 threads × 25 trials each; winners per trial `[1] * 25` in both modes
  - Mutation probe: with `try_complete`'s guard weakened to `status IN ('loading', 'processed')`, the race test fails with `assert [6, 6, 6, 6, 6, 6, ...] == [1, 1, 1, 1, 1, 1, ...]`, so the test does catch a double trigger. File restored (`cmp` identical).
  - Full suite with DB → `71 passed in 4.57s`, `Total coverage: 98.60%`
  - `make package` → `{"stage": "package_imports_ok", "count": 9, "failures": {}}` (4 handlers, 4 shared modules, pg8000 import from the zip alone; CA bundle present in the zip)
- Not verified here: the TLS handshake from a Lambda to RDS (RDS is private, so it is reachable only from inside the VPC). It runs for the first time in T22. The same `create_default_context(cafile=…)` path was verified from EC2 in T13.
- Still open (from T13): `serverless.yml` uses `dbName: loans`, `dbUser: loans_app`, but RDS has database `clickpe`, user `clickpe`. To be aligned before T22 (preferably a least-privilege `loans_app` role).
- Quality gates (`make check`, no DB): `All checks passed!`, `40 files already formatted`, `Success: no issues found in 28 source files`, `56 passed, 15 skipped`, `Required test coverage of 80.0% reached. Total coverage: 97.89%` (batches 100%, config 97%, db 96%, logging 98%)
- Secrets scan on the touched files: only variable names and the fake test values `pw-value` / `secret-value`.
- Rubric: Backend & Code Quality (typed modular shared package, fail-fast config, structured logs, 98% coverage, DB-backed concurrency tests with a mutation probe), Cloud (verified TLS to RDS packaged in the Lambda; exactly-once n8n trigger foundation).
- Explain it back:
  - Built: the four modules every Lambda uses. Config that fails at cold start, a reused verified-TLS database connection, JSON logs, and the batch state machine with the chunk ledger that makes SQS redelivery harmless and triggers n8n exactly once.
  - Why this approach over the obvious alternative (a `chunks_done = chunks_done + 1` counter checked inside the chunk transaction): a counter double-counts a redelivered message, and a check inside the transaction cannot see another chunk's uncommitted row, so two last chunks can both miss completion. The test `test_completion_checked_inside_the_transaction_would_be_missed` shows that case; the ledger plus a post-commit conditional UPDATE fixes both.
  - Q: Two chunks commit at the same moment and both run `try_complete`. Why can't both trigger n8n? A: Both UPDATEs target the same batch row. The first takes the row lock and sets `processed`; the second waits, then Postgres re-checks its WHERE against the committed row, `status = 'loading'` is now false, and it gets no row back. 25 aligned trials gave exactly one winner each; removing the guard gave 6.
  - Q: Can both last chunks miss completion and leave the batch stuck in `loading`? A: Not after commit. Each check starts after its own commit, so whichever check starts later sees both ledger rows. If a Lambda dies between commit and check, SQS redelivers the message, `claim_chunk` returns False, and `try_complete` still runs (tested).
  - Q: Why reuse one connection instead of a pool or RDS Proxy? A: A Lambda instance handles one request at a time, so a pool adds nothing; caching the connection skips the TLS + SCRAM handshake on warm starts. With `MaximumConcurrency 3` plus two Function URL Lambdas, connections stay far below RDS's `max_connections` of 79. RDS Proxy is the production upgrade (paid; it would also need an interface-endpoint-free design check).

### T15 — get-upload-url (2026-10-21)
- Files: `lambdas/shared/uploads.py` (new), `lambdas/get_upload_url/handler.py` (stub replaced), `tests/unit/test_uploads.py`, `tests/unit/test_get_upload_url.py` (new), `scripts/check_package.py` (`lambdas.shared.uploads` added), `pyproject.toml` + `uv.lock` (`boto3` dev dependency only, the Lambda runtime provides it; mypy override), `docs/decisions.md` (upload section)
- Choices:
  - `uploads.presigned_upload` is a pure function over a small `S3PostSigner` protocol, so the policy is unit-tested by decoding a real signature. The handler only parses the event, calls `create_batch` and `presigned_upload`, and formats JSON.
  - The handler builds config, `Database` and the S3 client on the first invocation (`functools.cache`), not at import. `scripts/check_package.py` imports every handler with no env and no site-packages, so an import-time `ConfigError` or a top-level `import boto3` would fail the packaging check. boto3 is imported inside `new_s3_client`.
  - Only POST is served (405 otherwise, nothing touched). A database error returns 503 `{"error": "database unavailable"}` and resets the cached connection; no signed upload is returned in that case.
  - The response includes every form field S3 needs. When the role's temporary credentials sign the policy, boto3 adds `x-amz-security-token` to `fields`, so T40 must send every returned field, in order, before the file.
- Bug found by verification: the `url` boto3 returned was `https://<bucket>.s3.amazonaws.com/` even with SigV4. `curl -F -w '%{http_code} -> %{redirect_url}'` against that host for the Sydney bucket → `307 -> https://clickpe-t15-tmp-376834080732.s3-ap-southeast-2.amazonaws.com/`. A browser does not follow that on a cross-origin form post. Fixed by pinning `endpoint_url=https://s3.<region>.amazonaws.com` and virtual-hosted addressing; the unit test `test_url_is_the_regional_bucket_endpoint` caught it first (an intermediate attempt without `addressing_style` gave a path-style URL).
- Evidence (handler run locally against a throwaway `postgres:16` migrated with `db.migrate`, and a temporary bucket `clickpe-t15-tmp-376834080732` in ap-southeast-2; the handler output was posted with `curl -F`):
  - Handler → `200`, url `https://clickpe-t15-tmp-376834080732.s3.ap-southeast-2.amazonaws.com/`, fields `Content-Type, key, policy, x-amz-algorithm, x-amz-credential, x-amz-date, x-amz-signature`, `max_upload_bytes 20971520`, `expires_in_seconds 300`
  - `SELECT id, s3_key, status, total_chunks FROM upload_batches` → `edb1b536-… | uploads/edb1b536-….csv | pending | (null)`
  - A. valid 158-byte fixture → `HTTP 204`; `head-object` → `ContentType text/csv`, `ContentLength 158`
  - B. 22,020,096-byte file → `HTTP 400`, `<Code>EntityTooLarge</Code>`, `<ProposedSize>20973881</ProposedSize><MaxSizeAllowed>20971520</MaxSizeAllowed>`
  - C. `Content-Type=text/plain` → `HTTP 403`, `Policy Condition failed: ["eq", "$Content-Type", "text/csv"]`
  - D. `key=uploads/other.csv` → `HTTP 403`, `Policy Condition failed: ["eq", "$key", "uploads/edb1b536-….csv"]`
  - Bucket listing after A–D → only the one 158-byte object. Global host check above → `307`.
  - Temporary resources: the bucket (emptied, then `delete-bucket`; `head-bucket` → `404 Not Found`), the container `t15-pg` (removed) and the scratch password and ticket files were deleted.
  - `make check` → `All checks passed!`, `43 files already formatted`, `Success: no issues found in 31 source files`, `70 passed, 15 skipped` (the 15 are DB integration tests, no DB configured in this run), `Required test coverage of 80.0% reached. Total coverage: 99.34%` (`uploads.py` 100%)
  - `make package` → `{"stage": "package_imports_ok", "count": 10, "failures": {}}`
  - Secrets scan on the touched files → only fake test values (`example-secret`, `pw`) and variable names.
- Not verified here: the Lambda running in the VPC against RDS and the Function URL with CORS. Those run for the first time in T22; the browser POST with the UI origin in T40.
- Still open (from T13): `serverless.yml` uses `dbName: loans`, `dbUser: loans_app`, but RDS has database `clickpe`, user `clickpe`. Must be aligned before T22, or `getUploadUrl` fails its first connection.
- Rubric: Cloud Architecture (presigned POST with S3-enforced key, type, size and expiry; regional endpoint), Backend (thin handler over a tested pure function, fail-fast lazy config, structured logs).
- Explain it back:
  - Built: the endpoint that starts an upload. It records a `pending` batch, then returns a short-lived signed form that lets the browser send exactly one CSV, at most 20 MB, straight to S3 under a key tied to that batch.
  - Why this approach over the obvious alternative (a presigned PUT or sending the file through the Lambda): a PUT has no documented size enforcement, and a Function URL or API Gateway body is capped at 6–10 MB. A POST policy makes S3 itself refuse a wrong key, type or size, so the Lambda never sees the bytes. The curl runs show each refusal.
  - Q: Anyone can call a public Function URL. What stops someone from filling the bucket or the batches table? A: Each call yields a policy limited to one key, 20 MB and 5 minutes, and the bucket expires uploads after 7 days. It does not stop someone from creating many `pending` rows; that needs throttling (API Gateway usage plans or WAF), which is listed as the documented production upgrade rather than built.
  - Q: Why does the batch row exist before the file does, and what if the user never uploads? A: `split-csv` runs outside the VPC and cannot write to RDS, so the row has to exist first for `load-chunk` to find. An abandoned upload leaves a harmless `pending` row with no S3 object, since S3 never fires an event.
  - Q: Why return the whole `fields` map instead of fixed fields? A: The set depends on the credentials. Role credentials add `x-amz-security-token`; with a different signer the list differs. The client sends whatever came back, so the policy and the form cannot drift apart.

### T16 — Validation module (2026-10-21)
- Files: `lambdas/shared/validation.py` (new); `tests/unit/test_validation.py`, `tests/integration/test_validation_db.py`, `tests/integration/conftest.py` (new); `tests/fixtures/{good_users,bom_crlf_quoted,malformed_users,duplicate_ids,header_only,header_mismatch,empty}.csv` (new, `.gitkeep` removed); `tests/integration/test_batches_db.py` (its migrated-database fixture moved to `conftest.py`, no behaviour change); `scripts/check_package.py` (`lambdas.shared.validation` added); `docs/decisions.md` (new section 21 "Row validation"; `columns` added to the chunk message)
- Choices (approved by the user before coding):
  1. Columns matched by name in any order (case, spaces and BOM ignored). `check_header` returns a `ColumnLayout`; **T17 must put `layout.columns` in every chunk message** and T18 rebuilds the layout with `check_header(message["columns"])` (tested: the rebuilt layout is identical). Unknown extra columns are ignored and listed in `layout.ignored`.
  2. A repeated `user_id` inside one chunk keeps the first row; later copies are rejected as `user_id: duplicate of line N`. Cross-chunk duplicates are left to the upsert (one row per id, last committed chunk wins); documented in `decisions.md`.
  3. Format is normalised (trim, lowercase email, canonical UUID, `self employed`/`SELF_EMPLOYED` → `Self-Employed`); meaning is never guessed (`25,000`, `₹25000`, `750.0`, `1e5`, `Student` are rejects).
  - Invariant: every accepted row satisfies the `users` CHECKs, because one refused row would abort the COPY of its whole chunk in T18. Extra rules beyond the schema: no control characters (NUL cannot be stored in `text`), ASCII email with a dotted domain ≤ 254 chars, name ≤ 200 chars, income ≤ 10 integer digits + 2 decimals. Numbers use `[0-9]` patterns because `int()` accepts `7_50` and Arabic-Indic digits.
  - `read_records` yields the physical line each record starts on (a quoted newline does not shift later numbers; blank lines are skipped but counted), so `rejected_rows(batch_id, line_no)` matches the file. A record the `csv` module cannot parse (`"Bad"Quote`, unclosed quote) becomes a `malformed CSV: …` reject and reading continues. Raw text kept for the reject report is capped at 1,000 chars.
  - Left for T18: decoding the chunk bytes (invalid UTF-8) and the cap on how many rejects are stored per batch.
- Evidence (throwaway `postgres:16` container `t16-pg` on 127.0.0.1:55432, PostgreSQL 16.15, password generated into a mode-600 scratch file; container and file removed afterwards, `docker ps -a --filter name=t16-pg` → 0):
  - Real sample: `validate_file(data/users.csv)` → `valid 10000 rejects 0 distinct_ids 10000 elapsed_ms 464`; employment `Salaried 3389 · Self-Employed 3371 · Business 3240`; income 25000–150000, score 650–800, age 22–50 (identical to the T01 profile)
  - Fixtures (`validate_file` per file): `good_users` 5 valid; `bom_crlf_quoted` (BOM, CRLF, reordered upper-case header, quoted comma, quoted CRLF, blank line) 2 valid + `3 name: contains a control character`, the row after it correctly numbered 6; `malformed_users` 1 valid + 10 rejects on lines 2–11, one per rule, line 10 lists 4 problems; `duplicate_ids` → `4 user_id: duplicate of line 2` (upper-case copy of the same id); `header_only` 0/0; `header_mismatch` → `HeaderError: missing columns: age; repeated columns: email`; `empty` → `HeaderError: file is empty`
  - DB invariant: `test_accepted_boundary_rows_satisfy_every_check` (4 accepted edge rows in one INSERT, 2 out-of-range rows rejected first), `test_every_sample_row_is_accepted_and_stored` (10,000 rows in one INSERT), and 4 negative controls where the raw value is refused by `users_email_check`, `users_employment_status_check`, `users_credit_score_check`, `users_age_check`
  - Mutation probe: with `email = value.lower()` changed to `email = value`, the boundary test fails with `new row for relation "users" violates check constraint "users_email_check"`. File restored (`cmp` → identical).
  - `TEST_DB_HOST=127.0.0.1 TEST_DB_PORT=55432 … pytest --cov` → `170 passed in 17.34s`, `Total coverage: 100.00%` (21 integration tests incl. the T09/T14 ones on the shared fixture)
  - `make check` (no DB) → `All checks passed!`, `47 files already formatted`, `Success: no issues found in 35 source files`, `149 passed, 21 skipped`, `Required test coverage of 80.0% reached. Total coverage: 99.62%`; `validation.py 177 stmts, 50 branches, 100%`
  - `make package` → `{"stage": "package_imports_ok", "count": 11, "failures": {}}`
  - Secrets scan on the touched files → only variable names (`TEST_DB_PASSWORD`, `password=`). Comment scan on new code → none.
- Rubric: Backend & Code Quality (correct ingestion: pure, typed validation with a per-line reject report; schema-backed invariant tested on PostgreSQL with a mutation probe; 100% coverage), Docs (decision section with rejected alternatives and measured numbers).
- Explain it back:
  - Built: the module that decides, for every CSV line, whether it becomes a user row or a reject with a readable reason, plus the header check that refuses a file without the required columns. It is pure, so split-csv and load-chunk can call it, and every rule is tested without AWS.
  - Why this approach over the obvious alternative (COPY the raw CSV and let the database CHECKs reject bad rows): Postgres COPY is all-or-nothing, so one bad line would fail its whole 5,000-row chunk and the user would see no per-line reasons. Validating first, never more loosely than the schema, keeps good rows loading and gives a reject report with line numbers.
  - Q: How do you know validation can never let through a row that breaks the COPY? A: The DB test inserts every accepted boundary row and all 10,000 sample rows in a single statement under the real CHECKs, and four negative controls show the same values without validation are refused. Removing email lowercasing made that test fail with `users_email_check`.
  - Q: The chunk has no header. How does load-chunk know which column is which? A: split-csv validates the header once and sends `layout.columns` in each chunk message; load-chunk rebuilds the identical layout with `check_header`. A test shows the round trip gives an equal layout.
  - Q: What happens to a duplicated `user_id`? A: Within a chunk the first row is kept and the later one is rejected with the line of the first. Across chunks the upsert keeps one row per id, and the stored version is from the chunk that commits last. That ordering is not guaranteed, which is documented as a limitation; the sample has 10,000 distinct ids.

### T18 — load-chunk Lambda (2026-10-21)
- Files: `lambdas/shared/chunks.py` (new: chunk/control message contract, ranged S3 read with `IfMatch`), `lambdas/shared/loading.py` (new: decoding, staging COPY, upsert, reject storage), `lambdas/load_chunk/handler.py` (stub replaced), `lambdas/shared/db.py` (`server_error`), `tests/chunk_helpers.py`, `tests/unit/test_chunks.py`, `tests/unit/test_loading.py`, `tests/unit/test_load_chunk.py`, `tests/integration/test_load_chunk_db.py` (new), `tests/unit/test_db.py` (2 tests), `scripts/check_package.py` (2 modules), `docs/decisions.md` (Chunking: `etag` + exclusive `end_byte`; Driver: upsert corrected; new section 22 "Chunk loader"). Local only (gitignored): `CLAUDE.md` T17 message spec updated to the T18 contract.
- Built against the documented message format: T17 is not built yet (it is P1), so T18 fixes the contract in code (`ChunkMessage`, `encode_message`, `parse_message`) and T17 must send messages with `encode_message`. Tests build messages with a line-based helper that is correct only for files without quoted newlines (documented in `tests/chunk_helpers.py`).
- Choices:
  - Contract additions: `end_byte` exclusive; `etag` from the S3 event sent as `IfMatch`, so a re-upload to the same key within the 5-minute presign window cannot mix two files.
  - Upsert compares the six data columns only. The planned `users.* IS DISTINCT FROM EXCLUDED.*` includes `batch_id`/`updated_at`, which would rewrite every row on an identical re-upload; `DISTINCT ON (user_id) … ORDER BY user_id, seq` keeps the first occurrence (same as validation).
  - S3 read and validation happen before the transaction; the transaction is claim → COPY → upsert → rejects → `finish_chunk`. `try_complete` runs after the commit and logs `batch_processed`; the n8n POST is T19.
  - Outcomes: ack (loaded / duplicate / batch not loading), ack + batch `failed` (control message, `PreconditionFailed`/`InvalidRange`/short read, `HeaderError`, `BatchStateError`, SQLSTATE class 22/23), retry via `batchItemFailures` (other DB errors, network, S3 throttling, unparseable message).
  - Rejects: all counted; first 100 per chunk stored; NUL and non-UTF-8 bytes replaced with U+FFFD for storage. Invalid UTF-8 rejects only its own record (`surrogateescape` decode).
  - Timeout 120 s / 512 MB kept from T10, reasoning in decisions.md section 22.
- Evidence (throwaway `postgres:16` container `t18-pg`, PostgreSQL 16.15 on 127.0.0.1:55432, password in a mode-600 scratch file; container and file removed afterwards, `docker ps -a --filter name=t18-pg` → 0):
  - Handler run on `data/users.csv` (2 chunks of 5,000, in-memory S3) →
    - first upload: `"chunk_loaded", "duration_ms": 286, "chunk_id": 0, "count": 5000, "rejected": 0, "inserted": 5000, "updated": 0, "unchanged": 0` and the same for chunk 1 (283 ms), then `"batch_processed"`; `{"batchItemFailures": []}`
    - redelivery of chunk 1 after completion → `"chunk_skipped", "reason": "not loading"`
    - identical re-upload (new batch): both chunks `"inserted": 0, "updated": 0, "unchanged": 5000` (146 / 144 ms), `"batch_processed"`
    - `upload_batches` → `[true, "processed", 2, 2, 10000, 0]`, `[false, "processed", 2, 2, 10000, 0]` (rows_ok + rows_rejected = 10,000 = CSV rows)
    - `SELECT count(*), count(DISTINCT user_id), count(*) FILTER (WHERE batch_id = <first>) FROM users` → `[10000, 10000, 10000]` (re-run → zero new rows, ownership unchanged)
    - `chunk_loads` → 4 rows, `(0, 5000, 0)` and `(1, 5000, 0)` per batch
  - `pytest tests/integration/test_load_chunk_db.py` → `8 passed`: full sample + identical re-upload; redelivery no-op (3 ledger rows, 4 S3 reads for 5 deliveries); `malformed_users.csv` rejects stored on lines 2–11 and `rows_ok + rows_rejected` = data lines; invalid UTF-8 and NUL lines rejected and stored as `R�na` / `N�ul`; changed row moves to the new batch (1 of 5); control message → `failed` with `split failed: missing columns: age`; replaced object → `failed` with `chunk 0: S3 refused chunk 0: PreconditionFailed`, later chunks skipped (1 S3 read); a row the DB refuses → `23514`, batch `failed`, ledger and users rolled back to 0.
  - First run of the redelivery test failed on a wrong expectation in the test (a delivery after completion is skipped at `start_loading`, not logged as a duplicate); the test was corrected, the code was not changed.
  - Mutation probe: with the `IS DISTINCT FROM` guard removed from `UPSERT_USERS`, the full-sample test fails with `assert 0 == 10000` (the identical re-upload moved every user to the new batch). File restored (`cmp` → identical).
  - Real S3 (temporary bucket `clickpe-t18-tmp-376834080732`, ap-southeast-2, public access blocked; sample uploaded with `put_object`, read with `new_s3_reader` + `read_chunk`): `bytes=70-496572` → 496,503 bytes and `bytes=496573-993190` → 496,618 bytes, both equal to the local slices and ending in `\n`; header + chunks reassemble the 993,191-byte file exactly; quoted ETag accepted; wrong ETag → `S3 refused chunk 0: PreconditionFailed`; start past the end → `InvalidRange`; range 50 bytes too long → `chunk 1 is 496618 bytes, message says 496668`; missing key → `NoSuchKey` (admin user has `ListBucket`; the Lambda role will see `AccessDenied` instead, which is retried; see decisions.md section 22). Bucket emptied and deleted; `head-bucket` → `404 Not Found`.
  - `TEST_DB_HOST=127.0.0.1 TEST_DB_PORT=55432 … pytest --cov` → `233 passed in 24.83s`, `Total coverage: 100.00%` (`chunks.py` 102 stmts, `loading.py` 63 stmts, both 100%)
- Quality gates (`make check`, no DB): `All checks passed!`, `54 files already formatted`, `Success: no issues found in 42 source files`, `204 passed, 29 skipped`, `Required test coverage of 80.0% reached. Total coverage: 99.73%`
- `make package` → `✔ Service packaged`, `{"stage": "package_imports_ok", "count": 13, "failures": {}}`
- Secrets scan on the touched files → only variable names and fake test values (`example-secret`, `pw`). Comment scan on new code → none (only `noqa: N803` directives for boto3's parameter names).
- Not verified here: the Lambda inside the VPC reading through the Gateway Endpoint and connecting to RDS over TLS, and the SQS event source mapping. Both run for the first time in T22. Still open from T13: `serverless.yml` `dbName: loans` / `dbUser: loans_app` vs RDS `clickpe` / `clickpe`.
- Rubric: Backend & Code Quality (COPY bulk load, idempotent dedup upsert with measured 0-row re-upload and a mutation probe, per-line reject report, typed message contract, 100% shared coverage), Cloud (S3 → SQS → Lambda loader with per-message retry vs fail classification, ranged reads with `IfMatch` checked on real S3).
- Explain it back:
  - Built: the Lambda that turns one SQS chunk message into rows in `users`. It reads exactly its byte range from S3, validates every record, bulk-loads the good ones with COPY through a staging table into an upsert, stores the bad ones with line numbers, records the chunk in the ledger in the same transaction, and after the commit checks whether it finished the batch.
  - Why this approach over the obvious alternative (`INSERT … ON CONFLICT` row by row, or COPY straight into `users`): row-by-row inserts are the slow path the decisions doc rejects, and COPY straight into `users` fails on the first `user_id` that already exists. Staging + one set-based upsert gets COPY's speed and an update path. Comparing only data columns turns an identical re-upload into 0 changed rows, so Workflow B finds nothing new to match or email.
  - Q: The same chunk message arrives twice. What stops double counting? A: The first statement in the chunk's transaction inserts `(batch_id, chunk_no)` into `chunk_loads` with `ON CONFLICT DO NOTHING`. The second delivery gets no row back and commits nothing. A concurrent duplicate waits on that key until the first commits. Tested: 5 deliveries of 3 chunks → 3 ledger rows, `rows_ok` 5.
  - Q: Someone uploads a second file to the same key while the first is still loading. What happens? A: Every ranged read sends the ETag from the S3 event as `IfMatch`. S3 answers `PreconditionFailed` for the replaced object, the batch is marked failed with that reason, and the remaining chunks are skipped. Measured on real S3 and tested.
  - Q: Which errors fail the batch and which are retried? A: Problems that can never succeed on retry fail the batch at once: a split error, a replaced or short object, missing columns, or data the database refuses (SQLSTATE classes 22 and 23). Network, connection, deadlock and throttling errors go back to SQS in `batchItemFailures` for that message only, and after 5 receives the message moves to the DLQ.

### T20 — batch-status Lambda (2026-10-21)
- Files: `lambdas/shared/status.py` (new: four read-only queries and the response document), `lambdas/batch_status/handler.py` (stub replaced), `scripts/check_package.py` (+`lambdas.shared.status`), `tests/unit/test_batch_status.py`, `tests/integration/test_batch_status_db.py` (new).
- Choices:
  - Response: `batch_id, status, error, total_chunks, chunks_done, rows_ok, rows_rejected, first_rejects[{line_no, reason}] (5), matches, notified, funnel, created_at, updated_at`.
  - `funnel` is the latest `pipeline_runs` row for the batch (`ORDER BY id DESC LIMIT 1`), or `null` before Workflow B starts. Counters not yet measured stay `null` rather than becoming 0, so the UI can tell "not measured" from a measured zero.
  - Errors: non-GET 405, missing or non-UUID `batch_id` 400 (no query sent), unknown batch 404, database error 503 with the connection dropped. `cache-control: no-store` because the UI polls.
  - Read-only, autocommit, indexed lookups only (`upload_batches` pk, `rejected_rows` pk, `matches_batch_id_idx`, `pipeline_runs_batch_id_idx`). `serverless.yml` needed no change: the function, role, VPC, GET-only CORS and Function URL permission were already in place from T10.
- Evidence (throwaway `postgres:16` container `t20-pg` on 127.0.0.1:55433, password in a mode-600 scratch file; container and file removed afterwards, `docker ps -a --filter name=t20-pg -q | wc -l` → 0):
  - `pytest tests/unit/test_batch_status.py tests/integration/test_batch_status_db.py` → 20 passed (15 unit incl. parametrized cases, 5 integration).
  - Integration cases: a loaded batch (3 ok / 8 rejected) returns only the first 5 rejects in line order and `funnel: null`; 3 matches with 1 notified count `3 / 1`; two `pipeline_runs` rows → the later one (`total_pairs 300`, `stage2_clear null`, `stage_ms {"stage1": 42}`) is returned; another batch's runs and rejects do not leak; a failed batch exposes its `error`; unknown id → `None`; the handler over a real connection returns 200 with `processed`, 3, 8.
  - Full suite with the DB: `253 passed in 29.77s`, `status.py 29 stmts, 100%`, `Total coverage: 100.00%`.
- Quality gates (`make check`, no DB): `All checks passed!`, `57 files already formatted`, `Success: no issues found in 45 source files`, `219 passed, 34 skipped`, `Required test coverage of 80.0% reached. Total coverage: 99.74%`.
- `make package` → `✔ Service packaged`, `{"stage": "package_imports_ok", "count": 14, "failures": {}}`.
- Secrets scan on touched files → only variable names (`DB_PASSWORD`) and fake test values (`pw`). No comments in new code.
- Not verified here: the deployed Function URL, CORS from the browser, and the Lambda reaching RDS from inside the VPC. These run for the first time in T22; the "correct JSON for a real batch" check on the deployed stack is repeated in the T22 smoke test.
- Rubric: Backend & Code Quality (typed, read-only status module with 100% coverage and DB-backed tests), Cloud (Function URL poller inside the VPC), Docs (the funnel in the response feeds the UI in T40).
- Explain it back:
  - Built: a GET endpoint the browser polls with a `batch_id`. It returns where the batch is in its lifecycle, chunk and row counters, the first 5 reject reasons, how many matches and notified emails exist, and the latest matching funnel.
  - Why this approach over the obvious alternative (one big JOIN across batches, rejects, matches and runs): a join multiplies rows (rejects × matches × runs) and would need de-duplicating. Four small indexed queries are simpler to read and test, and the cost is trivial at one poll every few seconds.
  - Q: Why return `null` for funnel counters instead of 0? A: The schema leaves a counter NULL until its stage has run, so 0 means a measured zero. Passing NULL through lets the UI show "pending" for stages that have not run instead of claiming nothing matched.
  - Q: Anyone with the URL can call it. Is that a problem? A: It is read-only and the id is a random UUID, so batches cannot be enumerated, and it returns counts and line-level reject reasons, not user data. It is documented as a public Function URL with those mitigations; API Gateway auth is the production upgrade.
  - Q: What if the database connection died while the Lambda was frozen? A: `Database.connection()` checks the connection with `SELECT 1` and reconnects; if a query still fails, the handler resets the cached connection and returns 503, so the next poll starts clean.

### T17 — split-csv Lambda (2026-10-21)
- Why now: T22 was next by priority, but its smoke test (upload → `processed`) cannot pass while `splitCsv` is the T10 stub, so the user chose to build T17 first. T22 now depends on T17 in practice.
- Files: `lambdas/shared/splitting.py` (new: event parsing, canonical-key check, size check, `IfMatch` fetch, chunk planning), `lambdas/split_csv/handler.py` (stub replaced), `lambdas/shared/chunks.py` (+`send_messages`, `MessageSender`, `SendError`, `new_sqs_client`), `scripts/check_package.py` (+`lambdas.shared.splitting`), `tests/unit/test_splitting.py`, `tests/unit/test_split_csv.py`, `tests/integration/test_split_to_load_db.py` (new), `pyproject.toml` + `uv.lock` (dev dependency `moto[s3,sqs]` 5.2.4), `docs/decisions.md` → "Chunking: exact record byte offsets".
- Choices (⚖️, approved with "go"):
  - Record boundaries come from `csv.reader` (strict) over the universal-newline lines, the parser load-chunk already uses. The bytes of the lines each record consumed are summed, so cuts and line numbers agree with load-chunk by construction. Rejected: a toggle-on-every-quote scanner (mis-cuts `ab"c,"…⏎…"`, test included).
  - Whole-object read (20 MB cap, checked from the event before reading and from the bytes after) instead of streaming. This deviates from the task text "stream file" and was approved by the user in the plan. Streaming is documented as the upgrade path.
  - One `{batch_id, error}` control message for an empty file, an oversize file, no header, a bad header, a file with no data rows, or a deleted object. A non-canonical key is only logged. A replaced object (`PreconditionFailed`) is skipped. S3/SQS errors raise → async retry ×2 → `split-failures`.
  - `SendMessageBatch` in tens, failed entries resent once, then `SendError`.
- Evidence:
  - Local plan of the real sample (`plan_chunks` on `data/users.csv`, 5,000 rows per chunk) → 2 chunks `(first_line 2, 5000 rows, bytes 70–496573)` and `(5002, 5000, 496573–993191)`, the same byte ranges T18 measured on real S3.
  - `pytest tests/unit/test_splitting.py` → 33 passed: 7 fixture/size combinations + a seeded random file (399 rows, quoted CRLFs, doubled quotes, blank lines) at chunk sizes 1/7/50/1000 all reassemble byte for byte, with per-chunk valid rows and `(line_no, reason)` rejects equal to one-chunk validation; quoted newline + CRLF + BOM keep first lines `[2, 3, 6]`; blank lines ride with the previous chunk; multi-line header shifts first lines to `[4, 5]`; literal quote not a cut point; unterminated quote → one malformed record; invalid UTF-8 rejects only line 3; 7 unusable-file cases; 6 key cases (upper-case and braced UUIDs refused).
  - `pytest tests/unit/test_split_csv.py` → 14 passed, against moto S3 + SQS: the `malformed_users.csv` upload → 4 messages, each read back with load-chunk's `read_chunk` (ranged GET + `IfMatch`) and validated, equal to whole-file validation; 40 rows at 3 per chunk → 14 messages over 2 SendMessageBatch calls; bad header and header-only → one control message each; oversize event → control message without reading S3; object bigger than the cap after reading → refused; deleted object → `upload is no longer in S3`; replaced object → 0 messages; foreign key → 0; duplicate event → identical chunks; S3 `SlowDown` propagates; a refused SQS entry is resent once (`[[0..9], [0], [10, 11]]`); refused twice → `SendError`; runtime pins `https://s3.ap-southeast-2.amazonaws.com`.
  - `pytest tests/integration/test_split_to_load_db.py` (throwaway `postgres:16` container `t17-pg`, PostgreSQL 16.15, on 127.0.0.1:55432, password in a mode-600 scratch file; container stopped with `--rm` and the file deleted, `docker ps -a --filter name=t17-pg` → empty) → 4 passed. These tests run the real split handler → moto SQS → the real load-chunk handler reading moto S3 → Postgres: the full sample → 2 messages, batch `["processed", 2, 2, 10000, 0, None]`, 10,000 users; `bom_crlf_quoted.csv` at 1 row per chunk → 3 chunks, `processed` 2 ok / 1 reject stored at line 3 (`name: contains a control character`); `malformed_users.csv` delivered shuffled with every second message duplicated → `processed`, 4 ledger rows, rejects on consecutive lines from 2; bad header → `failed`, `split failed: missing columns: age; repeated columns: email`.
  - First runs exposed two wrong test expectations: the literal-quote input opened a real quoted field, and the whole-file reference skipped load-chunk's UTF-8 reject step. Both tests were corrected; the code did not change. A third: `bom_crlf_quoted.csv`'s multi-line name is rejected by the T16 control-character rule, so the expectation was fixed to 2 ok / 1 reject.
  - Full suite with the DB: `304 passed in 34.06s`, `lambdas/shared` coverage `100.00%` (`splitting.py` 132 stmts, `chunks.py` 127 stmts, both 100%).
  - Size measurement (laptop, Ryzen 5 7530U): the sample repeated 21× = 20,855,611 bytes / 210,000 rows → 42 chunks in 1.36 / 1.34 / 1.28 s; peak Python allocation 104.3 MB, max RSS 145.9 MB (run under `tracemalloc`). The deployed Lambda duration is not measured yet (T22).
- Quality gates (`make check`, no DB): `All checks passed!`, `61 files already formatted`, `Success: no issues found in 49 source files`, `266 passed, 38 skipped`, `Required test coverage of 80.0% reached. Total coverage: 99.79%`.
- `make package` → `✔ Service packaged`, `{"stage": "package_imports_ok", "count": 15, "failures": {}}`.
- Secrets scan on touched files → only variable names (`AWS_SECRET_ACCESS_KEY` set to `testing` for moto). Comment scan → only `noqa: N803` directives for boto3 parameter names.
- Not verified here: the real S3 → Lambda trigger, SQS sends from the deployed function, and the deployed duration. These are first exercised by the T22 smoke test.
- Rubric: Cloud (S3 → split-csv → SQS fan-out now implemented, file-level failures routed to the batch, async failures to `split-failures`), Backend (quote-correct chunking proven by reassembly and validation-equivalence properties, moto + Postgres end-to-end tests, 100% shared coverage).
- Explain it back:
  - Built: the Lambda that S3 calls when a CSV lands. It checks the size, reads the object (pinned to the event's ETag), finds where every CSV record starts and ends in bytes, groups records into 5,000-row chunks and queues one message per chunk. A file that can never load becomes a single error message instead.
  - Why this approach over the obvious alternative (a hand-written byte scanner that tracks quotes): the loader already parses chunks with Python's csv module. Having the splitter find boundaries with the same parser on the same lines means the two cannot disagree about where a record ends or which line it is on. A separate scanner is a second CSV parser that has to match the first in every edge case, and the common quote-toggle version does not.
  - Q: How do you know no record is ever cut in half? A: Cuts are only placed where `csv.reader` has just returned a record, and load-chunk restarts the same reader at that point. The tests check it as a property: on every fixture and a random file with quoted newlines, the chunks reassemble the file byte for byte, and validating chunk by chunk gives the same rows and the same rejected line numbers as validating the file as one chunk.
  - Q: The user uploads a file with only a header. What happens? A: Zero chunks would leave the batch `pending` forever, because load-chunk only learns `total_chunks` from a chunk message. So split-csv sends one control message, `file has no data rows`, and load-chunk marks the batch `failed` with that reason.
  - Q: S3 delivers the same event twice. Do users get loaded twice? A: No. Planning is deterministic, so the second split sends identical `(batch_id, chunk_no)` messages. The `chunk_loads` ledger rejects the duplicates inside each chunk's transaction, and the upsert is idempotent anyway. A test checks that a duplicate event produces identical chunks, and the DB test delivers duplicates and gets exactly 4 ledger rows.

### T22 — Deploy + smoke test (2026-10-21)
- Why before T19: T19 depends on T22, and T22's dependencies (T15, T17, T18, T20) were DONE.
- Files: `scripts/smoke_test.sh` (new), `serverless.yml` (`dbName`/`dbUser` → `clickpe`, closing the open finding from T13), `docs/decisions.md` → "First deployment (T22)".
- Built: `sls deploy` of stack `clickpe-loan-engine-dev` to `ap-southeast-2`, then RDS ingress 5432 from the stack's Lambda SG (`sg-0ad4c9a31f3b8f7cc`) by SG reference, no CIDR. The smoke script finds the Function URLs with `aws lambda get-function-url-config`, calls `getUploadUrl`, posts the CSV with `--form-string` fields to S3, polls `batchStatus` every 3 s, and fails unless the batch reaches `processed` and `rows_ok + rows_rejected` equals the CSV data lines (`failed`, a bad S3 status or a 180 s timeout also fail).
- Evidence:
  - `npx serverless deploy` → `✔ Service deployed to stack clickpe-loan-engine-dev (280s)`; endpoints `getUploadUrl` and `batchStatus` on `*.lambda-url.ap-southeast-2.on.aws`; 4 functions, 952 kB each.
  - `aws ec2 authorize-security-group-ingress` → rule `sgr-079badaa4b84f2eae`; `describe-security-groups` on `sg-0f0ca5e2b7cb5e1c3` → 5432 from two SGs (n8n SG and Lambda SG), `IpRanges []`.
  - `scripts/smoke_test.sh` (default fixture) → `uploaded tests/fixtures/good_users.csv: HTTP 204`, `status=pending` then `status=processed chunks=1/1`, `rows_ok 5`, `PASS`.
  - `scripts/smoke_test.sh data/users.csv` → `HTTP 204`, `status=loading chunks=0/2`, `status=processed chunks=2/2`, `rows_ok 10000, rows_rejected 0`, `PASS`.
  - Same file again → `PASS`; CloudWatch `chunk_loaded` for the new batch: `"inserted": 0, "updated": 0, "unchanged": 5000` for both chunks (146 ms, 177 ms).
  - `scripts/smoke_test.sh tests/fixtures/malformed_users.csv` → `rows_ok 1, rows_rejected 10`, first rejects with line numbers (`2: age: missing`, `3: user_id: 'not-a-uuid' is not a UUID`, `4: email: ...`), `PASS` with 11 rows accounted for.
  - CloudWatch REPORT lines: `loadChunk` 189 ms, 112 MB of 512 MB, init 306 ms (cold); `splitCsv` 108 ms, 110 MB of 512 MB; `getUploadUrl` 5.6 ms, 103 MB of 256 MB; `batchStatus` 15.8 ms, 66 MB of 256 MB. Structured logs: `upload_split` 217 ms for the 993,191 B sample (2 chunks); `chunk_loaded` 288 ms and 250 ms for 5,000 rows each.
  - `ingest`, `ingest-dlq`, `split-failures` → `ApproximateNumberOfMessages` 0 and `NotVisible` 0 after all uploads.
  - `make check` → `All checks passed!`, `61 files already formatted`, `Success: no issues found in 49 source files`, `266 passed, 38 skipped`, `Required test coverage of 80.0% reached. Total coverage: 99.79%`. `make package` → `✔ Service packaged`, `package_imports_ok`, `count: 15`.
  - Secrets scan on touched files → only `${ssm:/…}` references and variable names. No comments in the new script (a shebang is not a comment).
- Side effects to know about: RDS now holds the 10,000 sample users (labeled by `batch_id`; the real CSV was going to be loaded in T42 anyway, and re-loading is a no-op) and 5 fixture users with ids `00000000-0000-4000-8000-00000000000x` and `@example.invalid` emails. Four batches were created in total (fixture, sample, identical re-upload, malformed), the last one with 10 stored rejects. No test data was deleted (no destructive commands).
- Not verified: the browser/CORS path (T40); the webhook POST to n8n (T19, `webhook_url` is still the SSM placeholder); the DLQ route with a poisoned chunk (T21); the Lambdas under 100k-row load (T37).
- Shortcut recorded: the Lambdas connect as RDS master user `clickpe`; a least-privilege role is tracked for T45.
- Rubric: Cloud (deployed S3 → split → SQS → VPC loader → private RDS verified end to end, measured durations), Backend (smoke script, idempotent re-upload measured on the real deployment).
- Explain it back:
  - Built: the first live deployment of the ingestion path, and a script that proves it works from the outside: it uses only the public Function URLs and the presigned form, the same way the browser will.
  - Why this approach over the obvious alternative (invoke the Lambdas directly with `aws lambda invoke`): direct invokes skip the Function URL permissions, the presigned policy, the S3 event and the SQS event source mapping, which are exactly what can be misconfigured. The smoke test crosses all of them.
  - Q: Why open the RDS security group after the deploy, in a separate command? A: The Lambda security group is created by the stack, and the RDS group was created before it in T11, so neither can reference the other at creation time. The rule references the Lambda SG by ID, not a CIDR, so only these functions can reach 5432. Folding the rule into the stack is possible but would make the stack edit a group it does not own.
  - Q: The Lambdas use the RDS master user. Is that acceptable? A: It is a documented shortcut, not a hidden one. The connection is private, TLS-verified and limited to the Lambda SG, but a compromised function could alter any table. The fix is a role with only the privileges the loader needs; it is listed for T45.
  - Q: How do you know exactly-once completion held on the real system? A: Each batch shows `chunks_done` equal to `total_chunks` and `processed`, queues drained with an empty DLQ, and the re-upload logged `unchanged` for every row. The concurrent-finisher guarantee itself was tested against PostgreSQL in T14 (25 × 2 trials); the real deployment ran at most 2 chunks at once, so it does not stress it further. T37 does.

### T23 — docker-compose (2026-10-21)
- Files: `n8n/docker-compose.yml`, `n8n/.env.example`, `infra/n8n.md`. On EC2 only: `/opt/clickpe/n8n/.env` (mode 600, generated encryption key, never displayed).
- Built: n8n `2.44.4` pinned, `n8n_data` volume, `WEBHOOK_URL` on the private IP, Asia/Kolkata, pruning, public API/diagnostics off, `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`, system AWS credentials enabled, restart policy, healthcheck. SG `clickpe-n8n-sg` gained 5678 from the Lambda SG only (`sgr-05583458c0968e07c`).
- Evidence (full output in `infra/n8n.md`):
  - `docker compose ps` → `Up 2 minutes (healthy)`; `/healthz` → 200; `.env` → `600 root`.
  - `aws ssm start-session` port forward → `http://localhost:15678/` 200, `{"status":"ok"}`.
  - Laptop → `3.26.22.50:5678` → timeout (curl exit 28).
  - Probe workflow: allowlist `172.31.0.0/16` → 200; allowlist `10.255.0.0/16` → 403; after unpublish → 404.
  - SG `IpPermissions` → one rule: 5678 from `sg-0ad4c9a31f3b8f7cc`, 0 CIDR ranges.
  - Secrets scan on the two repo files → no matches. No Python touched, so ruff/mypy/pytest were not re-run.
- Temporary resource: probe workflow `t23probe0001` left unpublished in n8n; delete it in the editor.
- Not verified: owner account + 2FA (browser step for the user, before T24); the allowlist is checked from the instance's own private IP, not yet from a Lambda (T19).
- Decision: `$env` access blocked (container env holds the encryption key), so non-secret config goes in an `app_config` table.
- Rubric: Cloud (n8n with no inbound internet ports, SG-referenced webhook access, IP allowlist proven), n8n (platform ready for A/B/C/E).
- Explain it back:
  - Built: a pinned, health-checked n8n container on the EC2 box, reachable by Lambda on the private IP and by humans only through an SSM tunnel.
  - Why this over the obvious alternative (expose 5678 with a CIDR rule or tunnel): SSM needs no open port and no extra service, and the SG stays at zero internet rules.
  - Q: Why block `$env` in nodes? A: The container env holds `N8N_ENCRYPTION_KEY`; any Code node could read it. Config that is not secret lives in a DB table.
  - Q: How do you know the IP allowlist works? A: Two Webhook nodes differing only in the allowlist returned 200 and 403 to the same caller.
  - Q: Why a plain-HTTP editor? A: It is only reachable through the encrypted SSM tunnel to localhost, so `N8N_SECURE_COOKIE=false` is needed and the exposure is nil.

### T19 — Completion → n8n trigger (2026-10-21)
- Files: `lambdas/shared/notify.py` (new), `lambdas/load_chunk/handler.py` (`send` in `Runtime`, `complete_batch`), `scripts/retrigger_batch.sh` (new), `scripts/check_package.py` (+`lambdas.shared.notify`), `tests/webhook_helpers.py`, `tests/unit/test_notify.py`, `tests/integration/test_completion_trigger_db.py` (new), `tests/unit/test_load_chunk.py`, `tests/integration/test_load_chunk_db.py`, `tests/integration/test_split_to_load_db.py` (sender injected, one-POST assertions), `docs/decisions.md` (new section 24 "Completion trigger"), `infra/n8n.md` (webhook + retrigger section). AWS: SSM `/clickpe/n8n/webhook_url` → `http://172.31.26.164:5678/webhook/match-batch` (version 2), stack redeployed.
- Choices:
  - Only the caller whose post-commit `try_complete` returns a row calls `notify_batch_processed`; the others log `completion_checked` with `won: false`. The duplicate-delivery path also runs the check, as before.
  - Stdlib `urllib`, 5 s per attempt, 3 attempts (0.5 s, 1 s back-off). Retry on connection errors, timeouts, 429, 5xx; no retry on other statuses (401/403/404 cannot change within seconds). Never raises; returns `NotifyResult(delivered, attempts, status, error)`.
  - A failed POST is logged at ERROR (`webhook_failed`) and the message acknowledged; the batch stays `processed`. Sending it back to SQS cannot help, because a redelivery skips a batch that is no longer `loading`. Recovery: `scripts/retrigger_batch.sh <batch_id>` (refuses unless `batchStatus` says `processed`; re-POSTs from the n8n instance via SSM Run Command with the secret read on the instance and piped to `curl -H @-`).
  - Rejected: a transactional outbox + sweeper (production upgrade; closes the crash-between-commit-and-POST gap automatically). Documented as a known gap with the retrigger as the fix.
  - The `Runtime` gained a `send` field so tests replace the network; the real Lambda uses `send_request`.
- Evidence (local; throwaway `postgres:16` container `t19-pg`, PostgreSQL 16.15 on 127.0.0.1:55432, password in a mode-600 scratch file; container and file removed, `docker ps -a --filter name=t19-pg -q | wc -l` → 0):
  - `tests/unit/test_notify.py` (real local HTTP server): 2xx delivered once with `X-Webhook-Secret`, JSON body and path; 503, 502 → 200 on attempt 3 with sleeps `[0.5, 1.0]`; 500/429/503 → gives up after 3 with status 503; 401/403/404 → 1 attempt; closed port → 3 attempts, `Connection refused`; 1 s server delay with a 0.2 s timeout → retried, `timed out` when every attempt is slow; the secret is not in the result or the request repr.
  - `test_concurrent_and_duplicate_finishers_post_to_n8n_exactly_once_per_batch`: 10 batches × 5 chunks, each chunk delivered twice, 10 worker threads (one connection each) released together → stage counts `100 chunk_loaded`, `90 completion_checked`, `10 batch_processed`, `10 webhook_sent`; the receiver got exactly one POST per batch, all with the configured secret.
  - Mutation probe: `try_complete` guard changed to `status IN ('loading', 'processed')` → the test fails with `{'7e02ab6b-…': 4} != {'7e02ab6b-…': 1}` (2–4 POSTs per batch). File restored (`cmp` → identical).
  - Full suite with the DB → `317 passed in 38.78s`, `lambdas/shared` coverage 100% (`notify.py` 48 stmts, 8 branches, 100%).
- Evidence (live, `clickpe-loan-engine-dev`):
  - `aws ssm put-parameter --name /clickpe/n8n/webhook_url … --overwrite` → version 2; `npx serverless deploy` → `✔ Service deployed to stack clickpe-loan-engine-dev (75s)`.
  - Temporary receiver `t19stubrecv1` imported with `n8n import:workflow` and published: Webhook `match-batch` (allowlist `172.31.0.0/16`) → Crypto SHA-256 of `X-Webhook-Secret` → Respond 200 if it equals the hash of the SSM secret (computed on the instance, never displayed), else 401. Probe from the instance: right secret `200 {"secret_ok":true}`, wrong secret `401`, no header `401`, via `127.0.0.1` `403`.
  - `scripts/smoke_test.sh` → 4 × `PASS`: `good_users.csv` (batch `6a9a0fa8…`, 1 chunk) and a 30,000-row file (the sample's data rows ×3, 2,979,433 B, 6 chunks) three times (`6f393e38…`, `8d8e48bb…`, `f83dfb64…`), each `processed` with every row accounted for.
  - CloudWatch `loadChunk` (`filter-log-events`, JSON filter on `stage`): per batch exactly 1 `batch_processed` and 1 `webhook_sent` with `status 200, attempts 1`; each 6-chunk batch has 6 `chunk_loaded` and 5 `completion_checked won=false`; winning chunks 5, 0 and 1.
  - n8n event log (`n8n.workflow.started`, unique `executionId` for `t19stubrecv1`): executions 6, 7, 8, 9 at 04:14:04, 04:14:29, 04:15:08, 04:15:33 IST, one per batch (2–5 were the probes above).
  - Drill: `docker compose stop n8n` → upload `good_users.csv` (batch `9e0704a8…`) → `PASS` (`processed`); log `{"stage":"webhook_failed","level":"ERROR","attempts":3,"status":null,"error":"URLError: <urlopen error [Errno 111] Connection refused>"}`; `ingest` 0 visible / 0 in flight; `batchStatus` → `processed`, 1/1, 5 rows. `docker compose start n8n` → `scripts/retrigger_batch.sh 9e0704a8-a586-47f3-92fd-fe394633623c` → `webhook HTTP 200`, `PASS`; n8n execution 10 at 04:17:51.
  - Refusal: `scripts/retrigger_batch.sh 00000000-0000-4000-8000-0000000000ff` → `FAIL: batch … is 'unknown'; only a processed batch is handed to n8n`, exit 1; `not-a-uuid` → usage error, exit 1.
  - Cleanup: stub unpublished, n8n restarted → `n8n Up 32 seconds (healthy)`, `match-batch` → 404. Local scratch files (30k CSV, stub JSON, command files) deleted.
- Quality gates (`make check`, no DB): `All checks passed!`, `66 files already formatted`, `Success: no issues found in 53 source files`, `278 passed, 39 skipped`, `Required test coverage of 80.0% reached. Total coverage: 99.80%`. `make package` → `✔ Service packaged`, `{"stage": "package_imports_ok", "count": 16, "failures": {}}`.
- Secrets scan on touched files → only prose, variable names and fake test values (`example-secret`, `never-logged-secret`). Repo-wide `AKIA…` / `gsk_…` pattern scan → no hits. Comment scan on new code → none.
- Side effects: RDS gained 5 batches (all `processed`; the 30k-row uploads changed 0 users because every row already existed). They stay `processed` until Workflow B exists. n8n holds `t19stubrecv1` (inactive) next to `t23probe0001`; both to be deleted in the editor once the owner account exists.
- Open items: (1) T32 must publish Workflow B on path `match-batch` and start with the conditional `processed → matching` UPDATE. (2) n8n saves the Webhook node's output including headers, so `X-Webhook-Secret` is stored in execution data on the n8n volume (pruned after 168 h; the stub's executions 2–10 contain it). T32/T45 decide how Workflow B avoids keeping it. (3) The crash window between `try_complete` and the POST is covered only by the manual retrigger.
- Not verified: Workflow B's own behaviour (T32); the n8n Header Auth credential (T24); a crash between commit and POST (not simulated).
- Rubric: Cloud (secure Lambda → n8n integration inside the VPC: SG + allowlist + secret header proven with 200/401/403, exactly-once trigger shown live and in a race test, failure drill + retrigger), Backend (typed notify module with a real-HTTP test suite and a mutation probe, 100% shared coverage).
- Explain it back:
  - Built: the link from ingestion to matching. When the last chunk of a batch commits, exactly one load-chunk invocation tells n8n "batch X is ready", over the private network with a shared secret, with a few quick retries. If n8n is down, the batch waits in `processed` and one script re-sends it.
  - Why this approach over the obvious alternative (POST from every chunk that sees `chunks_done == total_chunks`, or let SQS retry the message until n8n answers): the first double-triggers when two chunks finish together, which the mutation probe shows (2–4 POSTs per batch). The second cannot work: once the batch is `processed`, a redelivered message is skipped, so it never re-sends. The completion winner is the only safe sender, and a failed send needs an explicit re-send.
  - Q: Six chunks finish within milliseconds of each other. How many POSTs reach n8n? A: One. Each chunk runs the conditional `loading → processed` UPDATE after its own commit; Postgres lets only one of them change the row, and only that caller posts. Live: three 6-chunk batches each logged 5 lost checks and 1 `webhook_sent`, and n8n recorded one execution per batch.
  - Q: n8n is restarting when the last chunk lands. What happens to the batch? A: The Lambda tries three times over about 1.5 s, logs `webhook_failed` at ERROR and acknowledges the message, so nothing lands in the DLQ. The batch stays `processed`. `scripts/retrigger_batch.sh <batch_id>` re-sends it once n8n is back. Shown live with n8n stopped: 3 refused attempts, then HTTP 200 from the retrigger.
  - Q: Could the retry or the retrigger make n8n match the same batch twice? A: Both can deliver a second POST, by design. That is why Workflow B's first step is the conditional `processed → matching` UPDATE: the second execution gets no row back and stops. The trigger is at-least-once and the consumer is idempotent; that is built in T32.

### T24 — n8n credentials (2026-10-21)
- Files: `n8n/docker-compose.yml` (`NODE_EXTRA_CA_CERTS` + read-only CA mount), `infra/iam/{n8n-ses-trust,n8n-ses-send,n8n-ec2-assume-ses}.json` (new), `infra/n8n.md` (credentials section), `docs/screenshots/t24-{rds-postgres-test-ok,aws-ses-assume-role-test-ok,webhook-secret-credential,groq-api-credential}.png`. AWS: role `clickpe-n8n-ses-role`, inline policy `assume-n8n-ses-role` on `clickpe-n8n-ec2-role`. n8n container recreated.
- Evidence:
  - `aws sts assume-role` from the instance (SSM Run Command) → `assumed-role/clickpe-n8n-ses-role/t24check`, status `Success`.
  - `rds-postgres` first test → `self-signed certificate in certificate chain`; after mounting the CA (`/opt/clickpe/global-bundle.pem` sha256 prefix `90a6f1a7978a1b1b` = repo copy; `docker exec n8n ls -l /certs/rds-global-bundle.pem` → 174,560 B; container `Up 45 seconds (healthy)`) the error moved to `password authentication failed for user "postgres"` (wrong default user), then `Connection tested successfully` with user `clickpe`.
  - `aws-ses-assume-role` → `Connection tested successfully` (screenshot).
  - `webhook-secret` and `groq-api` saved with masked values (screenshots).
- Not verified: owner-account 2FA (done by the user in the browser; no evidence captured); an actual SES send through the assumed role (T39); `groq-api` against Groq from n8n (T26); `webhook-secret` against Workflow B (T32). No Python touched, so ruff/mypy/pytest were not re-run. Secrets values were copied to the clipboard by command and never printed.
- Side effects / open: probe workflows `t23probe0001` and `t19stubrecv1` still in n8n, to delete in the editor. SES role needed no static keys, so the IAM-user fallback was not used.
- Rubric: Cloud (SES access with no long-lived keys, least-privilege role limited to 3 identities, verified-TLS DB access from n8n), n8n (credentials named and ready for A/B/C/E).
- Explain it back:
  - Built: the four named n8n credentials, an SES-only IAM role reachable only from the n8n instance role, and a mounted RDS CA so n8n verifies the database certificate.
  - Why this over the obvious alternative (turn on "Ignore SSL Issues", or create an IAM user with access keys): the toggle encrypts but does not verify the server, and access keys would sit in n8n's database indefinitely. A mounted CA keeps full verification, and role chaining leaves nothing long-lived to leak or rotate.
  - Q: Why did the first Postgres test fail, and why not just ignore it? A: Node did not trust the Amazon RDS CA. Ignoring it would still encrypt but would accept any certificate; adding the CA proves we are talking to our RDS.
  - Q: What can the SES role do if the n8n box is compromised? A: Send mail from or to three verified test addresses only, and the SES sandbox adds a second limit (verified recipients, 200 per day).
  - Q: The form demanded an External ID. Is that a security control? A: No. Our trust policy has no condition on it, so it is ignored; the real control is that only the instance role can assume the role.

### T27 — Crawl targets (2026-10-21)
- Files: docs/decisions.md ("Crawl targets" rewritten with measured results)
- Evidence (probe run on the n8n instance `i-02ffa9d08e8403a4a` via SSM Run Command, so it is the IP n8n will crawl from; temp files deleted afterwards):
  - First GET of the old `.com` URLs: ICICI/Kotak/IDFC `301`, HDFC `301` (167 B). With redirects followed: ICICI 200 / 1,242,503 B, HDFC 200 / 1,096,086 B, BankBazaar 200 / 219,149 B, Kotak 200 / 820,923 B, IDFC FIRST 200 / 2,667,536 B.
  - `urllib.robotparser` on each host's robots.txt (all 200): target path allowed for `*` on ICICI, HDFC (`www.hdfc.bank.in`), BankBazaar, IDFC FIRST.
  - ICICI: "Minimum monthly income of ₹30,000 and total of 2 years of work experience for salaried individuals"; "A credit score of 700 and above is preferred".
  - HDFC: "Age: 21 to 60 years"; "Minimum monthly net income of ₹25,000".
  - IDFC FIRST: "Your age should be between 21 to 60 years"; "CIBIL Score: You should have a CIBIL Score of 710 or above"; "9.99% p.a.".
  - BankBazaar table: "Age limit 21 - 68 years", "Minimum Net Monthly Income Rs.5,000 and above", "CIBIL score of 750 or more", "Maximum EMI Up to 65% of Income".
  - Kotak page: rate "Starting at 10.99% p.a." but no income/age/score criteria, so rejected.
- Quality gates: no Python touched.
- Open items for T28/T30: ICICI and HDFC print no interest rate in the criteria text (rate fields stay NULL, lower `parse_confidence`); HDFC publishes no score floor. Selectors are first guesses from raw HTML and are confirmed in T28.
- Rubric: n8n Workflow Design (crawl targets, change-detection scope).
- Explain it back:
  - Built: a live, measured choice of crawl targets, probed from the same IP the workflow will use, with robots.txt checked by a parser and verbatim criteria snippets per page.
  - Why this over the obvious alternative (reuse the laptop probe from 2026-10-20): the banks have since moved to `bank.in` redirects and a laptop IP can be treated differently from an AWS IP, so only a probe from EC2 proves the workflow will get the same HTML.
  - Q: Why not crawl all five candidates? A: Kotak has no criteria in static HTML and BankBazaar is an aggregator, not a lender's product; three real lenders give distinct thresholds (₹25k/₹30k income, 700/710 score) without extra maintenance.
  - Q: What if a site blocks the EC2 IP or changes its layout? A: The site list is config-driven, each site has its own error branch (T31) so the others still update, and BankBazaar is a ready spare.
  - Q: Why extract text lines instead of relying on CSS classes? A: The sites use generated class names that can change; anchoring on income/age/score/rate wording survives redesigns and also gives a stable text to hash for change detection.

### T28 — Workflow A: fetch + extract (2026-10-21)
- Files: n8n/workflows/workflow-a-product-discovery.json (new), docs/decisions.md ("Crawl targets": selectors confirmed, HDFC score floor corrected), docs/rubric-evidence.md, infra/n8n.md (import/run commands).
- Workflow: id `wfaproductdisc01`, 8 nodes + sticky note, inactive. `Trigger · Daily 06:00 IST` and `Trigger · Manual run` → `Config · Crawl targets` (Code, 4 sites, `enabled` flag, BankBazaar spare disabled) → `Fetch · Crawl page` (HTTP Request: browser User-Agent, redirects, 30 s timeout, Retry On Fail 3 × 5 s, 1 request / 2 s, full response, never error, continue on error) → `Check · Page fetched OK` → true: `Extract · Criteria blocks` (HTML Extract, per-site selector) → `Normalize · Criteria lines` (Code, per item); false: `Mark · Fetch failed` (Set).
- Evidence (n8n 2.44.4 on `i-02ffa9d08e8403a4a`, execution ids from `execution_entity`):
  - DOM probe from the EC2 IP found real selectors for all 4 pages (ICICI `span.step-bullet`, HDFC `span.description`, IDFC `li.eligi-hover-content`, BankBazaar `table.w-full tr`).
  - First run (execution 11): every node `success`, 3 items through; criteria text had glued words ("forself-employed"), image paths and advice lines. Fixed (`cleanUpText` off, bracket strip, number-or-employment and boilerplate filters).
  - Final run (execution 14): `Config` 3 items → `Fetch` 3 × HTTP 200 (1,233,541 / 1,095,978 / 2,666,718 chars, 6.2 s total) → `Extract` 1.5 s → `Normalize` 0.25 s; ICICI 13, HDFC 18, IDFC FIRST 6 `criteria_lines`, all `status: ok`. Same counts as execution 12, so the output is stable between runs.
  - Failure/spare drill (execution 13, temporary config, same workflow id; final file re-imported afterwards): 6 sites in → `Fetch` 6 items → 4 to Extract/Normalize (ICICI 13, HDFC 18, IDFC 6, BankBazaar 23 lines) and 2 to `Mark · Fetch failed`: `HTTP 404` (status 404) and `getaddrinfo ENOTFOUND no-such-host.invalid` (status 0). Execution status stayed `success`.
  - Secrets scan of the JSON: clean; `pinData` empty.
- Quality gates: no Python in the repo touched, so ruff/mypy/pytest not re-run. Scratch scripts (generator, SSM runner, execution reader) are in the session scratchpad only.
- Found: HDFC's FAQ states "minimum credit score of 720" (T27's probe had said HDFC publishes none) → decisions.md corrected; it is a natural borderline case. `n8n execute` needs `N8N_RUNNERS_BROKER_PORT`/`N8N_PORT` overrides and truncates its stdout, so results are read from the saved execution.
- Open: Error Workflow = Workflow E is not set yet (Workflow E is T25); T25 must point A at it. No credentials are used by this part. The workflow stays inactive until T31 so the daily schedule does not run before change detection exists. Executions 11–14 (mode `cli`) remain in the editor list until pruned (168 h).
- Rubric: n8n Workflow Design (config-driven fetch, retry + explicit error branch, per-item robustness, descriptive nodes and sticky note).
- Explain it back:
  - Built: the first half of Workflow A: it fetches each lender's page and reduces it to normalised, sorted criteria lines, with a separate output for pages that failed.
  - Why this over the obvious alternative (one HTML Extract per site, or hash the raw HTML): one generic fetch → extract → normalise chain driven by a site list means adding a lender is a config edit; narrowing by selector but deciding by wording keeps extraction alive through class-name changes, and the output is the stable text T29 will hash.
  - Q: What happens if a site changes layout so the selector matches nothing? A: `Normalize` emits `status: no_criteria_found` with 0 lines rather than failing the run, so later steps (and `crawl_runs`, T29/T31) can flag it without losing the other sites.
  - Q: Why `neverError` plus an IF instead of letting the HTTP node fail? A: A 404/403 is data (a site-level outcome), not a workflow error; routing it keeps the other sites running, and only genuine network errors use continue-on-fail. Drill: a 404 and a DNS failure both reached `Mark · Fetch failed` while 4 other sites were extracted.
  - Q: Why sort and de-duplicate the lines and strip month/year text? A: The page carries repeated and date-bearing text ("in Oct'26"); sorting and stripping make the text identical across days when criteria are unchanged, which is what the T29 content hash needs. Two runs gave identical line counts per site.

### T30 — Workflow A: structuring via LLM Gateway (2026-10-21)
- Files: `n8n/workflows/workflow-a-product-discovery.json` (9 → 20 nodes), `docs/decisions.md` (new section 25 "Product structuring"), `docs/rubric-evidence.md`, `infra/n8n.md` (`groq-api` row). Scratch generator, Code-node sources and test harness are in the session scratchpad only. T26 is not built, so the Groq call is a direct HTTP Request; it becomes an Execute Workflow node when T26 lands.
- New nodes: `Check · Criteria found` → `Prompt · Build Groq request` → `LLM · Structure criteria (Groq)` → side branch `Prepare · llm_calls row` → `Log · llm_calls`, main branch `Route · Groq HTTP status` (200 / 429 / other) → `Coerce · Validate product` → `Check · Product valid`; `Mark · Groq rate limited`, `Mark · Groq call failed`, and one `Log · crawl_runs failure` that every failure path ends in (no-criteria, fetch failed, 429, other HTTP, invalid product). The true output of `Check · Product valid` is left open for T31.
- Evidence (n8n 2.44.4 on `i-02ffa9d08e8403a4a`, via SSM Run Command + `n8n import:workflow` / `n8n execute`; results read from `execution_entity`/`execution_data`):
  - Final run, execution 27: `Fetch` 3 × 200 → `Normalize` 13 / 18 / 6 lines (text hashes identical to executions 15 and 17) → `LLM` 3 × HTTP 200 → `Coerce` 3 → `Check · Product valid` 3 true / 0 false. ICICI: income 30,000, score ≥ 700, age 18–65, rate NULL, Salaried + Self-Employed, conditional, `parse_confidence` 0.60. HDFC: 25,000, ≥ 720, 21–60, NULL, Salaried, conditional, 0.60. IDFC FIRST: NULL, ≥ 710, 21–60, rate from 9.99, Salaried + Self-Employed, not conditional, 0.70. Tokens 3,193 prompt / 719 completion; server latency 612 / 570 / 434 ms.
  - `llm_calls` rows 29–31 for that run (status 200, tokens, `latency_ms`); no duplicate rows.
  - Drill 1, execution 16 (wrong credential): 401 for all three → `Mark · Groq call failed` → `crawl_runs` ("Groq HTTP 401") and `llm_calls` status 401. Cause: `groq-api` held the bare key without `Bearer `; fixed in place by piping `export:credentials --decrypted` through a transform into `import:credentials` (secret never printed or written to disk); `GET /models` then returned 200 from the instance.
  - Drill 2, execution 18 (`max_completion_tokens` 30): Groq returned HTTP 400, not a truncated 200 → other-HTTP branch → `crawl_runs` + `llm_calls` status 400.
  - Drill 3, execution 19 (ICICI forced to a schema-violating 200 via JSON mode): `Coerce` rejected it with 7 reasons (score 1200 outside 300..900; employment `Student`; min_age 60 > max_age 21; four ungrounded numbers), `Check · Product valid` 2 true / 1 false, HDFC and IDFC structured, one `crawl_runs` row.
  - Drill 4, execution 26 (criteria text repeated 14×): first call 200 (4,213 prompt tokens), second HTTP 429 with `retry-after` 21 s ("TPM limit 8000, used 3725, requested 7053") → `Mark · Groq rate limited` → `crawl_runs` with Groq's message; the third lender still structured.
  - Local fixtures: 17 model answers (unit strings, string range, out-of-range, ungrounded, min > max, fractional age, unknown employment, empty array, all NULL, non-JSON, truncated, missing key, array, no choices) behave as designed; found and fixed a regex that turned `"60 years"` into `"60 yea"`.
  - Final DB state (read-only probe, then Workflow A re-imported): `loan_products` 5 rows, all seed, 0 non-seed (nothing is written there until T31); `crawl_runs` 28 rows, `llm_calls` 31 rows, all from T30 development.
  - Retry On Fail finding: with it enabled the `crawl_runs` INSERT ran 3× on success (ids 1–3, 4–6, 7–9, 5 s apart); with it off one row in 27 ms; the post-fix drill (execution 26) gave exactly one row (id 28). Cause not isolated; both Postgres write nodes now have no retry.
  - Secrets scan on touched files: only variable and prose matches; no `gsk_` or `AKIA` anywhere; workflow `pinData` empty; no comments in the Code nodes.
- Quality gates: no Python touched, so ruff / mypy / pytest were not re-run.
- Side effects / open: (1) the `groq-api` credential value was changed (added `Bearer `). (2) `crawl_runs` / `llm_calls` hold drill rows including 17 duplicated failure rows from the retry finding; they are real events, not seed data. Deleting them is a `DELETE` on non-temp tables, so it waits for explicit approval (suggest before T42). (3) Workflow A is still inactive and has no Error Workflow (T25). (4) `Mark · Fetch failed` now also logs to `crawl_runs`, so T31 only has to log successes. (5) T29 can hash `criteria_text` directly; T31 connects `Check · Product valid` true.
- Rubric: n8n Workflow Design (+ structured LLM extraction with explicit status branches, validation beyond the schema, call ledger, measured failure drills).
- Explain it back:
  - Built: the middle of Workflow A. Each lender's criteria text goes to Groq with a strict schema; a Code node then coerces units, enforces the database ranges, rejects numbers that are not in the source text, and computes a completeness-based `parse_confidence`. Anything that fails is logged to `crawl_runs` and never inserted; every call is in `llm_calls`.
  - Why this over the obvious alternative (trust the strict-schema JSON and insert it): a schema guarantees shape, not truth. Without the grounding and range checks a hallucinated `45000` or a NULL that means "no limit" would flow into Stage 1 and silently change who gets matched.
  - Q: Why is an ungrounded number rejected instead of set to NULL? A: NULL means "unconstrained" to Stage 1, so nulling a bad income floor would make the product match everyone. Rejecting keeps the last good row (T31) and logs the reason.
  - Q: Why is `parse_confidence` computed in code and not asked of the model? A: A model's self-score is uncalibrated and cannot be audited. Completeness of the five criteria groups, capped at 0.6 when thresholds depend on employment type, can be recomputed from the row and is exactly what T34 needs to decide "borderline".
  - Q: What happens at 429 today and what is missing? A: The item goes to `Mark · Groq rate limited`, is logged with Groq's message and `retry-after`, and the other lenders continue. Waiting out `retry-after` and falling back to `gpt-oss-20b` is the LLM Gateway (T26), not built; at three calls a day against 30 RPM it has not mattered, and the forced drill shows the branch works.

### T31 — Workflow A: upsert + lifecycle (2026-10-21)
- Files: `n8n/workflows/workflow-a-product-discovery.json` (20 → 24 nodes), `docs/decisions.md` (new section 26 "Product storage and lifecycle"), `docs/rubric-evidence.md`. Scratch generators, drill variants and the SSM/probe helpers are in the session scratchpad only.
- New nodes: `Prepare · loan_products row` (Code) → `Upsert · loan_products + crawl_runs` (Postgres, `queryBatching: independently`, error output on) → success output ends the path; error output → `Mark · Upsert failed` → the existing `Log · crawl_runs failure` → new `Retire · Product after 3 failed runs`. `Check · Product valid` true now feeds `Prepare`. Sticky note rewritten for stages 6–7.
- Evidence (n8n 2.44.4 on `i-02ffa9d08e8403a4a`; execution ids from `execution_entity`; table state read through a read-only probe workflow using the `rds-postgres` credential):
  - Execution 30 (first run): 3 lenders → `Upsert` outputs `[3, 0]`: ICICI id 11, HDFC id 12, IDFC FIRST id 13, all `inserted: true`, `changed: true`; crawl_run ids 29–31. NULL criteria (ICICI/HDFC rate, IDFC income) passed through as SQL NULL.
  - Execution 32 (identical re-run): same ids 11–13, `inserted: false`, `changed: false`, new `ok` rows 32–34. Table: `8 rows, 8 distinct keys, 5 seed, 3 crawled`; `last_seen_at` moved 00:45:32 → 00:47:12 while `created_at` stayed.
  - Execution 44 (temporary variant: extra site returning 404 + ICICI's write forced to `allowed_employment = {Student}`): `Upsert` outputs `[2, 1]` (HDFC, IDFC written; ICICI to the error output), `Mark · Upsert failed` 1, `Log · crawl_runs failure` 2 (ICICI `Database write failed: Failing row contains (…{Student}…)`, `Drill Site 404` `HTTP 404`), execution status `success`.
  - Executions 41, 42, 43 (variant: ICICI URL replaced by a missing page; HDFC and IDFC healthy): `Retire` → `silent_for_3_runs` false / false / true, `retired_count` 0 / 0 / 1; HDFC and IDFC `Upsert` outputs `[2, 0]` each time.
  - Executions 40 and 45 (committed workflow after the outage): ICICI `reactivated: true`, `changed: false`, same product id 11.
  - Final state (probe, execution 46): `loan_products` 8 rows / 8 distinct keys; 5 seed rows all `active`, newest seed `updated_at` 2026-10-20 20:42 (untouched); 3 crawled rows all `active`: ICICI hash `45567b18` conf 0.6, HDFC `462336ae` 0.6, IDFC FIRST `1e36c90b` 0.7.
  - Hygiene: JSON parses, 24 unique node names and ids, `pinData` empty, no `//` or `/* */` in Code nodes, no `--` in SQL, only the sticky note is unconnected; secrets scan of the workflow and decisions.md → only prose and credential names.
- Found and fixed during the drills (both recorded in decisions.md §26):
  1. Default Postgres `queryBatching: single`: the first failing write aborted the node, so HDFC and IDFC were never written (execution 34, status `error`, outputs `[0, 1]`). Fixed with `independently` (execution 35 onward: `[2, 1]`).
  2. A "Wait · All sites finished" Merge + one global `Retire` ran twice per execution (execution 35). Replaced by a per-source `Retire` after the failure log, which is also what the rule needs.
  - The error output exposes no readable `message`; the log stores `description` (first 300 chars).
- Quality gates: no Python in the repo touched, so ruff / mypy / pytest were not re-run.
- Side effects / open: (1) `loan_products` now has 3 crawled rows (real, `is_seed = false`) next to the 5 labelled seed rows; Workflow B (T33) will match against both until the seed rows are deactivated or kept deliberately. (2) `crawl_runs` holds more drill rows (sources `Drill Site 404`, ICICI failures) in addition to T30's; they are real events, deleting them needs approval (suggest before T42). (3) New scratch workflow `scratchprobe0001` ("SCRATCH · read-only probe") was imported into n8n for reads; the CLI has no delete, so delete it in the editor together with `t23probe0001` and `t19stubrecv1`. (4) Workflow A is still inactive with no Error Workflow (T25); activation waits for T29 and T25 so the daily schedule does not run without change detection and alerting. (5) T29 must check that the SHA-256 it computes in the Code node equals the Postgres `sha256` of the same criteria text. (6) T35's verdict cache must key on the structured fields as well as `content_hash`.
- Rubric: n8n Workflow Design (+ per-item isolated DB writes, atomic product + run-log statement, change flag, run-history lifecycle with reactivation, measured failure drills); Backend (+ idempotent upsert on a natural key).
- Explain it back:
  - Built: the second half of Workflow A. Each validated product is upserted on `(source, product_name)` together with its `crawl_runs` row; a failed write is contained to its own site; a source with three failed runs in a row has its product set inactive, and any later good crawl switches it back on.
  - Why this over the obvious alternative (the Postgres node's Insert-or-Update, and a time-based "not seen for N days" sweep): the built-in operation cannot record `last_seen_at`, hash, or the run row in one transaction or tell me whether anything changed, and a date rule would retire products over a weekend outage. One CTE statement does all four and run-history retirement follows the actual crawl log.
  - Q: What stops one lender's bad data or a database error from blocking the others? A: Items are written independently, the error output of the write node routes only the failed item to `Mark · Upsert failed` and the failure log, and the drill showed HDFC and IDFC written while ICICI's forced CHECK violation was logged (execution 44). The first version did not do this: the default batching aborted every item, which the drill caught.
  - Q: Why not delete products that disappear? A: The primary key is referenced by `matches`; deleting would cascade or orphan past recommendations, and a flapping page would lose history. `active = false` hides the product from Stage 1 (`loan_products(active)` index) and keeps the row for reactivation.
  - Q: How do you know a re-run did not create duplicates? A: The key is unique in the schema and the statement upserts on it; after two identical runs the table had 8 rows and 8 distinct keys, and the crawled ids stayed 11, 12, 13 in every later run (drill variants included).

### T32 — Workflow B: webhook + run setup (2026-10-21)
- Files: `n8n/workflows/workflow-b-matching.json` (new, 10 nodes), `docs/decisions.md` (new section 27 "Workflow B entry"), `infra/n8n.md`, `docs/rubric-evidence.md`. Generator, drill variant and SSM helpers are in the session scratchpad only; no Python touched, so ruff / mypy / pytest were not re-run.
- Built: `Trigger · Batch processed (match-batch)` (POST, Header Auth `webhook-secret`, IP allowlist `172.31.0.0/16`, response via node) → `Check · Read batch_id` → `Check · batch_id is a UUID` → `Claim · processed to matching + create run` (one CTE statement: conditional `UPDATE upload_batches`, `users_in_batch × active_products`, `INSERT INTO pipeline_runs`; always returns one row) → `Check · Batch was claimed` → `Respond` 202 / 409; 400 for a bad id, 500 from the Postgres error output. Sticky note on top. Workflow E does not exist (T25), so the error-workflow setting is not set yet.
- Evidence (n8n 2.44.4 on `i-02ffa9d08e8403a4a`, probes run on the instance with the secret piped from SSM, never printed):
  - No header, wrong secret → `HTTP 403 Authorization data is wrong!`; right secret from `127.0.0.1` → `HTTP 403 IP is not allowed to access the webhook!`
  - `{"batch_id":"not-a-uuid"}`, upper-case UUID, `{}` → `HTTP 400` each; well-formed unknown UUID → `HTTP 409`.
  - Live trigger: `scripts/smoke_test.sh` with a 200-row CSV of new users (`@example.invalid`) → batch `4d5d548f-7a9b-41de-a85c-7c8117a181fd` reached `matching`; Lambda log `webhook_sent status=202 attempts=1`; `pipeline_runs` id 2 `total_pairs = 1600` (200 users × 8 active products); `users_in_batch = 200`. A first identical-shaped run (batch `9633897f…`, `total_pairs 1600`) was done before the fix below.
  - Replay: second POST of the same batch → `HTTP 409`, `runs_after_replay = 1`. `execution_entity` shows one execution per real trigger, plus one per my probe (`mode webhook`, `success`); rejected-auth requests create none.
  - Forced error drill (throwaway copy `t32faildrill01`, query `SELECT 1/0`): first version returned **409** (bug), fixed version returned `HTTP 500 {"error":"could not start matching run"}`; drill workflow unpublished, its path then answers 404.
  - After the final restart `n8n list:workflow --active=true` → `wfbmatching001|B · Matching`.
  - Hygiene: JSON parses, 10 unique names and ids, `pinData` empty, no comments in Code or SQL, only the sticky note unconnected; secrets scan → only prose and the credential name `webhook-secret`.
- Found and fixed: `alwaysOutputData` on the Postgres node (added to turn a lost claim into an empty item) also hid the node's error output, so a database error answered 409 and the Lambda would not have retried. Replaced by a statement that always returns one row (`FROM counts LEFT JOIN run`), `run_id IS NULL` meaning "not claimed".
- Cleanup: the 2 test batches, their 400 users (`@example.invalid`) and 2 `pipeline_runs` rows were deleted by literal id in one transaction (`DELETE 2 / 400 / 2`); afterwards `pipeline_runs` had 0 rows and `users` 10,006 (the 6 above the 10,000 sample come from earlier tasks' smoke tests, not from T32). `t32faildrill01` stays inactive in n8n like the earlier probes (no CLI delete).
- Open / decided: (1) The webhook secret is in saved execution data (confirmed); decision in decisions.md §27: keep saving, rotate after the recording, never show the Webhook node output on camera; T45 to revisit. (2) `total_pairs` counts the 5 seed products as well as the 3 crawled ones; T33 must decide whether seed products take part. (3) "Users in batch" = users the batch inserted or changed, so an identical re-upload has 0 pairs; a zero-pair batch still goes to `matching`, so T36 must finish such a run. (4) A batch stays in `matching` until T36 moves it on; nothing in T32 does.
- Rubric: n8n Workflow Design (+ named nodes, sticky note, explicit 400 / 409 / 500 branches, atomic claim, measured drills); Cloud Architecture (+ secure n8n integration: all four webhook layers now proven end to end).
- Explain it back:
  - Built: the front door of Workflow B. A Lambda-only, secret-protected webhook that turns a `processed` batch into a `matching` batch with exactly one `pipeline_runs` row holding the first funnel number (`total_pairs`), and answers 202, or 409 for a replay.
  - Why this over the obvious alternative (separate Postgres nodes for status update, count and run insert): one data-modifying CTE statement is atomic, so no crash window leaves a batch in `matching` without a run row, and the status condition doubles as the replay guard. It is also one round trip.
  - Q: What stops two deliveries of the same batch from starting two matching runs? A: The `UPDATE … WHERE status = 'processed'` is the claim; Postgres lets only one transaction flip the row, the second finds `matching`, inserts no run and gets 409. Proven: the replay POST left exactly one `pipeline_runs` row.
  - Q: Why did the first forced-error drill return 409 and why does that matter? A: `Always Output Data` put an empty item on the success output when the query failed, so the error output never fired and a broken database looked like a replay. The Lambda does not retry 409, so the batch would have waited for a manual retrigger. The fix is a query that always returns a row.
  - Q: Why is the webhook secret still readable in n8n's execution history, and is that acceptable? A: n8n stores the trigger output with its headers and has no per-node opt-out in this version. It stays inside the VPC-only instance that already holds the encryption key, is pruned after 168 h, and will be rotated after the demo; disabling execution saving would also remove the evidence reviewers can open.

### T33 — Workflow B: Stage 1 SQL pre-filter (2026-10-21)
- Decisions (⚖️, user said "go" to all three): (1) seed products out of matching, (2) candidate pairs stay in Postgres in a new `match_candidates` table, (3) keep near misses with a 5% margin on income / score floors and the score ceiling, tagged with the missed criteria; age and employment strict.
- Files: `db/0002_match_candidates.sql` (new: `match_candidates`, `pipeline_runs.stage1_near_miss`), `db/migrate.py` (registers 0002), `db/seed_products.sql` (new seed rows inserted inactive), `n8n/workflows/workflow-b-matching.json` (+3 nodes, sticky note), `tests/integration/test_stage1_prefilter_db.py` (new, 4 tests that run the SQL read from the workflow JSON), `tests/integration/test_migrate_db.py` (2 migrations, 11 schema tables, seed inactive), `docs/stage1-explain.md` (new), `docs/decisions.md` (section 28), `infra/n8n.md`, `docs/rubric-evidence.md`. Generator and SQL helpers are in the session scratchpad only.
- Built: `Respond · 202` → `Stage 1 · SQL pre-filter` (one `INSERT … SELECT … ON CONFLICT DO NOTHING` into `match_candidates`, returns its `statement_timestamp()`) → `Record · Stage 1 funnel` (counts from the table into `stage1_pairs` / `stage1_near_miss`, `stage_ms.stage1` from Stage 1's start to after its commit, first measurement kept). Both have Retry On Fail (3 × 2 s) because both are idempotent; their error outputs go to `Fail · Mark batch failed (Stage 1)` (`matching → failed` with the error text, run closed).
- Evidence (RDS PostgreSQL 16.9 via SSM from `i-02ffa9d08e8403a4a`, n8n 2.44.4):
  - Before building, independent count on the sample batch `9d278e88…`: strict 4,425 / 1,840 / 4,140 and near miss +1,478 / +743 / +1,539 for products 11 / 12 / 13.
  - Migration on RDS with `infra/ec2/migrate.sh` (password read from SSM on the instance): `{"stage": "migration_applied", "version": "0002_match_candidates", "duration_ms": 29}`, `seed_done count 0`; `schema_migrations` = `0001_schema, 0002_match_candidates`.
  - `UPDATE loan_products SET active = false WHERE id IN (1,2,3,4,5) AND is_seed AND active` → `UPDATE 5`; active products now 11, 12, 13 only.
  - Live run through `scripts/retrigger_batch.sh` (same webhook path as the Lambda) → `webhook HTTP 202`; `pipeline_runs` id 7: `total_pairs 30000, stage1_pairs 14165, stage1_strict 10405, stage1_near_miss 3760, stage_ms {"stage1": 578}`. Per product 5,903 / 2,583 / 5,679, identical to the independent count. Near misses: `{min_credit_score}` 3,718, `{min_monthly_income}` 29, both 13. 6,088 users have a candidate.
  - Re-run of both node statements on RDS for run 7 → `inserted_on_rerun 0`, same counts, `stage1_ms 578` kept.
  - Hand check: `bb0d9e4a…` (₹60k, 760, 34, Salaried) strict for all 3; `03b9e667…` (₹65k, 690, 44, Self-Employed) near miss `min_credit_score` for ICICI and IDFC, excluded by HDFC (Salaried only); `003190f1…` (Business) no candidate. Each agrees with the product criteria.
  - `EXPLAIN (ANALYZE, BUFFERS)` in a rolled-back transaction → `Execution Time: 566.850 ms`: join 39 ms, insert 161 ms, FK checks 128 + 140 + 127 ms; afterwards still 1 run and 14,165 candidates (`docs/stage1-explain.md`).
  - Forced-error drill (`t33faildrill01`, Stage 1 = `SELECT 1/0`): `drill HTTP 202`; Stage 1 node `executionTime 4047 ms` (3 tries), then `Fail ·` node 33 ms; batch `failed`, `error = matching stage 1 failed: division by zero`, run `finished_at` set, `stage1_pairs` NULL, 0 candidates. Drill unpublished → path 404; `n8n list:workflow --active=true` → `wfbmatching001|B · Matching`.
  - Tests: `make check` → ruff `All checks passed!`, `68 files already formatted`, mypy `Success: no issues found in 54 source files`, `321 passed`, coverage 100.00% (with `TEST_DB_HOST` on a throwaway `postgres:16`).
  - Mutation probes on the workflow SQL (file restored after each, `cmp` clean): margin 0 → 2 tests fail; `NULL employment` treated as "nobody" → 2 fail; keep-first timing guard removed → 1 fails.
  - Hygiene: JSON parses, 13 unique node names and ids, `pinData` empty, no comments in SQL or Code nodes; secrets scan → only the sticky-note prose and the credential name `webhook-secret`.
- Found and fixed: (1) the first version recorded `stage_ms.stage1 = 153` for work that took 556 ms, because foreign-key checks run at the end of the statement after its `clock_timestamp()`; split into a record node that measures after the commit (live 578 ms vs plan 567 ms). (2) A manual re-run replaced the measured 561 ms with 79 ms; the record node now keeps the first measurement.
- State left: batch `9d278e88…` is in `matching` with run 7 and its 14,165 candidates, ready for T34. Runs 3, 5 and 6 (my earlier runs and the drill) were deleted by batch id inside a transaction and the batch reset to `processed` before each rerun; run id 4 was used by the rolled-back EXPLAIN, so ids have gaps.
- Open: (1) No crawled product allows `Business`, so all 3,240 Business users (32%) are out at Stage 1; a Workflow A structuring question, recorded in decisions.md §28 for T34/T35. (2) The deployed `batchStatus` Lambda does not return `stage1_near_miss` yet; add it with T40 (UI funnel). (3) Errors caught by the failure branch are saved as `success` executions, so Workflow E (T25) will not see them; the batch `error` column holds them. (4) The planner estimates 313 rows for 14,165; re-check the plan at T37 scale after `ANALYZE`. (5) `t33faildrill01` stays inactive in the n8n database.
- Rubric: n8n Workflow Design (+ Treasure Hunt stage 1 with measured funnel 30,000 → 14,165, set-based in Postgres instead of n8n items, idempotent nodes with justified Retry On Fail, explicit failure branch proven by a drill); Backend (+ migration 0002, integration tests that run the workflow's own SQL, EXPLAIN evidence).
- Explain it back:
  - Built: Stage 1 of the matching funnel. One SQL statement pairs the batch's users with the active products on the hard criteria and stores the 14,165 survivors (of 30,000) in `match_candidates`, each marked as a strict pass or a near miss that names the criterion it missed. A second node records the counts and the measured time.
  - Why this over the obvious alternative (strict filter, pairs returned to n8n as items): n8n keeps all items in memory and in its execution log on a 2 GB box, so pairs stay in Postgres. A strict filter would drop users at 690 for a "700 is preferred" product before the LLM stage could judge that wording.
  - Q: Why is Retry On Fail safe here when you removed it from the T30 INSERT and the T32 claim? A: These two statements are idempotent by construction: `ON CONFLICT DO NOTHING` on the pair key, counts read from the table, the first timing kept. Re-running on RDS inserted 0 rows and left every number unchanged. The T30 INSERT and the T32 claim give a different result the second time.
  - Q: Your first version reported 153 ms. How do you know 578 ms is right? A: `EXPLAIN ANALYZE` showed the foreign-key triggers (about 395 ms) run at the end of the statement, after its clock read. The record node now measures from Stage 1's start to after its commit on the database clock, and gets 578 ms against 567 ms in the plan.
  - Q: What happens if Stage 1 fails half-way? A: Nothing half-way exists: the insert is one statement, so it commits completely or not at all. After 3 tries the failure branch moves the batch from `matching` to `failed` with the error text and closes the run; the drill showed this with 0 candidates written.
