# Benchmark: 100,000 users through the real pipeline (T37)

Run on 2026-10-21 (UTC) against the deployed stack in `ap-southeast-2`. Every number below was read from a command listed in this file; nothing is estimated unless the row says so. The input is synthetic data, not the real sample.

## What was run

| Item | Value |
|---|---|
| Input | `data/synthetic_100k.csv`, 100,000 rows, 10,136,283 bytes (gitignored) |
| Generator | `scripts/gen_synthetic_users.py`, seed `20261022`; uniform independent marginals copied from `docs/data-notes.md`; every email ends in `@example.invalid` |
| Path | Browser-equivalent presigned POST → S3 → `split-csv` → SQS → `load-chunk` (`MaximumConcurrency` 3) → Workflow B → Workflow C |
| Mail | Workflow C ran with `app_config.dry_run = true` (read before the run); `matches.notified_at` is set on 0 rows of the batch, so nothing was sent |
| Active products | 3 (ICICI Bank, HDFC Bank, IDFC FIRST Bank personal loans; seeds are inactive) |

```bash
uv run python -m scripts.gen_synthetic_users
./scripts/benchmark_run.sh data/synthetic_100k.csv
```

`benchmark_run.sh` requests a presigned POST, uploads the file with `curl` from a home connection, then polls `batch-status` every 2 s and prints the elapsed time at every status or chunk-count change. Its last 20 s are a settling window, so its "DONE" line adds 20 s that are not pipeline time.

## Timeline of the first run (batch `a32b16fc-3541-42f9-a38c-ecca934a27f3`)

Seconds from the start of the upload, as seen by the polling client (2 s resolution):

| Event | t (s) |
|---|---|
| Upload finished (HTTP 204), limited by the home uplink | 19.1 |
| `loading`, 3/20 chunks | 26.8 |
| `processed`, 20/20 chunks | 39.9 |
| `matching` | 43.1 |
| `notifying` (Workflow C running) | 69.2 |
| `matched` (Workflow C finished, dry run) | 72.3 |

Server-side figures:

| Measure | Value | Source |
|---|---|---|
| `split-csv` | 1,764 ms, 20 chunks of 5,000 rows | CloudWatch `splitCsv`, `stage=upload_split` |
| `load-chunk` duration per chunk | mean 340 ms, max 426 ms; 100,000 inserted, 0 updated, 0 unchanged, 0 rejected | CloudWatch `loadChunk`, `stage=chunk_loaded` |
| First chunk committed → last chunk committed | 13.7 s (20:02:02.9 → 20:02:16.6), about 7,300 rows/s with 3 concurrent loaders | `chunk_loads.loaded_at` |
| Upload finished → `processed` | 20.8 s | client timeline above |
| Workflow B run | 26.5 s (`pipeline_runs.started_at` → `finished_at`) | `batch-status` funnel |
| Database size afterwards | 177 MB (110,006 users, 128,701 matches, 154,097 candidate rows) | `pg_database_size` |

## The funnel (same batch)

| Step | Pairs | Share of previous step | Time |
|---|---|---|---|
| All pairs (100,000 users × 3 products) | 300,000 | | |
| Stage 1, SQL pre-filter (hard criteria, set-based in Postgres) | 139,918 (37,547 of them near-miss) | 46.6% | 5,955 ms |
| Stage 2, rules: clear match | 102,371 | 73.2% | 5,714 ms for the whole stage |
| Stage 2, rules: clear reject | 15,165 | 10.8% | |
| Stage 2, rules: borderline | 22,382 | 16.0% | |
| Stage 3, cohorts formed from the borderline pairs | 22 | | 4,866 ms for the whole stage |
| Stage 3, cohorts already answered in `cohort_verdicts` | 20 | | |
| Stage 3, Groq calls | **1** (1,105 tokens) | | |
| Stage 3, verdicts: eligible / not eligible | 14,479 / 7,903 | | |
| Persist 116,850 matches (102,371 rules + 14,479 LLM) | 116,850 | | 10,315 ms |

