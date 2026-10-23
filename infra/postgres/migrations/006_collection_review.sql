BEGIN;

ALTER TABLE ops.collection_requests ADD COLUMN reviewed_at timestamptz;
CREATE INDEX collection_requests_unreviewed_idx
    ON ops.collection_requests (created_at DESC)
    WHERE status IN ('failed', 'partial') AND reviewed_at IS NULL;

COMMIT;
