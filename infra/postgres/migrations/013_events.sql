BEGIN;

CREATE TABLE ops.events (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(trim(name)) > 0),
    occurred_at timestamptz NOT NULL,
    version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX events_occurred_at_idx ON ops.events(occurred_at DESC,id);

CREATE TABLE ops.event_targets (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id uuid NOT NULL REFERENCES ops.events(id) ON DELETE CASCADE,
    tag_id text REFERENCES ops.analysis_topics(id) ON DELETE RESTRICT,
    folder_id uuid REFERENCES ops.tag_folders(id) ON DELETE RESTRICT,
    CHECK ((tag_id IS NULL) <> (folder_id IS NULL)),
    UNIQUE (event_id,tag_id),
    UNIQUE (event_id,folder_id)
);
CREATE INDEX event_targets_tag_idx ON ops.event_targets(tag_id,event_id);
CREATE INDEX event_targets_folder_idx ON ops.event_targets(folder_id,event_id);

COMMIT;
