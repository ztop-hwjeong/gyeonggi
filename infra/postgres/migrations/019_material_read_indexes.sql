-- 수집 쓰기와 병행하는 최신 본문·자료 목록 조회 인덱스 생성
CREATE INDEX CONCURRENTLY article_contents_article_latest_idx
    ON dw.article_contents(article_id, created_at DESC, id DESC);

CREATE INDEX CONCURRENTLY articles_updated_page_idx
    ON dw.articles(updated_at DESC, id);

CREATE INDEX CONCURRENTLY blog_posts_updated_page_idx
    ON dw.blog_posts(updated_at DESC, id);
