BEGIN;

ALTER TABLE dw.articles ADD COLUMN publisher_code text;

CREATE FUNCTION dw.sync_search_publisher_code() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.provider = 'naver' AND NEW.channel = 'news'
        AND nullif(NEW.data->>'publisher_code', '') IS NOT NULL THEN
        UPDATE dw.articles SET publisher_code = NEW.data->>'publisher_code'
        WHERE id = NEW.article_id;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER sync_search_publisher_code
AFTER INSERT OR UPDATE OF data ON dw.search_items
FOR EACH ROW EXECUTE FUNCTION dw.sync_search_publisher_code();

COMMIT;
