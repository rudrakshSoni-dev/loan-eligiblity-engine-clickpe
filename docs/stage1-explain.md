# Stage 1 pre-filter: query plan on RDS

What this is: `EXPLAIN (ANALYZE, BUFFERS)` of the exact statement in the Workflow B node
`Stage 1 · SQL pre-filter` (`n8n/workflows/workflow-b-matching.json`), run on 2026-10-21 against the
private RDS instance (PostgreSQL 16.9, `db.t4g.micro`) from the n8n EC2 host.

Input: the real 10,000-row sample batch `9d278e88-bab6-4634-84d4-1c985a271a2a` and the 3 active crawled
products (ICICI 11, HDFC 12, IDFC FIRST 13; the 5 seed products are inactive). That is 30,000 user ×
product pairs.

Method: `BEGIN`, insert a temporary `pipeline_runs` row, `EXPLAIN ANALYZE` the statement with that run id,
`ROLLBACK`. After the rollback the table still held the 1 real run and its 14,165 candidates, so the
measurement changed nothing.

## Reading the plan

| Step | Time | What it means |
|---|---|---|
| Seq Scan on `users` | 4.3 ms | 10,000 of 10,006 users belong to this batch, so a scan beats `users_batch_id_idx`. For a small batch among many users the planner would use the index |
| Nested Loop × Materialize(3 products) | 39 ms total | 30,000 pair checks in memory; 15,835 removed by the join filter, 14,165 kept |
| Insert into `match_candidates` | 161 ms (incl. the join) | Primary key and `(run_id, product_id)` index maintenance |
| 3 foreign-key checks | 128 + 140 + 127 ms | They run at the end of the statement, once per inserted row |
| **Execution total** | **567 ms** | |

- **The foreign-key checks are 70% of the time.** `run_id`, `user_id` and `product_id` are each checked per
  row. They were kept on purpose (≈0.4 s per 14k rows), because they make cleanup cascade and stop a
  candidate from pointing at a deleted user.
- **Timing is recorded after the commit.** The checks run after any `clock_timestamp()` in the same statement
  would be read. That is why `stage_ms.stage1` is written by the next node, `Record · Stage 1 funnel`, from
  the statement's start time to after its commit. A first version recorded 153 ms for the same work; the
  live run with the fix recorded 578 ms, which agrees with this plan.
- **The row estimate is far off** (313 estimated, 14,165 actual). With 3 products a nested loop is right
  whatever the estimate. For T37 (100k users) the plan must be checked again after `ANALYZE`.

## Plan (verbatim)

```
Result  (cost=74578.30..74578.31 rows=1 width=80) (actual time=167.108..167.110 rows=1 loops=1)
  Buffers: shared hit=114646 dirtied=148 written=144
  I/O Timings: shared write=2.715
  CTE inserted
    ->  Insert on match_candidates  (cost=0.00..74571.24 rows=313 width=60) (actual time=0.215..160.674 rows=14165 loops=1)
          Conflict Resolution: NOTHING
          Conflict Arbiter Indexes: match_candidates_pkey
          Tuples Inserted: 14165
          Conflicting Tuples: 0
          Buffers: shared hit=114646 dirtied=148 written=144
          I/O Timings: shared write=2.715
          ->  Nested Loop  (cost=0.00..74571.24 rows=313 width=60) (actual time=0.055..39.147 rows=14165 loops=1)
                Join Filter: (((p.min_age IS NULL) OR (u.age >= p.min_age)) AND ((p.max_age IS NULL) OR (u.age <= p.max_age)) AND ((p.min_monthly_income IS NULL) OR (u.monthly_income >= (p.min_monthly_income * 0.95))) AND ((p.min_credit_score IS NULL) OR ((u.credit_score)::numeric >= ((p.min_credit_score)::numeric * 0.95))) AND ((p.max_credit_score IS NULL) OR ((u.credit_score)::numeric <= ((p.max_credit_score)::numeric * 1.05))) AND ((p.allowed_employment IS NULL) OR (u.employment_status = ANY (p.allowed_employment))))
                Rows Removed by Join Filter: 15835
                Buffers: shared hit=184
                ->  Seq Scan on users u  (cost=0.00..305.07 rows=10000 width=36) (actual time=0.011..4.265 rows=10000 loops=1)
                      Filter: (batch_id = '9d278e88-bab6-4634-84d4-1c985a271a2a'::uuid)
                      Rows Removed by Filter: 6
                      Buffers: shared hit=180
                ->  Materialize  (cost=0.00..13.38 rows=135 width=60) (actual time=0.000..0.000 rows=3 loops=10000)
                      Buffers: shared hit=4
                      ->  Seq Scan on loan_products p  (cost=0.00..12.70 rows=135 width=60) (actual time=0.006..0.022 rows=3 loops=1)
                            Filter: active
                            Rows Removed by Filter: 5
                            Buffers: shared hit=4
  InitPlan 2 (returns $2)
    ->  Aggregate  (cost=7.04..7.05 rows=1 width=8) (actual time=167.104..167.105 rows=1 loops=1)
          Buffers: shared hit=114646 dirtied=148 written=144
          I/O Timings: shared write=2.715
          ->  CTE Scan on inserted  (cost=0.00..6.26 rows=313 width=0) (actual time=0.217..165.662 rows=14165 loops=1)
                Buffers: shared hit=114646 dirtied=148 written=144
                I/O Timings: shared write=2.715
Planning:
  Buffers: shared hit=304
Planning Time: 1.132 ms
Trigger for constraint match_candidates_run_id_fkey: time=127.768 calls=14165
Trigger for constraint match_candidates_user_id_fkey: time=140.075 calls=14165
Trigger for constraint match_candidates_product_id_fkey: time=127.464 calls=14165
Execution Time: 566.850 ms
```
