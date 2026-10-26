BEGIN;

CREATE TABLE ops.analysis_queue (
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
CREATE FUNCTION ops.enqueue_article_analysis() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO ops.analysis_queue(source,source_id,content_hash)
    VALUES (NEW.source,NEW.source_id,NEW.content_hash)
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END;
$$;
CREATE TRIGGER enqueue_article_analysis
AFTER INSERT ON dw.article_contents
FOR EACH ROW EXECUTE FUNCTION ops.enqueue_article_analysis();

COMMIT;
