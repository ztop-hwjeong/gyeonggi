BEGIN;

ALTER TABLE dw.articles RENAME TO materials;
ALTER TABLE dw.article_sources RENAME TO material_sources;
ALTER TABLE dw.material_sources RENAME COLUMN article_id TO material_id;
ALTER TABLE dw.article_identity_keys RENAME TO material_identity_keys;
ALTER TABLE dw.material_identity_keys RENAME COLUMN article_id TO material_id;
ALTER TABLE dw.article_identity_conflicts RENAME TO material_identity_conflicts;
ALTER TABLE dw.material_identity_conflicts RENAME COLUMN article_id TO material_id;
ALTER TABLE dw.material_identity_conflicts RENAME COLUMN other_article_id TO other_material_id;
ALTER TABLE dw.news_items RENAME COLUMN article_id TO material_id;
ALTER TABLE dw.search_items RENAME COLUMN article_id TO material_id;
ALTER TABLE dw.article_contents RENAME COLUMN article_id TO material_id;

ALTER TABLE dw.materials ADD COLUMN kind text;
ALTER TABLE dw.materials ADD COLUMN cafe_name text;
ALTER TABLE dw.materials ADD COLUMN cafe_url text;
ALTER TABLE dw.materials ADD COLUMN blog_name text;
ALTER TABLE dw.materials ADD COLUMN blog_url text;

UPDATE dw.materials m SET kind = CASE
    WHEN s.source IN ('bigkinds','naver_news') THEN 'news'
    WHEN s.source = 'naver_cafearticle' THEN 'cafe'
    WHEN s.source = 'naver_blog' THEN 'blog'
END
FROM dw.material_sources s WHERE s.material_id=m.id;
ALTER TABLE dw.materials ALTER COLUMN kind SET NOT NULL;
ALTER TABLE dw.materials ADD CONSTRAINT materials_kind_check CHECK (kind IN ('news','cafe','blog'));

UPDATE dw.materials m SET cafe_name = c.name, cafe_url = c.url
FROM (
    SELECT material_id, max(coalesce(nullif(data->>'container_name',''),
        nullif(data->>'cafename',''),nullif(data->>'publisher',''))) AS name,
        max(nullif(data->>'cafe_url','')) AS url
    FROM dw.search_items WHERE provider='naver' AND channel='cafearticle'
    GROUP BY material_id
) c WHERE m.id=c.material_id AND m.kind='cafe';
UPDATE dw.materials m SET blog_name = b.name, blog_url = b.url
FROM (
    SELECT material_id, max(coalesce(nullif(data->>'blog_name',''),
        nullif(data->>'bloggername',''))) AS name,
        max(coalesce(nullif(data->>'blog_url',''),
        nullif(data->>'bloggerlink',''))) AS url
    FROM dw.search_items WHERE provider='naver' AND channel='blog'
    GROUP BY material_id
) b WHERE m.id=b.material_id AND m.kind='blog';
UPDATE dw.materials m SET published_at=
    (s.data->>'published_on')::date::timestamp AT TIME ZONE 'Asia/Seoul'
FROM dw.search_items s WHERE s.material_id=m.id AND s.channel='blog'
    AND s.data->>'published_on' ~ '^\d{4}-\d{2}-\d{2}$';
UPDATE dw.materials SET publisher=NULL WHERE kind<>'news';
ALTER TABLE dw.materials ADD CONSTRAINT materials_metadata_kind_check CHECK (
    (kind='news' OR publisher IS NULL) AND
    (kind='cafe' OR (cafe_name IS NULL AND cafe_url IS NULL)) AND
    (kind='blog' OR (blog_name IS NULL AND blog_url IS NULL))
);

WITH observed AS (
    SELECT source,source_id,first_seen_at AS first_seen,updated_at AS last_seen
    FROM dw.news_items
    UNION ALL
    SELECT provider || '_' || channel,source_id,first_seen_at,last_seen_at
    FROM dw.search_items
    UNION ALL
    SELECT source,source_id,created_at,created_at FROM dw.article_contents
), source_times AS (
    SELECT source,source_id,min(first_seen) AS first_seen,max(last_seen) AS last_seen
    FROM observed GROUP BY source,source_id
)
UPDATE dw.material_sources s SET first_seen_at=t.first_seen,last_seen_at=t.last_seen
FROM source_times t WHERE s.source=t.source AND s.source_id=t.source_id;
WITH material_times AS (
    SELECT material_id,min(first_seen_at) AS first_seen,max(last_seen_at) AS last_seen
    FROM dw.material_sources GROUP BY material_id
)
UPDATE dw.materials m SET created_at=t.first_seen,updated_at=t.last_seen
FROM material_times t WHERE m.id=t.material_id;

