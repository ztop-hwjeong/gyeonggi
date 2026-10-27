BEGIN;

CREATE TABLE dw.article_identity_keys (
    kind text NOT NULL,
    key text NOT NULL,
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    PRIMARY KEY (kind, key)
);
CREATE TABLE dw.article_identity_conflicts (
    source text NOT NULL,
    source_id text NOT NULL,
    article_id uuid NOT NULL REFERENCES dw.articles(id),
    other_article_id uuid NOT NULL REFERENCES dw.articles(id),
    kind text NOT NULL,
    key text NOT NULL,
    seen_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_id, kind, key)
);

-- 확인 가능한 언론사 원문 URL만 동일 기사 근거로 사용
CREATE FUNCTION dw.canonical_article_url(raw_url text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE parsed text[]; host text; path_part text; query_part text; clean_query text;
BEGIN
    IF raw_url IS NULL OR raw_url !~* '^https?://' THEN RETURN NULL; END IF;
    parsed := regexp_match(btrim(raw_url), '^https?://([^/?#]+)([^#]*)', 'i');
    IF parsed IS NULL THEN RETURN NULL; END IF;
    host := lower(regexp_replace(parsed[1], ':(80|443)$', ''));
    IF host IN ('news.naver.com','search.naver.com','bigkinds.or.kr','www.bigkinds.or.kr')
        OR host = '' OR host LIKE '%@%' THEN RETURN NULL; END IF;
    path_part := split_part(parsed[2], '?', 1);
    query_part := substring(parsed[2] from '\?(.*)$');
    SELECT string_agg(part, '&' ORDER BY part) INTO clean_query
    FROM regexp_split_to_table(coalesce(query_part, ''), '&') AS part
    WHERE part <> '' AND lower(split_part(part, '=', 1)) !~ '^(utm_.*|fbclid|gclid)$';
    IF coalesce(path_part, '') IN ('', '/') AND clean_query IS NULL THEN RETURN NULL; END IF;
    RETURN 'https://' || host || coalesce(nullif(path_part, ''), '/') ||
        CASE WHEN clean_query IS NULL THEN '' ELSE '?' || clean_query END;
END;
$$;

CREATE FUNCTION dw.resolve_article_source(
    p_source text, p_source_id text, p_url text, p_original_url text,
    p_title text, p_summary text, p_publisher text,
    p_published_on date, p_published_at timestamptz
) RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE found_id uuid; keyed_id uuid; canonical text;
BEGIN
    IF p_source NOT IN ('bigkinds', 'naver_news') THEN
        RAISE EXCEPTION 'Unsupported article source: %', p_source;
    END IF;
    canonical := dw.canonical_article_url(p_original_url);
    PERFORM pg_advisory_xact_lock(hashtextextended('source:' || p_source || ':' || p_source_id, 0));
    SELECT article_id INTO found_id FROM dw.article_sources
        WHERE source = p_source AND source_id = p_source_id;
    IF canonical IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(hashtextextended('url:' || canonical, 0));
        SELECT article_id INTO keyed_id FROM dw.article_identity_keys
            WHERE kind = 'publisher_url' AND key = canonical;
    END IF;
    IF found_id IS NULL THEN
        found_id := keyed_id;
    ELSIF keyed_id IS NOT NULL AND found_id <> keyed_id THEN
        INSERT INTO dw.article_identity_conflicts
            (source, source_id, article_id, other_article_id, kind, key)
        VALUES (p_source, p_source_id, found_id, keyed_id, 'publisher_url', canonical)
        ON CONFLICT (source, source_id, kind, key) DO UPDATE SET
            article_id = EXCLUDED.article_id,
            other_article_id = EXCLUDED.other_article_id,
            seen_at = now();
    END IF;
    IF found_id IS NULL THEN
        INSERT INTO dw.material_keys(kind) VALUES ('news') RETURNING id INTO found_id;
        INSERT INTO dw.articles(id, title, summary, publisher, published_on, published_at)
        VALUES (found_id, coalesce(nullif(p_title, ''), p_source_id), nullif(p_summary, ''),
            nullif(p_publisher, ''), p_published_on, p_published_at);
    ELSE
        UPDATE dw.articles SET
            title = coalesce(nullif(p_title, ''), title),
            summary = coalesce(nullif(p_summary, ''), summary),
            publisher = coalesce(nullif(p_publisher, ''), publisher),
            published_on = CASE WHEN original_published_on IS NULL AND original_published_at IS NULL
                THEN coalesce(p_published_on, published_on) ELSE published_on END,
            published_at = CASE WHEN original_published_on IS NULL AND original_published_at IS NULL
                THEN coalesce(p_published_at, published_at) ELSE published_at END,
            updated_at = now()
        WHERE id = found_id;
    END IF;
    INSERT INTO dw.article_sources
        (article_id, source, source_id, url, original_url, canonical_url, published_at)
    VALUES (found_id, p_source, p_source_id, nullif(p_url, ''),
        nullif(p_original_url, ''), canonical, p_published_at)
    ON CONFLICT (source, source_id) DO UPDATE SET
        url = coalesce(EXCLUDED.url, dw.article_sources.url),
        original_url = coalesce(EXCLUDED.original_url, dw.article_sources.original_url),
        canonical_url = coalesce(EXCLUDED.canonical_url, dw.article_sources.canonical_url),
        published_at = coalesce(EXCLUDED.published_at, dw.article_sources.published_at),
        last_seen_at = now();
    IF canonical IS NOT NULL AND (keyed_id IS NULL OR keyed_id = found_id) THEN
        INSERT INTO dw.article_identity_keys(kind, key, article_id)
        VALUES ('publisher_url', canonical, found_id) ON CONFLICT DO NOTHING;
    END IF;
    RETURN found_id;
END;
$$;

CREATE FUNCTION dw.resolve_blog_source(
    p_source text, p_source_id text, p_url text, p_original_url text,
    p_title text, p_summary text, p_blog_name text, p_blog_url text,
    p_published_on date, p_published_at timestamptz
) RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE found_id uuid;
BEGIN
    IF p_source <> 'naver_blog' THEN
        RAISE EXCEPTION 'Unsupported blog source: %', p_source;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('source:' || p_source || ':' || p_source_id, 0));
    SELECT blog_post_id INTO found_id FROM dw.blog_sources
        WHERE source = p_source AND source_id = p_source_id;
    IF found_id IS NULL THEN
        INSERT INTO dw.material_keys(kind) VALUES ('blog') RETURNING id INTO found_id;
        INSERT INTO dw.blog_posts
            (id, title, summary, blog_name, blog_url, published_on, published_at)
        VALUES (found_id, coalesce(nullif(p_title, ''), p_source_id), nullif(p_summary, ''),
            nullif(p_blog_name, ''), nullif(p_blog_url, ''), p_published_on, p_published_at);
    ELSE
        UPDATE dw.blog_posts SET
            title = coalesce(nullif(p_title, ''), title),
            summary = coalesce(nullif(p_summary, ''), summary),
            blog_name = coalesce(nullif(p_blog_name, ''), blog_name),
            blog_url = coalesce(nullif(p_blog_url, ''), blog_url),
            published_on = coalesce(p_published_on, published_on),
            published_at = coalesce(p_published_at, published_at),
            updated_at = now()
        WHERE id = found_id;
    END IF;
    INSERT INTO dw.blog_sources(blog_post_id, source, source_id, url, original_url)
    VALUES (found_id, p_source, p_source_id, nullif(p_url, ''), nullif(p_original_url, ''))
    ON CONFLICT (source, source_id) DO UPDATE SET
        url = coalesce(EXCLUDED.url, dw.blog_sources.url),
        original_url = coalesce(EXCLUDED.original_url, dw.blog_sources.original_url),
        last_seen_at = now();
    RETURN found_id;
