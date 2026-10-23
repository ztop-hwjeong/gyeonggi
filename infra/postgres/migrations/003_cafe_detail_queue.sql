BEGIN;

CREATE INDEX IF NOT EXISTS article_detail_results_source_idx
    ON st.article_detail_results (source_id, (result->'seed'->>'source'), run_id);

COMMIT;
