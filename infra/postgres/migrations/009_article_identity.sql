BEGIN;

CREATE TABLE dw.articles (
    id uuid PRIMARY KEY,
    title text NOT NULL,
    summary text,
    publisher text,
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE dw.article_sources (
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    source text NOT NULL,
    source_id text NOT NULL,
    url text,
    original_url text,
    canonical_url text,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source,source_id)
);
CREATE INDEX article_sources_article_idx ON dw.article_sources(article_id);
CREATE TABLE dw.article_identity_keys (
    kind text NOT NULL,
    key text NOT NULL,
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    PRIMARY KEY (kind,key)
);
CREATE TABLE dw.article_identity_conflicts (
    source text NOT NULL,
    source_id text NOT NULL,
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    other_article_id uuid NOT NULL REFERENCES dw.articles(id),
    kind text NOT NULL,
    key text NOT NULL,
    seen_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(source,source_id,kind,key)
);

-- 확인 가능한 언론사 원문 URL만 통합 근거로 사용
CREATE FUNCTION dw.canonical_article_url(raw_url text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    parsed text[];
    host text;
    path_and_query text;
    path_part text;
    query_part text;
    clean_query text;
BEGIN
    IF raw_url IS NULL OR raw_url !~* '^https?://' THEN
        RETURN NULL;
    END IF;
    parsed := regexp_match(btrim(raw_url), '^https?://([^/?#]+)([^#]*)', 'i');
    IF parsed IS NULL THEN
        RETURN NULL;
    END IF;
    host := lower(parsed[1]);
    host := regexp_replace(host, ':(80|443)$', '');
    IF host IN ('news.naver.com','search.naver.com','bigkinds.or.kr','www.bigkinds.or.kr')
        OR host = '' OR host LIKE '%@%' THEN
        RETURN NULL;
    END IF;
    path_and_query := parsed[2];
    path_part := split_part(path_and_query,'?',1);
    query_part := substring(path_and_query from '\?(.*)$');
    SELECT string_agg(part,'&' ORDER BY part) INTO clean_query
    FROM regexp_split_to_table(coalesce(query_part,''),'&') AS part
    WHERE part <> '' AND lower(split_part(part,'=',1)) !~ '^(utm_.*|fbclid|gclid)$';
    IF coalesce(path_part,'') IN ('','/') AND clean_query IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN 'https://' || host || coalesce(nullif(path_part,''),'/') ||
        CASE WHEN clean_query IS NULL THEN '' ELSE '?' || clean_query END;
END;
$$;

CREATE FUNCTION dw.resolve_article_source(
    p_source text, p_source_id text, p_url text, p_original_url text,
    p_title text, p_summary text, p_publisher text, p_published_at timestamptz
) RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE
    found_id uuid;
    keyed_id uuid;
    canonical text;
BEGIN
    canonical := CASE WHEN p_source IN ('bigkinds','naver_news')
        THEN dw.canonical_article_url(p_original_url) ELSE NULL END;
    PERFORM pg_advisory_xact_lock(hashtextextended('source:' || p_source || ':' || p_source_id,0));
    SELECT article_id INTO found_id FROM dw.article_sources
    WHERE source=p_source AND source_id=p_source_id;
    IF canonical IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(hashtextextended('url:' || canonical,0));
        SELECT article_id INTO keyed_id FROM dw.article_identity_keys
        WHERE kind='publisher_url' AND key=canonical;
    END IF;
    IF found_id IS NULL THEN
        found_id := keyed_id;
    ELSIF keyed_id IS NOT NULL AND found_id <> keyed_id THEN
        INSERT INTO dw.article_identity_conflicts
            (source,source_id,article_id,other_article_id,kind,key)
        VALUES (p_source,p_source_id,found_id,keyed_id,'publisher_url',canonical)
        ON CONFLICT(source,source_id,kind,key) DO UPDATE SET
            article_id=EXCLUDED.article_id,
            other_article_id=EXCLUDED.other_article_id,seen_at=now();
    END IF;
    IF found_id IS NULL THEN
        found_id := gen_random_uuid();
        INSERT INTO dw.articles(id,title,summary,publisher,published_at)
        VALUES (found_id,coalesce(nullif(p_title,''),p_source_id),
            nullif(p_summary,''),nullif(p_publisher,''),p_published_at);
    ELSE
        UPDATE dw.articles SET
            title=coalesce(nullif(p_title,''),title),
            summary=coalesce(nullif(p_summary,''),summary),
            publisher=coalesce(nullif(p_publisher,''),publisher),
            published_at=coalesce(p_published_at,published_at),updated_at=now()
        WHERE id=found_id;
    END IF;
    INSERT INTO dw.article_sources(article_id,source,source_id,url,original_url,canonical_url)
    VALUES (found_id,p_source,p_source_id,nullif(p_url,''),nullif(p_original_url,''),canonical)
    ON CONFLICT(source,source_id) DO UPDATE SET
        url=coalesce(EXCLUDED.url,dw.article_sources.url),
        original_url=coalesce(EXCLUDED.original_url,dw.article_sources.original_url),
        canonical_url=coalesce(EXCLUDED.canonical_url,dw.article_sources.canonical_url),
        last_seen_at=now();
    IF canonical IS NOT NULL AND (keyed_id IS NULL OR keyed_id=found_id) THEN
        INSERT INTO dw.article_identity_keys(kind,key,article_id)
        VALUES ('publisher_url',canonical,found_id) ON CONFLICT DO NOTHING;
    END IF;
    RETURN found_id;
END;
$$;

ALTER TABLE dw.news_items ADD COLUMN article_id uuid REFERENCES dw.articles(id);
ALTER TABLE dw.search_items ADD COLUMN article_id uuid REFERENCES dw.articles(id);
ALTER TABLE dw.article_contents ADD COLUMN article_id uuid REFERENCES dw.articles(id);

CREATE FUNCTION dw.assign_news_article() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.article_id := dw.resolve_article_source(
        NEW.source,NEW.source_id,NEW.data->>'url',NEW.data->>'original_url',
        NEW.data->>'title',NEW.data->>'summary',NEW.data->>'publisher',
        CASE WHEN NEW.data->>'published_on' ~ '^\d{4}-\d{2}-\d{2}$'
            THEN (NEW.data->>'published_on')::date::timestamp AT TIME ZONE 'Asia/Seoul'
            ELSE NULL END);
    RETURN NEW;
END;
$$;
CREATE TRIGGER assign_news_article BEFORE INSERT OR UPDATE OF data ON dw.news_items
FOR EACH ROW EXECUTE FUNCTION dw.assign_news_article();

CREATE FUNCTION dw.assign_search_article() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.article_id := dw.resolve_article_source(
        NEW.provider || '_' || NEW.channel,NEW.source_id,
        NEW.data->>'url',NEW.data->>'original_url',NEW.data->>'title',
        NEW.data->>'summary',NEW.data->>'container_name',
        CASE WHEN NEW.data->>'published_at' IS NOT NULL
            THEN (NEW.data->>'published_at')::timestamptz ELSE NULL END);
    RETURN NEW;
END;
$$;
CREATE TRIGGER assign_search_article BEFORE INSERT OR UPDATE OF data ON dw.search_items
FOR EACH ROW EXECUTE FUNCTION dw.assign_search_article();

CREATE FUNCTION dw.assign_content_article() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    seed jsonb;
BEGIN
    SELECT result->'seed' INTO seed FROM st.article_detail_results
    WHERE source_id=NEW.source_id AND result->'seed'->>'source'=NEW.source
    ORDER BY run_id DESC LIMIT 1;
    NEW.article_id := dw.resolve_article_source(
        NEW.source,NEW.source_id,NULL,seed->>'original_url',NEW.title,
        seed->>'summary',seed->>'publisher',
        CASE WHEN seed->>'published_on' ~ '^\d{4}-\d{2}-\d{2}$'
            THEN (seed->>'published_on')::date::timestamp AT TIME ZONE 'Asia/Seoul'
            ELSE NULL END);
    RETURN NEW;
END;
$$;
CREATE TRIGGER assign_content_article BEFORE INSERT ON dw.article_contents
FOR EACH ROW EXECUTE FUNCTION dw.assign_content_article();

UPDATE dw.news_items SET article_id=dw.resolve_article_source(
    source,source_id,data->>'url',data->>'original_url',data->>'title',
    data->>'summary',data->>'publisher',
    CASE WHEN data->>'published_on' ~ '^\d{4}-\d{2}-\d{2}$'
        THEN (data->>'published_on')::date::timestamp AT TIME ZONE 'Asia/Seoul'
        ELSE NULL END);
UPDATE dw.search_items SET article_id=dw.resolve_article_source(
    provider || '_' || channel,source_id,data->>'url',data->>'original_url',
    data->>'title',data->>'summary',data->>'container_name',
    CASE WHEN data->>'published_at' IS NOT NULL
        THEN (data->>'published_at')::timestamptz ELSE NULL END);
UPDATE dw.article_contents c SET article_id=dw.resolve_article_source(
    c.source,c.source_id,NULL,
    (SELECT r.result->'seed'->>'original_url' FROM st.article_detail_results r
        WHERE r.source_id=c.source_id AND r.result->'seed'->>'source'=c.source
        ORDER BY r.run_id DESC LIMIT 1),c.title,NULL,
    (SELECT r.result->'seed'->>'publisher' FROM st.article_detail_results r
        WHERE r.source_id=c.source_id AND r.result->'seed'->>'source'=c.source
        ORDER BY r.run_id DESC LIMIT 1),NULL);

ALTER TABLE dw.news_items ALTER COLUMN article_id SET NOT NULL;
ALTER TABLE dw.search_items ALTER COLUMN article_id SET NOT NULL;
ALTER TABLE dw.article_contents ALTER COLUMN article_id SET NOT NULL;

ALTER TABLE ops.analysis_runs ADD COLUMN article_id uuid REFERENCES dw.articles(id);
ALTER TABLE ops.analysis_queue ADD COLUMN article_id uuid REFERENCES dw.articles(id);
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='ops'
        AND table_name='analysis_runs' AND column_name='prompt_version') THEN
        UPDATE ops.analysis_runs SET catalog_snapshot =
            coalesce(catalog_snapshot,'{}'::jsonb) ||
            jsonb_build_object('legacy_prompt_version',prompt_version);
        ALTER TABLE ops.analysis_runs DROP COLUMN prompt_version;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='ops'
        AND table_name='analysis_queue' AND column_name='model') THEN
        ALTER TABLE ops.analysis_queue DROP CONSTRAINT analysis_queue_pkey;
        DELETE FROM ops.analysis_queue a USING ops.analysis_queue b
        WHERE a.ctid < b.ctid AND a.source=b.source AND a.source_id=b.source_id
            AND a.content_hash=b.content_hash;
        ALTER TABLE ops.analysis_queue DROP COLUMN model;
        ALTER TABLE ops.analysis_queue DROP COLUMN prompt_version;
        ALTER TABLE ops.analysis_queue ADD PRIMARY KEY(source,source_id,content_hash);
    END IF;
