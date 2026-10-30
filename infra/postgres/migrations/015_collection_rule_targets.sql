BEGIN;

CREATE TABLE ops.collection_rule_targets (
    rule_id uuid NOT NULL REFERENCES ops.collection_rules(id),
    target_id uuid NOT NULL REFERENCES ops.analysis_targets(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (rule_id, target_id)
);
CREATE INDEX collection_rule_targets_target_idx
    ON ops.collection_rule_targets(target_id, rule_id);
CREATE INDEX collection_request_items_source_idx
    ON st.collection_request_items(source_id, request_id);

COMMIT;
