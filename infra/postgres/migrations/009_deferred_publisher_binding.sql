BEGIN;

CREATE OR REPLACE FUNCTION dw.resolve_publisher_code(identifier text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE resolved text;
BEGIN
    IF nullif(identifier, '') IS NULL THEN RETURN NULL; END IF;
    IF identifier LIKE 'naver:%' THEN
        SELECT code INTO resolved FROM dw.publishers WHERE code = identifier;
    ELSE
        SELECT publisher_code INTO resolved FROM dw.publisher_domains WHERE domain = identifier;
    END IF;
    RETURN resolved;
END;
$$;

CREATE OR REPLACE FUNCTION dw.assign_search_publisher() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE resolved text; display_name text;
BEGIN
    IF NEW.provider <> 'naver' OR NEW.channel <> 'news' THEN RETURN NEW; END IF;
    resolved := dw.resolve_publisher_code(coalesce(
        NEW.data->>'publisher_domain', NEW.data->>'publisher_code'));
    SELECT name INTO display_name FROM dw.publishers WHERE code = resolved;
    NEW.data := NEW.data || jsonb_build_object(
        'publisher_code', resolved,
        'publisher', coalesce(display_name, NEW.data->>'publisher'));
    RETURN NEW;
END;
$$;

CREATE FUNCTION dw.article_publisher_domain(raw_url text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT regexp_replace(lower(substring(btrim(raw_url) from '(?i)^https?://([^/?#:]+)')), '^www\.', '');
$$;

CREATE FUNCTION dw.sync_article_source_publisher() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE resolved text; display_name text;
BEGIN
    SELECT p.code, p.name INTO resolved, display_name
    FROM dw.publisher_domains d JOIN dw.publishers p ON p.code = d.publisher_code
    WHERE d.domain = dw.article_publisher_domain(coalesce(nullif(NEW.original_url, ''), NEW.url));
    IF resolved IS NOT NULL THEN
        UPDATE dw.articles SET publisher_code = resolved, publisher = coalesce(display_name, publisher)
        WHERE id = NEW.article_id;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER sync_article_source_publisher
AFTER INSERT OR UPDATE OF original_url, url ON dw.article_sources
FOR EACH ROW EXECUTE FUNCTION dw.sync_article_source_publisher();

CREATE OR REPLACE FUNCTION dw.sync_publisher_domain() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE dw.search_items SET data = data WHERE provider = 'naver' AND channel = 'news'
        AND data->>'publisher_domain' = NEW.domain;
    UPDATE dw.articles a
    SET publisher_code = NEW.publisher_code,
        publisher = coalesce((SELECT name FROM dw.publishers WHERE code = NEW.publisher_code), a.publisher)
    WHERE EXISTS (
        SELECT 1 FROM dw.article_sources s WHERE s.article_id = a.id
        AND dw.article_publisher_domain(coalesce(nullif(s.original_url, ''), s.url)) = NEW.domain
    );
    RETURN NEW;
END;
$$;
DROP TRIGGER sync_publisher_domain ON dw.publisher_domains;
CREATE TRIGGER sync_publisher_domain AFTER INSERT OR UPDATE OF publisher_code ON dw.publisher_domains
FOR EACH ROW EXECUTE FUNCTION dw.sync_publisher_domain();

CREATE OR REPLACE FUNCTION dw.sync_publisher_name() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE dw.articles SET publisher = NEW.name WHERE publisher_code = NEW.code;
    UPDATE dw.search_items SET data = data WHERE provider = 'naver' AND channel = 'news'
        AND data->>'publisher_domain' = NEW.code;
    RETURN NEW;
END;
$$;
DROP TRIGGER sync_publisher_name ON dw.publishers;
CREATE TRIGGER sync_publisher_name AFTER INSERT OR UPDATE OF name ON dw.publishers
FOR EACH ROW EXECUTE FUNCTION dw.sync_publisher_name();

UPDATE dw.article_sources SET original_url = original_url;

COMMIT;