END;
$$;
ALTER TABLE ops.analysis_runs ADD COLUMN IF NOT EXISTS prompt text;
ALTER TABLE ops.analysis_runs ADD COLUMN IF NOT EXISTS prompt_hash text;
ALTER TABLE ops.analysis_attempts ADD COLUMN IF NOT EXISTS model text;
ALTER TABLE ops.analysis_attempts ADD COLUMN IF NOT EXISTS prompt text;
ALTER TABLE ops.analysis_attempts ADD COLUMN IF NOT EXISTS prompt_hash text;
UPDATE ops.analysis_runs r SET article_id=s.article_id FROM dw.article_sources s
WHERE s.source=r.source AND s.source_id=r.source_id;
UPDATE ops.analysis_queue q SET article_id=s.article_id FROM dw.article_sources s
WHERE s.source=q.source AND s.source_id=q.source_id;
ALTER TABLE ops.analysis_runs ALTER COLUMN article_id SET NOT NULL;
ALTER TABLE ops.analysis_queue ALTER COLUMN article_id SET NOT NULL;

CREATE TABLE ops.analysis_response_cache (
    cache_key text PRIMARY KEY,
    prompt text NOT NULL,
    llm_string text NOT NULL,
    generations jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE ops.analysis_queue_keys (
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    content_hash text NOT NULL,
    source text NOT NULL,
    source_id text NOT NULL,
    PRIMARY KEY(article_id,content_hash)
);
INSERT INTO ops.analysis_queue_keys(article_id,content_hash,source,source_id)
SELECT DISTINCT ON(article_id,content_hash)
    article_id,content_hash,source,source_id FROM ops.analysis_queue
ORDER BY article_id,content_hash,created_at,source,source_id;

CREATE OR REPLACE FUNCTION ops.enqueue_article_analysis() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source NOT IN ('bigkinds','naver_news') THEN
        RETURN NEW;
    END IF;
    INSERT INTO ops.analysis_queue_keys(article_id,content_hash,source,source_id)
    VALUES (NEW.article_id,NEW.content_hash,NEW.source,NEW.source_id)
    ON CONFLICT DO NOTHING;
    IF FOUND THEN
        INSERT INTO ops.analysis_queue(article_id,source,source_id,content_hash)
        VALUES (NEW.article_id,NEW.source,NEW.source_id,NEW.content_hash)
        ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;

ALTER TABLE ops.analysis_article_topics ADD COLUMN article_id uuid REFERENCES dw.articles(id);
ALTER TABLE ops.analysis_article_versions ADD COLUMN article_id uuid REFERENCES dw.articles(id);
ALTER TABLE ops.analysis_article_topic_history ADD COLUMN article_id uuid REFERENCES dw.articles(id);
ALTER TABLE ops.analysis_topic_evidence ADD COLUMN article_id uuid REFERENCES dw.articles(id);
UPDATE ops.analysis_article_topics t SET article_id=s.article_id FROM dw.article_sources s
WHERE s.source=t.source AND s.source_id=t.source_id;
UPDATE ops.analysis_article_versions v SET article_id=s.article_id FROM dw.article_sources s
WHERE s.source=v.source AND s.source_id=v.source_id;
UPDATE ops.analysis_article_topic_history h SET article_id=s.article_id FROM dw.article_sources s
WHERE s.source=h.source AND s.source_id=h.source_id;
UPDATE ops.analysis_topic_evidence e SET article_id=s.article_id FROM dw.article_sources s
WHERE s.source=e.source AND s.source_id=e.source_id;
CREATE INDEX analysis_article_topics_article_idx ON ops.analysis_article_topics(article_id);
CREATE INDEX analysis_topic_evidence_article_idx ON ops.analysis_topic_evidence(article_id);

-- 원본 저장 시각을 통합 출처와 기사에 반영
WITH observed AS (
    SELECT source,source_id,first_seen_at AS first_seen,last_seen_at AS last_seen
    FROM (
        SELECT source,source_id,first_seen_at,updated_at AS last_seen_at
        FROM dw.news_items
        UNION ALL
        SELECT provider || '_' || channel,source_id,first_seen_at,last_seen_at
        FROM dw.search_items
        UNION ALL
        SELECT source,source_id,created_at,created_at FROM dw.article_contents
    ) records
), source_times AS (
    SELECT source,source_id,min(first_seen) AS first_seen,max(last_seen) AS last_seen
    FROM observed GROUP BY source,source_id
)
UPDATE dw.article_sources s SET first_seen_at=t.first_seen,last_seen_at=t.last_seen
FROM source_times t WHERE s.source=t.source AND s.source_id=t.source_id;

WITH article_times AS (
    SELECT article_id,min(first_seen_at) AS first_seen,max(last_seen_at) AS last_seen
    FROM dw.article_sources GROUP BY article_id
)
UPDATE dw.articles a SET created_at=t.first_seen,updated_at=t.last_seen
FROM article_times t WHERE a.id=t.article_id;

COMMIT;