Stage times are the nodes' own clocks and sum to 26.85 s against a 26.46 s run window.

The 100,000-user stage times against the 10,000-user sample (`PROGRESS.md`, T33/T34): Stage 1 578 ms → 5,955 ms (10.3×), Stage 2 625 ms → 5,714 ms (9.1×). Both grow in step with the pairs, so neither stage has a hidden super-linear cost at this size.

**Cache caveat.** 20 of the 22 cohorts were answered from `cohort_verdicts` because the earlier 10,000-user runs had already asked the same products the same questions, so this run made one call for the 2 new cohorts. A cold 100,000-user run was not made. The measured cold reference is the 10,000-user sample: 20 cohorts packed into 2 calls, 3,655 tokens (T35). The cohort count moved from 20 to 22 while users went from 10,000 to 100,000, because cohorts are keyed by product, reason, employment and a coarse band of the shortfall, not by user.

## "LLM on every pair" against what the pipeline did

Per-call cost was measured by sending 10 real borderline pairs from this batch to Groq one at a time with the Stage 3 system prompt and schema (`scripts/measure_naive_llm.py`, model `openai/gpt-oss-120b`):

```bash
set -a; . ./.env; set +a
uv run python -m scripts.measure_naive_llm pairs.json --limit 10
```

Result: mean 804 prompt + 124.1 completion = **928.1 tokens per pair**, mean latency 924.6 ms (10 calls).

Groq limits for this model are the ones recorded in `docs/decisions.md` (T04): 30 requests/min, 1,000 requests/day, 8,000 tokens/min, 200,000 tokens/day. The rows below multiply the measured per-pair figures by those limits. They are arithmetic on measured inputs, not runs, and they ignore the 8,000 tokens/min limit, which would only make them slower.

| Approach | Calls | Tokens | Days at 200K tokens/day | Days at 1K requests/day |
|---|---|---|---|---|
| Naive: one call for every pair | 300,000 | 278.4 M | 1,392 | 300 |
| Naive: one call for every borderline pair | 22,382 | 20.8 M | 103.9 | 22.4 |
| This pipeline, warm cache (measured) | 1 | 1,105 | 0.006 | 0.001 |

The pipeline sent 0.00033% of the calls that "ask the LLM about every pair" would need. Against asking only about borderline pairs, 1 call replaces 22,382, which is a measured 22 cohorts and 20 cache hits. The warm-cache row is the best case; the cold case is the 3,655-token, 2-call reference above.

## Idempotency at scale: the same file again (batch `b1586049-ddcd-45a3-a014-7fd0290c2644`)

Uploaded straight after the first run with the same command.

| Check | Result |
|---|---|
| `load-chunk` totals over 20 chunks | 0 inserted, 0 updated, 100,000 unchanged, 0 rejected |
| `users` rows afterwards | 110,006, the same as before |
| Rows tagged with the second batch | 0, so Workflow B found 0 users in it: 0 pairs, 0 LLM calls, 0 matches |
| Matches written by the second batch | 0 |
| Time to `matched` | 32.7 s from the start of the upload (14.0 s of it the upload) |

## Reproduce

1. `uv run python -m scripts.gen_synthetic_users`
2. Check `dry_run` is `true`: `scripts/rds_query.sh "SELECT value FROM app_config WHERE key = 'dry_run'"`
3. `./scripts/benchmark_run.sh data/synthetic_100k.csv`
4. Read the funnel from the final JSON, or `scripts/rds_query.sh` against `pipeline_runs` and `llm_calls` for the batch id.

## Limits of this benchmark

- One run per measurement. The timings are not averaged and no variance is claimed.
- The upload leg is limited by one home connection and is not a property of the pipeline.
- The data is uniform and independent, as the sample is (measured correlations below 0.02). Real borrower data with clustered values would form fewer, larger cohorts, but that was not tested.
- The 100,000 synthetic users remain in the demo database. The mail guard still redirects every send to the test aliases.
