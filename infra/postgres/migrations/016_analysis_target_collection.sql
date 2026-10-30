BEGIN;

ALTER TABLE ops.analysis_targets
    ADD COLUMN collection_enabled boolean NOT NULL DEFAULT true;

COMMIT;