END;
$$;

CREATE FUNCTION dw.assign_news_article() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.article_id := dw.resolve_article_source(
        NEW.source, NEW.source_id, NEW.data->>'url', NEW.data->>'original_url',
        NEW.data->>'title', NEW.data->>'summary', NEW.data->>'publisher',
        CASE WHEN NEW.data->>'published_on' ~ '^\d{4}-\d{2}-\d{2}$'
            THEN (NEW.data->>'published_on')::date END,
        CASE WHEN NEW.data->>'published_at' IS NOT NULL
            THEN (NEW.data->>'published_at')::timestamptz END);
    RETURN NEW;
END;
$$;
CREATE TRIGGER assign_news_article BEFORE INSERT OR UPDATE OF data ON dw.news_items
FOR EACH ROW EXECUTE FUNCTION dw.assign_news_article();

CREATE FUNCTION dw.assign_search_material() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE publication_day date; publication_time timestamptz;
BEGIN
    publication_day := CASE WHEN NEW.data->>'published_on' ~ '^\d{4}-\d{2}-\d{2}$'
        THEN (NEW.data->>'published_on')::date END;
    publication_time := CASE WHEN NEW.data->>'published_at' IS NOT NULL
        THEN (NEW.data->>'published_at')::timestamptz END;
    IF NEW.channel = 'news' THEN
        NEW.article_id := dw.resolve_article_source(
            NEW.provider || '_' || NEW.channel, NEW.source_id,
            NEW.data->>'url', NEW.data->>'original_url', NEW.data->>'title',
            NEW.data->>'summary', NEW.data->>'publisher', publication_day, publication_time);
        NEW.blog_post_id := NULL;
    ELSIF NEW.channel = 'blog' THEN
        NEW.blog_post_id := dw.resolve_blog_source(
            NEW.provider || '_' || NEW.channel, NEW.source_id,
            NEW.data->>'url', NEW.data->>'original_url', NEW.data->>'title',
            NEW.data->>'summary', NEW.data->>'blog_name', NEW.data->>'blog_url',
            publication_day, publication_time);
        NEW.article_id := NULL;
    ELSE
        RAISE EXCEPTION 'Unsupported search channel: %', NEW.channel;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER assign_search_material BEFORE INSERT OR UPDATE OF data ON dw.search_items
