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
CREATE TABLE ops.analysis_topic_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    topic_id text NOT NULL REFERENCES ops.analysis_topics(id),
    action text NOT NULL CHECK (action IN ('update','merge','archive')),
    detail jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE ops.material_tags (
    material_id uuid NOT NULL REFERENCES dw.material_keys(id),
    topic_id text NOT NULL REFERENCES ops.analysis_topics(id),
    origin text NOT NULL CHECK (origin IN ('ai','manual_include','manual_exclude')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (material_id, topic_id)
);
CREATE INDEX material_tags_topic_idx ON ops.material_tags(topic_id, material_id);
CREATE TABLE ops.analysis_article_versions (
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    content_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (article_id, content_hash)
);
CREATE TABLE ops.analysis_article_topic_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    article_id uuid NOT NULL REFERENCES dw.articles(id),
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
    article_id uuid NOT NULL REFERENCES dw.articles(id),
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
CREATE TABLE ops.analysis_response_cache (
    cache_key text PRIMARY KEY,
    prompt text NOT NULL,
    llm_string text NOT NULL,
    generations jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
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

CREATE TABLE ops.analysis_queue (
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    source text NOT NULL,
    source_id text NOT NULL,
    content_hash text NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','submitted','running','completed','failed')),
    flow_run_id uuid,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source,source_id,content_hash)
);
CREATE TABLE ops.analysis_queue_keys (
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    content_hash text NOT NULL,
    source text NOT NULL,
    source_id text NOT NULL,
    PRIMARY KEY (article_id, content_hash)
);
CREATE FUNCTION ops.enqueue_article_analysis() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO ops.analysis_queue_keys(article_id,content_hash,source,source_id)
    VALUES (NEW.article_id,NEW.content_hash,NEW.source,NEW.source_id)
    ON CONFLICT DO NOTHING;
    IF FOUND THEN
        INSERT INTO ops.analysis_queue(article_id,source,source_id,content_hash)
        VALUES (NEW.article_id,NEW.source,NEW.source_id,NEW.content_hash)
        ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER enqueue_article_analysis
AFTER INSERT ON dw.article_contents
FOR EACH ROW EXECUTE FUNCTION ops.enqueue_article_analysis();

COMMIT;
