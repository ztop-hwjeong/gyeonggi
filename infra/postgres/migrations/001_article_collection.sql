BEGIN;

CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS st;
CREATE SCHEMA IF NOT EXISTS dw;

CREATE TABLE IF NOT EXISTS ops.article_detail_runs (
    id uuid PRIMARY KEY,
    summary jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS st.article_responses (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES ops.article_detail_runs(id),
    source_id text NOT NULL,
    stage text NOT NULL,
    seed jsonb NOT NULL,
    metadata jsonb NOT NULL,
    raw_object jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS article_responses_run_id_idx ON st.article_responses(run_id);
CREATE TABLE IF NOT EXISTS st.article_detail_attempts (
    run_id uuid NOT NULL REFERENCES ops.article_detail_runs(id),
    source_id text NOT NULL,
    stage text NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY (run_id, source_id, stage)
);
CREATE TABLE IF NOT EXISTS st.article_detail_results (
    run_id uuid NOT NULL REFERENCES ops.article_detail_runs(id),
    source_id text NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY (run_id, source_id)
);
CREATE TABLE IF NOT EXISTS dw.article_contents (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source text NOT NULL,
    source_id text NOT NULL,
    content_hash text NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    stage text NOT NULL,
    run_id uuid NOT NULL REFERENCES ops.article_detail_runs(id),
    provenance jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, source_id, content_hash)
);
CREATE TABLE IF NOT EXISTS ops.publisher_adaptive_profiles (
    scope text NOT NULL,
    identifier text NOT NULL,
    properties jsonb NOT NULL,
    context jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, identifier)
);
CREATE TABLE IF NOT EXISTS ops.publisher_adaptive_history (
    id uuid PRIMARY KEY,
    scope text NOT NULL,
    identifier text NOT NULL,
    properties jsonb NOT NULL,
    context jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS publisher_adaptive_history_scope_idx
    ON ops.publisher_adaptive_history(scope, created_at);

COMMIT;
