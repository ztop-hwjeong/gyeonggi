BEGIN;

CREATE TABLE ops.article_browser_policies (
    domain text PRIMARY KEY,
    browser_mode text NOT NULL CHECK (browser_mode IN ('http_only', 'rendered_after_http_failure')),
    reason text NOT NULL,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
