-- Self-asserting constraint checks for db/schema.sql.
--
-- Run:  psql -v ON_ERROR_STOP=1 -f tests/sql/schema_constraints.sql
-- Every statement runs inside one transaction that is rolled back, so this is
-- safe to run against any database that has the schema, including RDS (T13).
-- Each bad row must fail with the expected SQLSTATE; otherwise the script stops.

BEGIN;

-- Runs one statement and raises unless it fails with the expected SQLSTATE.
CREATE FUNCTION pg_temp.expect_error(label text, stmt text, expected text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    got text;
BEGIN
    BEGIN
        EXECUTE stmt;
    EXCEPTION WHEN OTHERS THEN
        got := SQLSTATE;
    END;
    IF got IS NULL THEN
        RAISE EXCEPTION 'FAIL %: statement was accepted', label;
    ELSIF got <> expected THEN
        RAISE EXCEPTION 'FAIL %: expected SQLSTATE %, got %', label, expected, got;
    END IF;
    RAISE NOTICE 'ok   % (rejected, %)', label, got;
END;
$$;

-- Known-good rows: a sample-shaped user and a fully specified product must be accepted.
INSERT INTO upload_batches (id, s3_key)
VALUES ('00000000-0000-4000-8000-000000000001', 'uploads/00000000-0000-4000-8000-000000000001.csv');
INSERT INTO users (user_id, name, email, monthly_income, credit_score, employment_status, age, batch_id)
VALUES ('b35de23e-755f-4c6a-81d8-f7dd99ce53ef', 'Dhruv Iyengar', 'dhruv.iyengar@example.com',
        131000, 725, 'Self-Employed', 37, '00000000-0000-4000-8000-000000000001');
INSERT INTO loan_products (source, product_name, interest_rate_min, interest_rate_max,
                           min_monthly_income, min_credit_score, max_credit_score,
                           min_age, max_age, allowed_employment, parse_confidence)
VALUES ('test', 'Valid Product', 10.5, 24, 25000, 650, 900, 21, 60, ARRAY['Salaried'], 0.9);
INSERT INTO chunk_loads (batch_id, chunk_no, rows_ok, rows_rejected)
VALUES ('00000000-0000-4000-8000-000000000001', 0, 5000, 0);

DO $$
DECLARE
    b   constant text := '''00000000-0000-4000-8000-000000000001''';
    usr constant text := 'INSERT INTO users (user_id, name, email, monthly_income, credit_score, '
                         'employment_status, age, batch_id) VALUES (gen_random_uuid(), ';
    prd constant text := 'INSERT INTO loan_products (source, product_name, ';
BEGIN
    -- users: rules from docs/data-notes.md
    PERFORM pg_temp.expect_error('credit score above 900',
        usr || '''A'', ''a@example.com'', 50000, 950, ''Salaried'', 30, ' || b || ')', '23514');
    PERFORM pg_temp.expect_error('age below 18',
        usr || '''A'', ''a@example.com'', 50000, 700, ''Salaried'', 15, ' || b || ')', '23514');
    PERFORM pg_temp.expect_error('non-positive income',
        usr || '''A'', ''a@example.com'', 0, 700, ''Salaried'', 30, ' || b || ')', '23514');
    PERFORM pg_temp.expect_error('non-canonical employment status',
        usr || '''A'', ''a@example.com'', 50000, 700, ''salaried'', 30, ' || b || ')', '23514');
    PERFORM pg_temp.expect_error('email not normalised',
        usr || '''A'', ''A@Example.com'', 50000, 700, ''Salaried'', 30, ' || b || ')', '23514');
    PERFORM pg_temp.expect_error('blank name',
        usr || ''' '', ''a@example.com'', 50000, 700, ''Salaried'', 30, ' || b || ')', '23514');
    PERFORM pg_temp.expect_error('missing name',
        usr || 'NULL, ''a@example.com'', 50000, 700, ''Salaried'', 30, ' || b || ')', '23502');
    PERFORM pg_temp.expect_error('unknown batch',
        usr || '''A'', ''a@example.com'', 50000, 700, ''Salaried'', 30, gen_random_uuid())', '23503');
    PERFORM pg_temp.expect_error('user_id not a UUID',
        'INSERT INTO users (user_id, name, email, monthly_income, credit_score, employment_status, '
        'age, batch_id) VALUES (''not-a-uuid'', ''A'', ''a@example.com'', 50000, 700, '
        '''Salaried'', 30, ' || b || ')', '22P02');
    PERFORM pg_temp.expect_error('duplicate user_id',
        'INSERT INTO users SELECT * FROM users LIMIT 1', '23505');

    -- ingestion bookkeeping
    PERFORM pg_temp.expect_error('unknown batch status',
        'UPDATE upload_batches SET status = ''done''', '23514');
    PERFORM pg_temp.expect_error('chunks_done above total_chunks',
        'UPDATE upload_batches SET total_chunks = 2, chunks_done = 3', '23514');
    PERFORM pg_temp.expect_error('duplicate chunk delivery',
        'INSERT INTO chunk_loads (batch_id, chunk_no, rows_ok, rows_rejected) VALUES ('
        || b || ', 0, 5000, 0)', '23505');

    -- loan_products
    PERFORM pg_temp.expect_error('rate min above max',
        prd || 'interest_rate_min, interest_rate_max) VALUES (''t'', ''p1'', 24, 10.5)', '23514');
    PERFORM pg_temp.expect_error('credit score range inverted',
        prd || 'min_credit_score, max_credit_score) VALUES (''t'', ''p2'', 800, 700)', '23514');
    PERFORM pg_temp.expect_error('unknown employment in product',
        prd || 'allowed_employment) VALUES (''t'', ''p3'', ARRAY[''Student''])', '23514');
    PERFORM pg_temp.expect_error('empty employment list',
        prd || 'allowed_employment) VALUES (''t'', ''p4'', ARRAY[]::text[])', '23514');
    PERFORM pg_temp.expect_error('confidence above 1',
        prd || 'parse_confidence) VALUES (''t'', ''p5'', 1.5)', '23514');
    PERFORM pg_temp.expect_error('content hash not SHA-256 hex',
        prd || 'content_hash) VALUES (''t'', ''p6'', ''abc'')', '23514');
    PERFORM pg_temp.expect_error('duplicate (source, product_name)',
        'INSERT INTO loan_products (source, product_name) VALUES (''test'', ''Valid Product'')',
        '23505');

    -- matches
    PERFORM pg_temp.expect_error('unknown match stage',
        'INSERT INTO matches (user_id, product_id, stage, reason, batch_id) '
        'SELECT u.user_id, p.id, ''guess'', ''r'', u.batch_id FROM users u, loan_products p', '23514');
END;
$$;

-- Positive behaviour the pipeline depends on.
DO $$
DECLARE
    n integer;
    t timestamptz;
BEGIN
    -- A redelivered chunk with ON CONFLICT DO NOTHING inserts nothing and raises nothing.
    WITH ins AS (
        INSERT INTO chunk_loads (batch_id, chunk_no, rows_ok, rows_rejected)
        VALUES ('00000000-0000-4000-8000-000000000001', 0, 5000, 0)
        ON CONFLICT DO NOTHING RETURNING 1
    ) SELECT count(*) INTO n FROM ins;
    IF n <> 0 THEN RAISE EXCEPTION 'FAIL redelivery inserted % rows', n; END IF;
    RAISE NOTICE 'ok   redelivered chunk is a no-op';

    -- The trigger owns updated_at: a write path cannot set it to a stale value.
    UPDATE users SET age = 38, updated_at = '2000-01-01' RETURNING updated_at INTO t;
    IF t <> now() THEN RAISE EXCEPTION 'FAIL updated_at not maintained by trigger: %', t; END IF;
    RAISE NOTICE 'ok   updated_at set by trigger';

    -- A NULL criterion is allowed (means unconstrained).
    INSERT INTO loan_products (source, product_name) VALUES ('test', 'No Criteria');
    RAISE NOTICE 'ok   product with all-NULL criteria accepted';
END;
$$;

ROLLBACK;