FOR EACH ROW EXECUTE FUNCTION dw.assign_search_material();

CREATE FUNCTION dw.assign_content_article() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE seed jsonb;
BEGIN
    SELECT result->'seed' INTO seed FROM st.article_detail_results
    WHERE run_id = NEW.run_id AND source_id = NEW.source_id
        AND result->'seed'->>'source' = NEW.source;
    NEW.article_id := dw.resolve_article_source(
        NEW.source, NEW.source_id, NULL, seed->>'original_url', NEW.title,
        seed->>'summary', seed->>'publisher',
        CASE WHEN seed->>'published_on' ~ '^\d{4}-\d{2}-\d{2}$'
            THEN (seed->>'published_on')::date END,
        CASE WHEN seed->>'published_at' IS NOT NULL
            THEN (seed->>'published_at')::timestamptz END);
    RETURN NEW;
END;
$$;
CREATE TRIGGER assign_content_article BEFORE INSERT ON dw.article_contents
FOR EACH ROW EXECUTE FUNCTION dw.assign_content_article();

CREATE FUNCTION dw.sync_article_original_dates() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE dw.articles SET
        original_published_on = NEW.original_published_on,
        original_published_at = NEW.original_published_at,
        original_modified_on = NEW.original_modified_on,
        original_modified_at = NEW.original_modified_at,
        published_on = coalesce(NEW.original_published_on, published_on),
        published_at = CASE
            WHEN NEW.original_published_on IS NOT NULL OR NEW.original_published_at IS NOT NULL
            THEN NEW.original_published_at ELSE published_at END,
        updated_at = now()
    WHERE id = NEW.article_id
        AND NOT EXISTS (
            SELECT 1 FROM dw.article_contents newer
            WHERE newer.article_id = NEW.article_id
                AND (newer.created_at, newer.id) > (NEW.created_at, NEW.id)
        );
    RETURN NEW;
END;
$$;
CREATE TRIGGER sync_article_original_dates
AFTER INSERT OR UPDATE OF original_published_on, original_published_at,
    original_modified_on, original_modified_at, collected_at ON dw.article_contents
FOR EACH ROW EXECUTE FUNCTION dw.sync_article_original_dates();

CREATE VIEW dw.materials AS
    SELECT a.id, 'news'::text AS kind, a.title, a.summary, a.publisher,
        NULL::text AS blog_name, NULL::text AS blog_url,
        a.published_on, a.published_at, a.created_at, a.updated_at
    FROM dw.articles a
    UNION ALL
    SELECT b.id, 'blog'::text AS kind, b.title, b.summary, NULL::text AS publisher,
        b.blog_name, b.blog_url, b.published_on, b.published_at, b.created_at, b.updated_at
    FROM dw.blog_posts b;

CREATE VIEW dw.material_sources AS
    SELECT s.article_id AS material_id, s.source, s.source_id, s.url,
        s.original_url, s.canonical_url, s.published_at, s.first_seen_at, s.last_seen_at
    FROM dw.article_sources s
    UNION ALL
    SELECT s.blog_post_id AS material_id, s.source, s.source_id, s.url,
        s.original_url, NULL::text AS canonical_url, NULL::timestamptz AS published_at,
        s.first_seen_at, s.last_seen_at
    FROM dw.blog_sources s;

CREATE TABLE ops.article_reprints (
    article_a_id uuid NOT NULL REFERENCES dw.articles(id),
    article_b_id uuid NOT NULL REFERENCES dw.articles(id),
    article_a_content_hash text NOT NULL,
    article_b_content_hash text NOT NULL,
    body_similarity double precision NOT NULL CHECK (body_similarity BETWEEN 0 AND 1),
    matching_basis text NOT NULL,
    checked_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (article_a_id, article_b_id, article_a_content_hash, article_b_content_hash),
    CHECK (article_a_id < article_b_id)
);
CREATE INDEX article_reprints_b_idx ON ops.article_reprints(article_b_id, checked_at DESC);

COMMIT;
