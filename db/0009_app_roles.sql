DO $roles$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_ingest') THEN
        CREATE ROLE app_ingest LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_n8n') THEN
        CREATE ROLE app_n8n LOGIN;
    END IF;
END
$roles$;

ALTER ROLE app_ingest CONNECTION LIMIT 10;
ALTER ROLE app_n8n CONNECTION LIMIT 20;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM app_ingest, app_n8n;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM app_ingest, app_n8n;

GRANT SELECT, INSERT, UPDATE ON upload_batches, chunk_loads, users TO app_ingest;
GRANT SELECT, INSERT ON rejected_rows TO app_ingest;
GRANT SELECT ON matches, pipeline_runs TO app_ingest;

GRANT SELECT, UPDATE ON upload_batches TO app_n8n;
GRANT SELECT ON users, app_config TO app_n8n;
GRANT SELECT, INSERT, UPDATE ON loan_products, pipeline_runs, match_candidates, matches, n8n_errors TO app_n8n;
GRANT SELECT, INSERT ON crawl_runs, cohort_verdicts, llm_calls TO app_n8n;

CREATE OR REPLACE FUNCTION analyze_match_candidates() RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
BEGIN
    ANALYZE public.match_candidates;
END
$function$;

REVOKE ALL ON FUNCTION analyze_match_candidates() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analyze_match_candidates() TO app_n8n;
