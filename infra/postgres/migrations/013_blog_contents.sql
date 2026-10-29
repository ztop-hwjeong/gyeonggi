BEGIN;

CREATE TABLE ops.blog_detail_runs (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    summary jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE st.blog_detail_results (
    run_id uuid NOT NULL REFERENCES ops.blog_detail_runs(id),
    source text NOT NULL,
    source_id text NOT NULL,
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, source, source_id)
);
CREATE INDEX blog_detail_results_source_idx
    ON st.blog_detail_results(source, source_id, created_at DESC);

CREATE TABLE st.blog_responses (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    run_id uuid NOT NULL REFERENCES ops.blog_detail_runs(id),
    source text NOT NULL,
    source_id text NOT NULL,
    stage text NOT NULL,
    seed jsonb NOT NULL,
    metadata jsonb NOT NULL,
    raw_object jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX blog_responses_source_idx
    ON st.blog_responses(source, source_id, created_at DESC);

CREATE TABLE dw.blog_contents (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    blog_post_id uuid NOT NULL REFERENCES dw.blog_posts(id),
    source text NOT NULL,
    source_id text NOT NULL,
    content_hash text NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    stage text NOT NULL,
    run_id uuid NOT NULL REFERENCES ops.blog_detail_runs(id),
    provenance jsonb NOT NULL,
    original_published_on date,
    original_published_at timestamptz,
    original_modified_on date,
    original_modified_at timestamptz,
    collected_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, source_id, content_hash)
);
CREATE INDEX blog_contents_post_latest_idx
    ON dw.blog_contents(blog_post_id, created_at DESC, id DESC);

COMMIT;
