BEGIN;

CREATE TABLE ops.tag_folders (
    id uuid PRIMARY KEY,
    parent_id uuid REFERENCES ops.tag_folders(id),
    name text NOT NULL CHECK (length(trim(name)) > 0),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (parent_id IS NULL OR parent_id <> id)
);
CREATE INDEX tag_folders_parent_idx ON ops.tag_folders(parent_id,name,id);

CREATE TABLE ops.folder_tags (
    folder_id uuid NOT NULL REFERENCES ops.tag_folders(id) ON DELETE CASCADE,
    tag_id text NOT NULL REFERENCES ops.analysis_topics(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (folder_id,tag_id)
);
CREATE INDEX folder_tags_tag_idx ON ops.folder_tags(tag_id,folder_id);

COMMIT;
