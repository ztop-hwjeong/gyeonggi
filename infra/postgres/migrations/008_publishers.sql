BEGIN;

CREATE TABLE dw.publishers (
    code text PRIMARY KEY CHECK (btrim(code) <> ''),
    name text CHECK (name IS NULL OR btrim(name) <> '')
);
CREATE TABLE dw.publisher_domains (
    domain text PRIMARY KEY CHECK (domain = lower(domain) AND btrim(domain) <> ''),
    publisher_code text NOT NULL REFERENCES dw.publishers(code) ON UPDATE CASCADE
);

INSERT INTO dw.publishers(code, name) VALUES
    ('munhwa.com', '문화일보'),
    ('news.tvchosun.com', 'TV조선'),
    ('gg.newdaily.co.kr', '뉴데일리');
INSERT INTO dw.publisher_domains(domain, publisher_code) VALUES
    ('munhwa.com', 'munhwa.com'),
    ('news.tvchosun.com', 'news.tvchosun.com'),
    ('gg.newdaily.co.kr', 'gg.newdaily.co.kr'),
    ('newdaily.co.kr', 'gg.newdaily.co.kr');

INSERT INTO dw.publishers(code, name)
SELECT publisher_code,
    CASE WHEN count(DISTINCT publisher) = 1 THEN min(publisher) END
FROM dw.articles WHERE publisher_code IS NOT NULL GROUP BY publisher_code
ON CONFLICT DO NOTHING;
INSERT INTO dw.publisher_domains(domain, publisher_code)
SELECT code, code FROM dw.publishers WHERE code NOT LIKE 'naver:%'
ON CONFLICT DO NOTHING;
ALTER TABLE dw.articles ADD CONSTRAINT articles_publisher_code_fkey
    FOREIGN KEY (publisher_code) REFERENCES dw.publishers(code) ON UPDATE CASCADE;

CREATE FUNCTION dw.resolve_publisher_code(identifier text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE resolved text;
BEGIN
    IF nullif(identifier, '') IS NULL THEN RETURN NULL; END IF;
    IF identifier NOT LIKE 'naver:%' THEN
        SELECT publisher_code INTO resolved FROM dw.publisher_domains WHERE domain = identifier;
        IF resolved IS NOT NULL THEN RETURN resolved; END IF;
    END IF;
    INSERT INTO dw.publishers(code) VALUES (identifier) ON CONFLICT DO NOTHING;
    IF identifier LIKE 'naver:%' THEN RETURN identifier; END IF;
    INSERT INTO dw.publisher_domains(domain, publisher_code) VALUES (identifier, identifier)
        ON CONFLICT DO NOTHING;
    SELECT publisher_code INTO resolved FROM dw.publisher_domains WHERE domain = identifier;
    RETURN resolved;
END;
$$;

CREATE FUNCTION dw.assign_search_publisher() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE resolved text; display_name text;
BEGIN
    IF NEW.provider <> 'naver' OR NEW.channel <> 'news' THEN RETURN NEW; END IF;
    resolved := dw.resolve_publisher_code(coalesce(
        NEW.data->>'publisher_domain', NEW.data->>'publisher_code'));
    IF resolved IS NOT NULL THEN
        SELECT name INTO display_name FROM dw.publishers WHERE code = resolved;
        NEW.data := NEW.data || jsonb_build_object('publisher_code', resolved, 'publisher', display_name);
    END IF;
    RETURN NEW;
END;
$$;
-- 자료 통합 식별보다 먼저 수행하는 언론사 코드 해석
CREATE TRIGGER a_assign_search_publisher BEFORE INSERT OR UPDATE OF data ON dw.search_items
FOR EACH ROW EXECUTE FUNCTION dw.assign_search_publisher();

CREATE OR REPLACE FUNCTION dw.sync_search_publisher_code() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.provider = 'naver' AND NEW.channel = 'news'
        AND nullif(NEW.data->>'publisher_code', '') IS NOT NULL THEN
        UPDATE dw.articles SET publisher_code = NEW.data->>'publisher_code',
            publisher = (SELECT name FROM dw.publishers WHERE code = NEW.data->>'publisher_code')
        WHERE id = NEW.article_id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION dw.sync_publisher_name() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE dw.articles SET publisher = NEW.name WHERE publisher_code = NEW.code;
    RETURN NEW;
END;
$$;
CREATE TRIGGER sync_publisher_name AFTER UPDATE OF name ON dw.publishers
FOR EACH ROW WHEN (OLD.name IS DISTINCT FROM NEW.name) EXECUTE FUNCTION dw.sync_publisher_name();

CREATE FUNCTION dw.sync_publisher_domain() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE dw.search_items SET data = data WHERE provider = 'naver' AND channel = 'news'
        AND data->>'publisher_domain' = NEW.domain;
    RETURN NEW;
END;
$$;
CREATE TRIGGER sync_publisher_domain AFTER UPDATE OF publisher_code ON dw.publisher_domains
FOR EACH ROW WHEN (OLD.publisher_code IS DISTINCT FROM NEW.publisher_code)
EXECUTE FUNCTION dw.sync_publisher_domain();

COMMIT;
