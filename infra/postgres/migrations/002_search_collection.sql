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
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, channel, source_id)
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

COMMIT;
