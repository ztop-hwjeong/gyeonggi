CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 최신 본문 ID를 대조하는 부분 문자열 검색용 역색인
CREATE INDEX CONCURRENTLY article_contents_body_trgm_idx
    ON dw.article_contents USING gin(body gin_trgm_ops)
    WITH (gin_pending_list_limit = 64);

CREATE INDEX CONCURRENTLY articles_title_trgm_idx
    ON dw.articles USING gin(title gin_trgm_ops)
    WITH (gin_pending_list_limit = 64);
