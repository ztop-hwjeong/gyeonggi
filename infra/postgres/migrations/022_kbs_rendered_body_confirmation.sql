INSERT INTO ops.article_browser_policies (domain, browser_mode, reason, evidence)
VALUES (
    'news.kbs.co.kr',
    'rendered_after_http_failure',
    '동적 본문 및 영상 전용 기사의 렌더링 후 텍스트 유무 확인',
    '{"method":"verified_site_structure","body_selector":"#cont_newstext","print_selector":"#mailHtmlContents .view_con_text"}'::jsonb
)
ON CONFLICT (domain) DO UPDATE
SET browser_mode = EXCLUDED.browser_mode,
    reason = EXCLUDED.reason,
    evidence = EXCLUDED.evidence,
    updated_at = now();
