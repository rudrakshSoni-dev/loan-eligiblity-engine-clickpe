ALTER TABLE match_candidates
    ADD COLUMN stage2_class text
        CHECK (stage2_class IN ('clear_match', 'clear_reject', 'borderline')),
    ADD COLUMN borderline_reason text CHECK (borderline_reason ~ '^near_miss:[a-z_+]+$'),
    ADD COLUMN trigger_feature text CHECK (trigger_feature IN ('monthly_income', 'credit_score')),
    ADD COLUMN trigger_value numeric(12,2),
    ADD COLUMN indicative_emi numeric(12,2) CHECK (indicative_emi > 0),
    ADD COLUMN stage2_reason text,
    ADD CHECK ((stage2_class = 'borderline') = (borderline_reason IS NOT NULL)),
    ADD CHECK ((borderline_reason IS NULL) = (trigger_feature IS NULL)),
    ADD CHECK ((trigger_feature IS NULL) = (trigger_value IS NULL)),
    ADD CHECK ((stage2_class IS NULL) = (stage2_reason IS NULL));

CREATE INDEX match_candidates_borderline_idx ON match_candidates (run_id, product_id)
    WHERE stage2_class = 'borderline';

ALTER TABLE pipeline_runs
    ADD COLUMN stage2_reject integer CHECK (stage2_reject >= 0),
    ADD CHECK (stage2_clear + stage2_borderline + stage2_reject = stage1_pairs);