CREATE FUNCTION dw.resolve_material_source(
    p_source text, p_source_id text, p_url text, p_original_url text,
    p_title text, p_summary text, p_publisher text, p_published_at timestamptz,
    p_cafe_name text, p_cafe_url text, p_blog_name text, p_blog_url text
) RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE
    material_kind text;
    found_id uuid;
    keyed_id uuid;
    canonical text;
BEGIN
    material_kind := CASE
        WHEN p_source IN ('bigkinds','naver_news') THEN 'news'
        WHEN p_source='naver_cafearticle' THEN 'cafe'
        WHEN p_source='naver_blog' THEN 'blog'
    END;
    IF material_kind IS NULL THEN
        RAISE EXCEPTION 'Unsupported material source: %',p_source;
    END IF;
    canonical := CASE WHEN material_kind='news'
        THEN dw.canonical_article_url(p_original_url) ELSE NULL END;
    PERFORM pg_advisory_xact_lock(hashtextextended('source:' || p_source || ':' || p_source_id,0));
    SELECT material_id INTO found_id FROM dw.material_sources
    WHERE source=p_source AND source_id=p_source_id;
    IF canonical IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(hashtextextended('url:' || canonical,0));
        SELECT material_id INTO keyed_id FROM dw.material_identity_keys
        WHERE kind='publisher_url' AND key=canonical;
    END IF;
    IF found_id IS NULL THEN
        found_id := keyed_id;
    ELSIF keyed_id IS NOT NULL AND found_id <> keyed_id THEN
        INSERT INTO dw.material_identity_conflicts
            (source,source_id,material_id,other_material_id,kind,key)
        VALUES (p_source,p_source_id,found_id,keyed_id,'publisher_url',canonical)
        ON CONFLICT(source,source_id,kind,key) DO UPDATE SET
            material_id=EXCLUDED.material_id,
            other_material_id=EXCLUDED.other_material_id,seen_at=now();
    END IF;
    IF found_id IS NULL THEN
        found_id := gen_random_uuid();
        INSERT INTO dw.materials(
            id,kind,title,summary,publisher,published_at,cafe_name,cafe_url,blog_name,blog_url
        ) VALUES (
            found_id,material_kind,coalesce(nullif(p_title,''),p_source_id),
            nullif(p_summary,''),
            CASE WHEN material_kind='news' THEN nullif(p_publisher,'') END,
            p_published_at,
            CASE WHEN material_kind='cafe' THEN nullif(p_cafe_name,'') END,
            CASE WHEN material_kind='cafe' THEN nullif(p_cafe_url,'') END,
            CASE WHEN material_kind='blog' THEN nullif(p_blog_name,'') END,
            CASE WHEN material_kind='blog' THEN nullif(p_blog_url,'') END
        );
    ELSE
        UPDATE dw.materials SET
            title=coalesce(nullif(p_title,''),title),
            summary=coalesce(nullif(p_summary,''),summary),
            publisher=CASE WHEN kind='news' THEN coalesce(nullif(p_publisher,''),publisher) END,
            cafe_name=CASE WHEN kind='cafe' THEN coalesce(nullif(p_cafe_name,''),cafe_name) END,
            cafe_url=CASE WHEN kind='cafe' THEN coalesce(nullif(p_cafe_url,''),cafe_url) END,
            blog_name=CASE WHEN kind='blog' THEN coalesce(nullif(p_blog_name,''),blog_name) END,
            blog_url=CASE WHEN kind='blog' THEN coalesce(nullif(p_blog_url,''),blog_url) END,
            published_at=coalesce(p_published_at,published_at),updated_at=now()
        WHERE id=found_id AND kind=material_kind;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Material source kind conflict: %, %',p_source,p_source_id;
        END IF;
    END IF;
    INSERT INTO dw.material_sources(material_id,source,source_id,url,original_url,canonical_url)
    VALUES (found_id,p_source,p_source_id,nullif(p_url,''),nullif(p_original_url,''),canonical)
    ON CONFLICT(source,source_id) DO UPDATE SET
        url=coalesce(EXCLUDED.url,dw.material_sources.url),
        original_url=coalesce(EXCLUDED.original_url,dw.material_sources.original_url),
        canonical_url=coalesce(EXCLUDED.canonical_url,dw.material_sources.canonical_url),
        last_seen_at=now();
    IF canonical IS NOT NULL AND (keyed_id IS NULL OR keyed_id=found_id) THEN
        INSERT INTO dw.material_identity_keys(kind,key,material_id)
        VALUES ('publisher_url',canonical,found_id) ON CONFLICT DO NOTHING;
    END IF;
    RETURN found_id;
