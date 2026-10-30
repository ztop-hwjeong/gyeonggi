BEGIN;

CREATE TABLE ops.analysis_reports (
    id uuid PRIMARY KEY,
    target_id uuid NOT NULL REFERENCES ops.analysis_targets(id),
    target_kind text NOT NULL CHECK (target_kind IN ('regular', 'current_issue')),
    title text NOT NULL CHECK (length(btrim(title)) > 0),
    description text NOT NULL DEFAULT '',
    keywords_override jsonb,
    is_default boolean NOT NULL DEFAULT false,
    start_at timestamptz,
    end_at timestamptz,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (keywords_override IS NULL OR jsonb_typeof(keywords_override) = 'array'),
    CHECK (start_at IS NULL OR end_at IS NULL OR start_at < end_at)
);
CREATE UNIQUE INDEX analysis_reports_one_default_per_target_idx
    ON ops.analysis_reports(target_id) WHERE is_default;
CREATE INDEX analysis_reports_target_idx ON ops.analysis_reports(target_id, created_at, id);

CREATE TABLE ops.analysis_report_decisions (
    report_id uuid NOT NULL REFERENCES ops.analysis_reports(id) ON DELETE CASCADE,
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    decision text NOT NULL CHECK (decision IN ('include', 'exclude')),
    reason text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (report_id, article_id)
);
CREATE INDEX analysis_report_decisions_article_idx
    ON ops.analysis_report_decisions(article_id, report_id);

CREATE TABLE ops.analysis_report_decision_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id uuid NOT NULL REFERENCES ops.analysis_reports(id) ON DELETE CASCADE,
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    previous_decision text CHECK (previous_decision IN ('include', 'exclude')),
    action text NOT NULL CHECK (action IN ('include', 'exclude', 'release')),
    reason text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX analysis_report_decision_history_report_idx
    ON ops.analysis_report_decision_history(report_id, article_id, created_at DESC, id DESC);

CREATE FUNCTION ops.ensure_default_analysis_report() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.kind IN ('regular', 'current_issue') THEN
        INSERT INTO ops.analysis_reports(id, target_id, target_kind, title, description, is_default)
        VALUES (uuidv7(), NEW.id, NEW.kind, NEW.name, NEW.description, true)
        ON CONFLICT (target_id) WHERE is_default DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER ensure_default_analysis_report
AFTER INSERT ON ops.analysis_targets
FOR EACH ROW EXECUTE FUNCTION ops.ensure_default_analysis_report();

INSERT INTO ops.analysis_reports(id, target_id, target_kind, title, description, is_default)
SELECT uuidv7(), id, kind, name, description, true
FROM ops.analysis_targets
WHERE kind IN ('regular', 'current_issue')
  AND archived_at IS NULL
ON CONFLICT (target_id) WHERE is_default DO NOTHING;

COMMIT;
