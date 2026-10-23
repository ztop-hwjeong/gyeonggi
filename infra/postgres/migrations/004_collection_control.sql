BEGIN;

CREATE TABLE ops.collection_rules (
    id uuid PRIMARY KEY,
    version integer NOT NULL CHECK (version > 0),
    definition jsonb NOT NULL,
    next_run_at timestamptz NOT NULL DEFAULT now(),
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
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_id)
);

COMMIT;
