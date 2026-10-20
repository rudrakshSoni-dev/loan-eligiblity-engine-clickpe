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