END;
$$;

CREATE FUNCTION dw.assign_news_material() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.material_id := dw.resolve_material_source(
        NEW.source,NEW.source_id,NEW.data->>'url',NEW.data->>'original_url',
        NEW.data->>'title',NEW.data->>'summary',NEW.data->>'publisher',
        CASE WHEN NEW.data->>'published_on' ~ '^\d{4}-\d{2}-\d{2}$'
            THEN (NEW.data->>'published_on')::date::timestamp AT TIME ZONE 'Asia/Seoul'
            ELSE NULL END,NULL,NULL,NULL,NULL);
    RETURN NEW;
END;
$$;
CREATE FUNCTION dw.assign_search_material() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.material_id := dw.resolve_material_source(
        NEW.provider || '_' || NEW.channel,NEW.source_id,
        NEW.data->>'url',NEW.data->>'original_url',NEW.data->>'title',
        NEW.data->>'summary',NULL,
        CASE WHEN NEW.data->>'published_at' IS NOT NULL
            THEN (NEW.data->>'published_at')::timestamptz
            WHEN NEW.data->>'published_on' ~ '^\d{4}-\d{2}-\d{2}$'
            THEN (NEW.data->>'published_on')::date::timestamp AT TIME ZONE 'Asia/Seoul'
            ELSE NULL END,
        NEW.data->>'container_name',NEW.data->>'cafe_url',
        NEW.data->>'blog_name',NEW.data->>'blog_url');
    RETURN NEW;
END;
$$;
CREATE FUNCTION dw.assign_content_material() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    seed jsonb;
    cafe_name text;
BEGIN
    SELECT result->'seed' INTO seed FROM st.article_detail_results
    WHERE source_id=NEW.source_id AND result->'seed'->>'source'=NEW.source
    ORDER BY run_id DESC LIMIT 1;
    SELECT data->>'container_name' INTO cafe_name FROM dw.search_items
    WHERE provider='naver' AND channel='cafearticle' AND source_id=NEW.source_id;
    NEW.material_id := dw.resolve_material_source(
        NEW.source,NEW.source_id,NULL,seed->>'original_url',NEW.title,
        seed->>'summary',CASE WHEN NEW.source IN ('bigkinds','naver_news')
            THEN seed->>'publisher' END,
        CASE WHEN seed->>'published_on' ~ '^\d{4}-\d{2}-\d{2}$'
            THEN (seed->>'published_on')::date::timestamp AT TIME ZONE 'Asia/Seoul'
            ELSE NULL END,cafe_name,NULL,NULL,NULL);
    RETURN NEW;
END;
$$;

DROP TRIGGER assign_news_article ON dw.news_items;
DROP TRIGGER assign_search_article ON dw.search_items;
DROP TRIGGER assign_content_article ON dw.article_contents;
CREATE TRIGGER assign_news_material BEFORE INSERT OR UPDATE OF data ON dw.news_items
FOR EACH ROW EXECUTE FUNCTION dw.assign_news_material();
CREATE TRIGGER assign_search_material BEFORE INSERT OR UPDATE OF data ON dw.search_items
FOR EACH ROW EXECUTE FUNCTION dw.assign_search_material();
CREATE TRIGGER assign_content_material BEFORE INSERT ON dw.article_contents
FOR EACH ROW EXECUTE FUNCTION dw.assign_content_material();
DROP FUNCTION dw.assign_news_article();
DROP FUNCTION dw.assign_search_article();
DROP FUNCTION dw.assign_content_article();
DROP FUNCTION dw.resolve_article_source(text,text,text,text,text,text,text,timestamptz);

CREATE OR REPLACE FUNCTION ops.enqueue_article_analysis() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source NOT IN ('bigkinds','naver_news') THEN
        RETURN NEW;
    END IF;
    INSERT INTO ops.analysis_queue_keys(article_id,content_hash,source,source_id)
    VALUES (NEW.material_id,NEW.content_hash,NEW.source,NEW.source_id)
    ON CONFLICT DO NOTHING;
    IF FOUND THEN
        INSERT INTO ops.analysis_queue(article_id,source,source_id,content_hash)
        VALUES (NEW.material_id,NEW.source,NEW.source_id,NEW.content_hash)
        ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;

COMMIT;
