ALTER TABLE pipeline_runs
    ADD COLUMN stage1_near_miss integer CHECK (stage1_near_miss >= 0),
    ADD CHECK (stage1_near_miss <= stage1_pairs);

CREATE TABLE match_candidates (
    run_id             bigint  NOT NULL REFERENCES pipeline_runs (id) ON DELETE CASCADE,
    user_id            uuid    NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    product_id         integer NOT NULL REFERENCES loan_products (id),
    near_miss_criteria text[]  NOT NULL DEFAULT '{}'
        CHECK (near_miss_criteria <@ ARRAY['min_monthly_income', 'min_credit_score',
                                           'max_credit_score']),
    PRIMARY KEY (run_id, user_id, product_id)
);

CREATE INDEX match_candidates_run_product_idx ON match_candidates (run_id, product_id);
