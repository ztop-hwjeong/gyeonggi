BEGIN;
CREATE TABLE st.collection_request_responses (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES ops.collection_requests(id),
    page_number integer NOT NULL,
    metadata jsonb NOT NULL,
    raw_object jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX collection_request_responses_request_idx
    ON st.collection_request_responses(request_id, page_number);
COMMIT;
