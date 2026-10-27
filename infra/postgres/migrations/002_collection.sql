BEGIN;

CREATE TABLE ops.search_streams (
    stream_key text PRIMARY KEY,
    provider text NOT NULL,
    channel text NOT NULL,
    query text NOT NULL,
    cursor jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE ops.search_runs (
    id uuid PRIMARY KEY,
    stream_key text NOT NULL REFERENCES ops.search_streams(stream_key),
    summary jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX search_runs_created_at_idx ON ops.search_runs(created_at);
CREATE INDEX search_runs_stream_key_idx ON ops.search_runs(stream_key, created_at DESC);
CREATE TABLE st.search_responses (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES ops.search_runs(id),
    start_position integer NOT NULL,
    status_code integer NOT NULL,
    metadata jsonb NOT NULL,
    raw_object jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX search_responses_run_id_idx ON st.search_responses(run_id);
CREATE TABLE dw.search_items (
    provider text NOT NULL,
    channel text NOT NULL,
    source_id text NOT NULL,
    content_hash text NOT NULL,
    data jsonb NOT NULL,
    article_id uuid REFERENCES dw.articles(id),
    blog_post_id uuid REFERENCES dw.blog_posts(id),
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, channel, source_id),
    CHECK ((article_id IS NULL) <> (blog_post_id IS NULL))
);
CREATE TABLE st.search_run_items (
    run_id uuid NOT NULL REFERENCES ops.search_runs(id),
    source_id text NOT NULL,
    response_id uuid NOT NULL REFERENCES st.search_responses(id),
    data jsonb NOT NULL,
    is_new boolean NOT NULL,
    is_updated boolean NOT NULL,
    PRIMARY KEY (run_id, source_id)
);
CREATE TABLE ops.api_daily_usage (
    provider text NOT NULL,
    day date NOT NULL,
    calls integer NOT NULL,
    PRIMARY KEY (provider, day)
);
CREATE TABLE ops.api_request_pauses (
    provider text PRIMARY KEY,
    retry_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS article_detail_results_source_idx
    ON st.article_detail_results (source_id, (result->'seed'->>'source'), run_id);

CREATE TABLE ops.collection_rules (
    id uuid PRIMARY KEY,
    version integer NOT NULL CHECK (version > 0),
    definition jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE ops.collection_rule_versions (
    rule_id uuid NOT NULL REFERENCES ops.collection_rules(id),
    version integer NOT NULL,
    definition jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (rule_id, version)
);
CREATE TABLE ops.collection_requests (
    id uuid PRIMARY KEY,
    rule_id uuid REFERENCES ops.collection_rules(id),
    rule_version integer,
    source text NOT NULL,
    mode text NOT NULL CHECK (mode IN ('preview', 'incremental', 'backfill')),
    definition jsonb NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL CHECK (end_date >= start_date),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','submitted','running','completed','partial','failed','cancelled','cancelling')),
    flow_run_id uuid UNIQUE,
    summary jsonb NOT NULL DEFAULT '{}',
    error text,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (rule_id, rule_version) REFERENCES ops.collection_rule_versions(rule_id, version)
);
CREATE INDEX collection_requests_pending_idx ON ops.collection_requests(created_at)
    WHERE status IN ('queued','submitted','running','cancelling');
CREATE INDEX collection_requests_rule_idx ON ops.collection_requests(rule_id, created_at DESC);
CREATE TABLE st.collection_request_items (
    request_id uuid NOT NULL REFERENCES ops.collection_requests(id),
    source_id text NOT NULL,
    data jsonb NOT NULL,
    PRIMARY KEY (request_id, source_id)
);
CREATE TABLE dw.news_items (
    source text NOT NULL,
    source_id text NOT NULL,
    data jsonb NOT NULL,
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_id)
);

CREATE TABLE st.collection_request_responses (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES ops.collection_requests(id),
    page_number integer NOT NULL,
    metadata jsonb NOT NULL,
    raw_object jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX collection_request_responses_request_idx
    ON st.collection_request_responses(request_id, page_number);

COMMIT;
