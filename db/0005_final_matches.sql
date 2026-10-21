ALTER TABLE pipeline_runs
    ADD CONSTRAINT pipeline_runs_final_matches_funnel
    CHECK (final_matches = stage2_clear + stage3_eligible);
