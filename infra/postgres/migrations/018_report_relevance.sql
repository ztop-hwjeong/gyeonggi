BEGIN;

ALTER TABLE ops.analysis_reports
    ADD COLUMN relevance_criteria text NOT NULL DEFAULT '';

UPDATE ops.analysis_reports report
SET relevance_criteria = concat_ws(E'\n', target.name, target.description)
FROM ops.analysis_targets target
WHERE target.id = report.target_id
  AND report.relevance_criteria = '';

CREATE OR REPLACE FUNCTION ops.ensure_default_analysis_report() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.kind IN ('regular', 'current_issue') THEN
        INSERT INTO ops.analysis_reports(
            id, target_id, target_kind, title, description, relevance_criteria, is_default
        ) VALUES (
            uuidv7(), NEW.id, NEW.kind, NEW.name, NEW.description,
            concat_ws(E'\n', NEW.name, NEW.description), true
        ) ON CONFLICT (target_id) WHERE is_default DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE ops.report_relevance_runs (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    batch_id uuid NOT NULL,
    report_id uuid NOT NULL REFERENCES ops.analysis_reports(id) ON DELETE CASCADE,
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    content_id bigint NOT NULL REFERENCES dw.article_contents(id),
    content_hash text NOT NULL,
    title text NOT NULL,
    criteria text NOT NULL,
    criteria_hash text NOT NULL,
    model text NOT NULL CHECK (model = 'gpt-6-luna'),
    prompt text,
    prompt_hash text,
    status text NOT NULL CHECK (status IN ('queued','submitted','running','completed','failed')),
    relevance text CHECK (relevance IN ('related','unrelated','uncertain')),
    reason text,
    evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
    usage jsonb NOT NULL DEFAULT '{}'::jsonb,
    error text,
    flow_run_id uuid,
    submission_attempts integer NOT NULL DEFAULT 0,
    lease_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX report_relevance_runs_active_unique_idx
    ON ops.report_relevance_runs(report_id, article_id, content_hash, criteria_hash)
    WHERE status IN ('queued','submitted','running');
CREATE INDEX report_relevance_runs_current_lookup_idx
    ON ops.report_relevance_runs(report_id, article_id, created_at DESC, id DESC);
CREATE INDEX report_relevance_runs_batch_idx ON ops.report_relevance_runs(batch_id, created_at, id);

COMMIT;
