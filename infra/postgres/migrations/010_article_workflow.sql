BEGIN;

CREATE TABLE ops.analysis_targets (
    id uuid PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('policy','regular','current_issue','leader_message')),
    name text NOT NULL CHECK (length(trim(name)) > 0),
    description text NOT NULL DEFAULT '',
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    archived_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ops.article_filter_rules (
    id uuid PRIMARY KEY,
    target_id uuid REFERENCES ops.analysis_targets(id),
    name text NOT NULL CHECK (length(trim(name)) > 0),
    priority integer NOT NULL,
    decision text NOT NULL CHECK (decision IN ('include','exclude')),
    conditions jsonb NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX article_filter_rules_order_idx ON ops.article_filter_rules(target_id,priority DESC,id)
    WHERE enabled;
CREATE TABLE ops.article_filter_rule_versions (
    rule_id uuid NOT NULL REFERENCES ops.article_filter_rules(id),
    version integer NOT NULL,
    definition jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (rule_id,version)
);

CREATE TABLE ops.article_inclusions (
    article_id uuid PRIMARY KEY REFERENCES dw.articles(id),
    decision text NOT NULL CHECK (decision IN ('include','exclude')),
    origin text NOT NULL CHECK (origin IN ('auto','manual')),
    reason text NOT NULL,
    matched_terms jsonb NOT NULL DEFAULT '[]'::jsonb,
    rule_id uuid,
    rule_version integer,
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (rule_id,rule_version)
        REFERENCES ops.article_filter_rule_versions(rule_id,version)
);
CREATE TABLE ops.article_target_links (
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    target_id uuid NOT NULL REFERENCES ops.analysis_targets(id),
    decision text NOT NULL CHECK (decision IN ('include','exclude')),
    origin text NOT NULL CHECK (origin IN ('auto','manual')),
    reason text NOT NULL,
    matched_terms jsonb NOT NULL DEFAULT '[]'::jsonb,
    rule_id uuid,
    rule_version integer,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (article_id,target_id),
    FOREIGN KEY (rule_id,rule_version)
        REFERENCES ops.article_filter_rule_versions(rule_id,version)
);
CREATE INDEX article_target_links_target_idx ON ops.article_target_links(target_id,decision,article_id);

CREATE TABLE ops.article_decision_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    target_id uuid REFERENCES ops.analysis_targets(id),
    previous_decision text,
    decision text CHECK (decision IN ('include','exclude')),
    action text NOT NULL CHECK (action IN ('evaluate','override','release')),
    origin text NOT NULL CHECK (origin IN ('auto','manual')),
    reason text NOT NULL,
    matched_terms jsonb NOT NULL DEFAULT '[]'::jsonb,
    rule_id uuid,
    rule_version integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (rule_id,rule_version)
        REFERENCES ops.article_filter_rule_versions(rule_id,version)
);
CREATE INDEX article_decision_history_article_idx
    ON ops.article_decision_history(article_id,created_at DESC,id DESC);

COMMIT;
