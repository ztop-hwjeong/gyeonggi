-- 반복 발견 이력의 인덱스 전용 조회를 위한 가시성 맵·통계 갱신 주기 단축
ALTER TABLE st.collection_request_items SET (
    autovacuum_vacuum_insert_scale_factor = 0.01,
    autovacuum_vacuum_insert_threshold = 1000,
    autovacuum_analyze_scale_factor = 0.02
);
