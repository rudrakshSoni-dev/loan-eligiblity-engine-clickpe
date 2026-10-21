ALTER TABLE match_candidates
    ADD COLUMN cohort_key text CHECK (btrim(cohort_key) <> ''),
    ADD COLUMN stage3_outcome text
        CHECK (stage3_outcome IN ('eligible', 'not_eligible', 'unresolved_budget',
                                  'unresolved_error')),
    ADD COLUMN stage3_reason text,
    ADD CHECK (cohort_key IS NULL OR stage2_class = 'borderline'),
    ADD CHECK (stage3_outcome IS NULL OR cohort_key IS NOT NULL),
    ADD CHECK ((stage3_outcome IS NULL) = (stage3_reason IS NULL));

ALTER TABLE pipeline_runs
    ADD COLUMN stage3_eligible integer CHECK (stage3_eligible >= 0),
    ADD COLUMN stage3_not_eligible integer CHECK (stage3_not_eligible >= 0),
    ADD COLUMN unresolved_error integer CHECK (unresolved_error >= 0),
    ADD CHECK (stage3_eligible + stage3_not_eligible + unresolved_budget + unresolved_error
               = stage2_borderline),
    ADD CHECK (cache_hits <= llm_cohorts);

ALTER TABLE llm_calls
    ADD COLUMN run_id bigint REFERENCES pipeline_runs (id) ON DELETE SET NULL,
    ADD CHECK (run_id IS NULL OR batch_id IS NOT NULL);

CREATE INDEX llm_calls_created_at_idx ON llm_calls (created_at);
