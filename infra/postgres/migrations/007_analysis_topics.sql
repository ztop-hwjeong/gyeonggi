BEGIN;

CREATE TABLE ops.analysis_topics (
    id text PRIMARY KEY CHECK (id ~ '^[a-z][a-z0-9-]{0,39}$'),
    name text NOT NULL,
    description text NOT NULL,
    synonyms jsonb NOT NULL DEFAULT '[]',
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    merged_into text REFERENCES ops.analysis_topics(id),
    archived_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE ops.analysis_topic_labels (
    id text NOT NULL REFERENCES ops.analysis_topics(id),
    normalized_name text PRIMARY KEY,
    is_canonical boolean NOT NULL
);
CREATE TABLE ops.analysis_topic_candidates (
    id uuid PRIMARY KEY,
    normalized_name text NOT NULL UNIQUE,
    name text NOT NULL,
    description text NOT NULL,
    promoted_topic_id text REFERENCES ops.analysis_topics(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE ops.analysis_topic_evidence (
    candidate_id uuid NOT NULL REFERENCES ops.analysis_topic_candidates(id),
    source text NOT NULL,
    source_id text NOT NULL,
    publisher text NOT NULL,
    quote text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (candidate_id, source, source_id)
);
CREATE TABLE ops.analysis_topic_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    topic_id text NOT NULL REFERENCES ops.analysis_topics(id),
    action text NOT NULL CHECK (action IN ('update','merge','archive')),
    detail jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE ops.analysis_article_topics (
    source text NOT NULL,
    source_id text NOT NULL,
    topic_id text NOT NULL REFERENCES ops.analysis_topics(id),
    origin text NOT NULL CHECK (origin IN ('ai','manual_include','manual_exclude')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_id, topic_id)
);
CREATE TABLE ops.analysis_article_versions (
    source text NOT NULL,
    source_id text NOT NULL,
    content_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_id, content_hash)
);
CREATE TABLE ops.analysis_article_topic_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source text NOT NULL,
    source_id text NOT NULL,
    content_hash text,
    original_topic_id text NOT NULL,
    resulting_topic_id text,
    previous_origin text,
    resulting_origin text,
    action text NOT NULL CHECK (action IN ('override','release','merge')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE ops.analysis_runs (
    id uuid PRIMARY KEY,
    source text NOT NULL,
    source_id text NOT NULL,
    content_hash text NOT NULL,
    model text NOT NULL,
    prompt text,
    prompt_hash text,
    status text NOT NULL CHECK (status IN ('queued','running','completed','failed')),
    catalog_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    model_draft jsonb,
    applied_result jsonb,
    usage jsonb NOT NULL DEFAULT '{}'::jsonb,
    error text,
    lease_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE ops.analysis_attempts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES ops.analysis_runs(id),
    prefect_flow_run_id uuid,
    prefect_task_run_id uuid,
    model text,
    prompt text,
    prompt_hash text,
    status text NOT NULL CHECK (status IN ('running','completed','failed')),
    error text,
    usage jsonb NOT NULL DEFAULT '{}'::jsonb,
    model_draft jsonb,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
COMMIT;
