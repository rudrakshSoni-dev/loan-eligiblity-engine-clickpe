# Data notes — sample `users.csv`

Observed on 2026-10-20. File: 993,191 bytes, UTF-8, comma-delimited, header row + **10,000 data rows**. Every row has exactly 7 fields; no malformed rows, no empty values, no leading/trailing whitespace.

## Columns

| Column | Observed type | Nulls | Distinct | Min / Max | Notes |
|---|---|---|---|---|---|
| `user_id` | UUID string (36 chars) | 0 | 10,000 | n/a | Unique, all valid UUIDs. Natural primary key. |
| `name` | text (≤ 20 chars) | 0 | 2,632 | n/a | Names repeat across users. |
| `email` | text (≤ 32 chars) | 0 | 2,632 | n/a | All `@example.com`. **Not unique**: 7,368 duplicate rows; each email is shared by 2–5 users. One email per name. |
| `monthly_income` | integer (whole rupees) | 0 | 126 | 25,000 / 150,000 | Always a multiple of 1,000. |
| `credit_score` | integer | 0 | 31 | 650 / 800 | Always a multiple of 5. |
| `employment_status` | text, 3 values | 0 | 3 | n/a | `Salaried` 3,389 · `Self-Employed` 3,371 · `Business` 3,240. Case and hyphenation exactly as shown. |
| `age` | integer | 0 | 29 | 22 / 50 | |

## Implications

**T08 schema**
- `users.user_id`: `uuid` primary key (not serial).
- `email` must NOT be unique and must not be the upsert key. Upsert on `user_id` only.
- `monthly_income`: `numeric(12,2)` is fine (data is whole numbers). `credit_score`, `age`: `int`, with CHECK ranges looser than observed (e.g. score 300–900, age 18–100), so valid future uploads are not rejected.
- `employment_status`: `text`, validated in code against the 3 observed values (a CHECK constraint is optional; new statuses should be a deliberate change).

**T16 validation**
- Required columns: all 7. Reject rows with a missing/blank value, a non-UUID `user_id`, a non-numeric income/score/age, or an unknown `employment_status`.
- Strip whitespace; match `employment_status` exactly (consider case-insensitive normalisation).
- The sample has zero bad rows, so `/tests/` needs synthetic bad-row CSVs of its own.

**Matching (Workflow B)**
- Only 3 employment values, ~126 income levels, 31 score levels and 29 ages, yet the combinations are nearly all distinct: 9,869 distinct (income, score, age, employment) tuples across 10,000 users (T07 analysis). Raw-value cohorts therefore do not shrink the LLM workload; Stage 3 cohorts are keyed by the *reason* a pair is borderline instead (see `decisions.md` → Treasure Hunt).
- Duplicate emails matter for Workflow C: do not group or dedupe notifications by email, only by `user_id`. Per CLAUDE.md §0.5, no mail goes to these addresses anyway; they are only quoted as "intended for" in the body.

## Housekeeping
- The file lives at `data/users.csv`, and `data/` is gitignored (`git check-ignore -v data/users.csv` → `.gitignore:4:data/`). The sample is never committed.
