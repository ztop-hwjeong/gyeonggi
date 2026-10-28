BEGIN;

-- 기준 목록 밖에서 실체를 확인한 지역 일간지 등록
INSERT INTO dw.publishers(code,name,category_code,category_source) VALUES
    ('01a1817a-e507-7de4-83b7-3d628d5724e0', '광주드림', 'general_daily', 'manual')
ON CONFLICT (code) DO NOTHING;

-- 수집 원문에서 확인한 매체 명칭과 기준 코드 연결
INSERT INTO dw.publisher_domains(domain,publisher_code,evidence) VALUES
    ('aitimes.com', '2746', '{"method": "publisher_site_identity", "url": "https://www.aitimes.com/news/articleView.html?idxno=212161", "name": "AI타임스"}'),
    ('bigtanews.co.kr', '2645', '{"source": "naver_news", "original_url": "https://www.bigtanews.co.kr/article/view/big202502270020", "method": "catalog publisher name/domain identity"}'),
    ('biz.newdaily.co.kr', '2005', '{"source": "late-unlinked-review", "matched_name": "뉴데일리"}'),
    ('bntnews.co.kr', '2191', '{"method": "publisher_site_identity", "url": "https://www.bntnews.co.kr/article/view/bnt202610200209", "name": "bnt뉴스"}'),
    ('cbci.co.kr', '2785', '{"source": "naver_news", "original_url": "https://www.cbci.co.kr/news/articleView.html?idxno=486310", "method": "catalog publisher name/domain identity"}'),
    ('ccdn.co.kr', '2116', '{"source": "late-unlinked-review", "matched_name": "충청일보"}'),
    ('ch.yes24.com', '2185', '{"method": "publisher_site_identity", "url": "https://ch.yes24.com/Article/View/81234", "name": "채널예스"}'),
    ('dailysportshankook.co.kr', '2604', '{"source": "naver_news", "original_url": "https://www.dailysportshankook.co.kr/news/articleView.html?idxno=334208", "method": "catalog publisher name/domain identity"}'),
    ('ddaily.co.kr', '1138', '{"source": "late-unlinked-review", "matched_name": "디지털데일리"}'),
    ('ddanzi.com', '2390', '{"method": "publisher_site_identity", "url": "http://www.ddanzi.com/890438432", "name": "딴지일보"}'),
    ('econovill.com', '2097', '{"source": "naver_news", "original_url": "https://www.econovill.com/news/articleView.html?idxno=683748", "method": "article masthead", "primary_url": "https://www.econovill.com/news/articleView.html?idxno=683748"}'),
    ('enetnews.co.kr', '2866', '{"source": "late-unlinked-review", "matched_name": "이넷뉴스", "canonical_rebind": {"from": "01a1817c-0742-74a2-80f5-89b1edc6452c", "reason": "reference_catalog_exact_name"}}'),
    ('eroun.net', '2738', '{"method": "publisher_site_identity", "url": "https://www.eroun.net/news/articleView.html?idxno=51420", "name": "이로운넷"}'),
    ('fetv.co.kr', '2484', '{"source": "naver_news", "original_url": "https://www.fetv.co.kr/news/article.html?no=165537", "method": "catalog publisher name/domain identity"}'),
    ('fntoday.co.kr', '2585', '{"source": "late-unlinked-review", "matched_name": "파이낸스투데이"}'),
    ('fsnews.co.kr', '2470', '{"method": "publisher_site_identity", "url": "http://www.fsnews.co.kr/news/articleView.html?idxno=62464", "name": "대한급식신문"}'),
    ('ftoday.co.kr', '2585', '{"source": "naver_news", "original_url": "http://www.ftoday.co.kr/news/articleView.html?idxno=367893", "method": "catalog publisher name/domain identity"}'),
    ('geconomy.co.kr', '2633', '{"source": "late-unlinked-review", "matched_name": "G.ECONOMY", "canonical_rebind": {"from": "01a1817c-0902-7035-82b9-f0dd52e2b67a", "reason": "reference_catalog_exact_name"}}'),
    ('gjdream.com', '01a1817a-e507-7de4-83b7-3d628d5724e0', '{"method": "publisher_site_identity", "url": "http://www.gjdream.com/news/articleView.html?idxno=653698", "name": "광주드림", "type_basis_url": "https://news.nate.com/view/20220916n18954"}'),
    ('gndomin.com', '2416', '{"source": "naver_news", "original_url": "http://www.gndomin.com/news/articleView.html?idxno=493595", "method": "catalog publisher name/domain identity"}'),
    ('gnmaeil.com', '2346', '{"source": "late-unlinked-review", "matched_name": "경남매일신문"}'),
    ('gnnews.co.kr', '2217', '{"method": "publisher_site_identity", "url": "https://www.gnnews.co.kr/news/articleView.html?idxno=648061", "name": "경남일보"}'),
    ('huffingtonpost.kr', '2384', '{"source": "naver_news", "original_url": "https://www.huffingtonpost.kr/news/articleView.html?idxno=234733", "method": "catalog publisher name/domain identity"}'),
    ('ikbc.co.kr', '1660', '{"source": "late-unlinked-review", "matched_name": "kbc광주방송"}'),
    ('ikld.kr', '2338', '{"method": "publisher_site_identity", "url": "http://www.ikld.kr/news/articleView.html?idxno=342824", "name": "국토일보"}'),
    ('ikpnews.net', '2414', '{"source": "naver_news", "original_url": "http://www.ikpnews.net/news/articleView.html?idxno=71745", "method": "site masthead", "primary_url": "https://pdf.ikpnews.net/832/83216.pdf"}'),
    ('ilyoseoul.co.kr', '2279', '{"source": "late-unlinked-review", "matched_name": "일요서울"}'),
    ('incheonin.com', '2808', '{"method": "publisher_site_identity", "url": "http://www.incheonin.com/news/articleView.html?idxno=104792", "name": "인천in"}'),
    ('incheontoday.com', '2688', '{"source": "naver_news", "original_url": "https://www.incheontoday.com/news/articleView.html?idxno=304072", "method": "catalog publisher name/domain identity"}'),
    ('insight.co.kr', '2486', '{"source": "late-unlinked-review", "matched_name": "인사이트"}'),
    ('jbsori.com', '2883', '{"method": "publisher_site_identity", "url": "http://www.jbsori.com/news/articleView.html?idxno=15530", "name": "전북의소리"}'),
    ('jeonmin.co.kr', '2368', '{"source": "naver_news", "original_url": "http://www.jeonmin.co.kr/news/articleView.html?idxno=414962", "method": "catalog publisher name/domain identity"}'),
    ('jjan.kr', '2335', '{"source": "late-unlinked-review", "matched_name": "전북일보"}'),
    ('jmagazine.joins.com', '2203', '{"method": "publisher_site_identity", "url": "http://jmagazine.joins.com/monthly/view/340165", "name": "월간중앙"}'),
    ('jndn.com', '2379', '{"source": "naver_news", "original_url": "http://www.jndn.com/article.php?aid=1739787443404103001", "method": "catalog publisher name/domain identity"}'),
    ('joseilbo.com', '1123', '{"source": "late-unlinked-review", "matched_name": "조세일보"}'),
    ('journalist.or.kr', '1127', '{"method": "publisher_site_identity", "url": "http://www.journalist.or.kr/news/article.html?no=57877", "name": "기자협회보"}'),
    ('kbsm.net', '2533', '{"source": "naver_news", "original_url": "http://www.kbsm.net/news/view.php?idx=464276", "method": "article masthead", "primary_url": "https://www.kbsm.net/news/view.php?idx=464276"}'),
    ('kfenews.co.kr', '2206', '{"source": "late-unlinked-review", "matched_name": "한국금융경제신문"}'),
    ('kidshankook.kr', '2360', '{"method": "publisher_site_identity", "url": "https://www.kidshankook.kr/news/articleView.html?idxno=10150", "name": "소년한국일보"}'),
    ('kizmom.com', '2310', '{"source": "naver_news", "original_url": "https://www.kizmom.com/news/articleView.html?idxno=89520", "method": "catalog publisher name/domain identity"}'),
    ('kjmbc.co.kr', '2383', '{"source": "late-unlinked-review", "matched_name": "광주MBC"}'),
    ('korea.kr', '2881', '{"method": "publisher_site_identity", "url": "https://www.korea.kr/news/policyNewsView.do?call_from=naver_news&newsId=148954474", "name": "대한민국 정책브리핑"}'),
    ('koreareport.co.kr', '2917', '{"source": "naver_news", "original_url": "http://www.koreareport.co.kr/news/articleView.html?idxno=35592", "method": "catalog publisher name/domain identity"}'),
    ('kpenews.com', '2503', '{"source": "late-unlinked-review", "matched_name": "한국정경신문"}'),
    ('kyosu.net', '2150', '{"method": "publisher_site_identity", "url": "http://www.kyosu.net/news/articleView.html?idxno=142905", "name": "교수신문"}'),
    ('lawtimes.co.kr', '2094', '{"source": "naver_news", "original_url": "https://www.lawtimes.co.kr/news/212039", "method": "catalog publisher name/domain identity"}'),
    ('livesnews.com', '2811', '{"source": "late-unlinked-review", "matched_name": "라이브뉴스", "canonical_rebind": {"from": "01a1817c-0c19-7eee-80ec-1d81274a5e30", "reason": "reference_catalog_exact_name"}}'),
    ('ltn.kr', '2626', '{"method": "publisher_site_identity", "url": "https://www.ltn.kr/news/articleView.html?idxno=48066", "name": "법률방송뉴스"}'),
    ('m.skyedaily.com', '2510', '{"source": "naver_news", "original_url": "https://m.skyedaily.com/news_view.html?ID=263393", "method": "catalog publisher name/domain identity"}'),
    ('magazine.hankyung.com', '1050', '{"source": "naver_news", "original_url": "https://magazine.hankyung.com/business/article/202610230957b", "method": "article masthead", "primary_url": "https://magazine.hankyung.com/business/article/202610230957b"}'),
    ('mediapen.com', '2244', '{"source": "late-unlinked-review", "matched_name": "미디어펜"}'),
    ('mhns.co.kr', '2415', '{"method": "publisher_site_identity", "url": "https://www.mhns.co.kr/news/articleView.html?idxno=752144", "name": "더쎈뉴스"}'),
    ('netongs.com', '2748', '{"source": "late-unlinked-review", "matched_name": "여수넷통뉴스", "canonical_rebind": {"from": "01a1817c-0dc0-7a7e-a64a-1347fdee45c7", "reason": "reference_catalog_exact_name"}}'),
    ('news.bbsi.co.kr', '2019', '{"source": "naver_news", "original_url": "https://news.bbsi.co.kr/news/articleView.html?idxno=3156329", "method": "publisher subdomain identity"}'),
    ('news.cpbc.co.kr', '2234', '{"method": "publisher_site_identity", "url": "https://news.cpbc.co.kr/article/1168861?division=NAVER", "name": "CPBC NEWS"}'),
    ('news.lghellovision.net', '2698', '{"source": "late-unlinked-review", "matched_name": "LG헬로비전"}'),
    ('news2day.co.kr', '2527', '{"method": "publisher_site_identity", "url": "https://www.news2day.co.kr/article/20240912500105", "name": "뉴스투데이"}'),
    ('newsclaim.co.kr', '2772', '{"source": "late-unlinked-review", "matched_name": "뉴스클레임"}'),
    ('newsgn.com', '2714', '{"source": "naver_news", "original_url": "https://www.newsgn.com/news/articleView.html?idxno=580637", "method": "catalog publisher name/domain identity"}'),
    ('newsmaker.or.kr', '2159', '{"method": "publisher_site_identity", "url": "http://www.newsmaker.or.kr/news/articleView.html?idxno=162515", "name": "뉴스메이커"}'),
    ('newsprime.co.kr', '2325', '{"source": "naver_news", "original_url": "http://www.newsprime.co.kr/news/article.html?no=700131", "method": "catalog publisher name/domain identity"}'),
    ('newsverse.kr', '2897', '{"source": "late-unlinked-review", "matched_name": "뉴스버스"}'),
    ('newswhoplus.com', '2692', '{"method": "publisher_site_identity", "url": "https://www.newswhoplus.com/news/articleView.html?idxno=21174", "name": "뉴스후플러스"}'),
    ('newsworker.co.kr', '2521', '{"source": "naver_news", "original_url": "http://www.newsworker.co.kr/news/articleView.html?idxno=368125", "method": "catalog publisher name/domain identity"}'),
    ('ngetnews.com', '2824', '{"source": "late-unlinked-review", "matched_name": "뉴스저널리즘", "canonical_rebind": {"from": "01a1817c-0fdf-7609-b51d-d562ce4c24bb", "reason": "reference_catalog_exact_name"}}'),
    ('ntoday.co.kr', '2460', '{"method": "publisher_site_identity", "url": "https://www.ntoday.co.kr/news/articleView.html?idxno=110370", "name": "투데이신문"}'),
    ('pinpointnews.co.kr', '2829', '{"source": "naver_news", "original_url": "https://www.pinpointnews.co.kr/news/articleView.html?idxno=324512", "method": "catalog publisher name/domain identity"}'),
    ('polinews.co.kr', '2052', '{"source": "late-unlinked-review", "matched_name": "폴리뉴스"}'),
    ('ppss.kr', '2407', '{"method": "publisher_site_identity", "url": "https://www.ppss.kr/news/articleView.html?idxno=297271", "name": "PPSS"}'),
    ('readersnews.com', '2043', '{"source": "naver_news", "original_url": "http://www.readersnews.com/news/articleView.html?idxno=114062", "method": "catalog publisher name/domain identity"}'),
    ('siminsori.com', '2439', '{"source": "late-unlinked-review", "matched_name": "시민의소리"}'),
    ('sisain.co.kr', '1308', '{"method": "publisher_site_identity", "url": "https://www.sisain.co.kr/news/articleView.html?idxno=54840", "name": "시사IN"}'),
    ('sisunnews.co.kr', '2369', '{"source": "naver_news", "original_url": "http://www.sisunnews.co.kr/news/articleView.html?idxno=221444", "method": "catalog publisher name/domain identity"}'),
    ('slist.kr', '2575', '{"source": "late-unlinked-review", "matched_name": "싱글리스트"}'),
    ('slownews.kr', '2397', '{"method": "publisher_site_identity", "url": "https://slownews.kr/128743", "name": "슬로우뉴스"}'),
    ('smartbizn.com', '2827', '{"source": "naver_news", "original_url": "https://www.smartbizn.com/news/articleView.html?idxno=157290", "method": "catalog publisher name/domain identity"}'),
    ('sports.donga.com', '1382', '{"source": "late-unlinked-review", "matched_name": "스포츠동아"}'),
    ('stardailynews.co.kr', '2401', '{"method": "publisher_site_identity", "url": "https://www.stardailynews.co.kr/news/articleView.html?idxno=443492", "name": "스타데일리뉴스"}'),
    ('starnewskorea.com', '1108', '{"source": "naver_news", "original_url": "https://www.starnewskorea.com/sports/2026/07/01/2026070112350847888", "method": "catalog publisher name/domain identity"}'),
    ('startuptoday.co.kr', '2721', '{"source": "late-unlinked-review", "matched_name": "오늘경제", "canonical_rebind": {"from": "01a1817c-1151-7829-8f48-17e8aea21769", "reason": "reference_catalog_exact_name"}}'),
    ('straightnews.co.kr', '2677', '{"method": "publisher_site_identity", "url": "https://www.straightnews.co.kr/news/articleView.html?idxno=278362", "name": "스트레이트뉴스"}'),
    ('thebigdata.co.kr', '2645', '{"source": "naver_news", "original_url": "http://www.thebigdata.co.kr/view.php?ud=202512151810018332e91b94b033_23", "method": "catalog publisher name/domain identity"}'),
    ('thefairnews.co.kr', '2863', '{"source": "late-unlinked-review", "matched_name": "더페어", "canonical_rebind": {"from": "01a1817c-124e-7b66-b9bf-89f0cb4b9764", "reason": "reference_catalog_exact_name"}}'),
    ('thepowernews.co.kr', '2832', '{"method": "publisher_site_identity", "url": "https://www.thepowernews.co.kr/view.php?ud=20261023184750745761d72a7352_7", "name": "더파워"}'),
    ('tjb.co.kr', '2451', '{"source": "naver_news", "original_url": "http://www.tjb.co.kr/sub0301/bodo/view/id/72895", "method": "catalog publisher name/domain identity"}'),
    ('vegannews.co.kr', '2888', '{"source": "late-unlinked-review", "matched_name": "비건뉴스"}'),
    ('weekly.chosun.com', '1053', '{"method": "publisher_site_identity", "url": "http://weekly.chosun.com/news/articleView.html?idxno=40318", "name": "주간조선"}'),
    ('weekly.khan.co.kr', '1033', '{"source": "naver_news", "original_url": "https://weekly.khan.co.kr/article/202606291510001", "method": "publisher subdomain identity"}'),
    ('womennews.co.kr', '1310', '{"source": "late-unlinked-review", "matched_name": "여성신문"}'),
    ('yonhapnewstv.co.kr', '1422', '{"method": "publisher_site_identity", "url": "http://www.yonhapnewstv.co.kr/AKR20250821150115272", "name": "연합뉴스TV"}'),
    ('ziksir.com', '2489', '{"source": "naver_news", "original_url": "https://www.ziksir.com/news/articleView.html?idxno=150473", "method": "catalog publisher name/domain identity"}')
ON CONFLICT (domain) DO UPDATE SET
    publisher_code = EXCLUDED.publisher_code,
    evidence = dw.publisher_domains.evidence || EXCLUDED.evidence
WHERE dw.publisher_domains.publisher_code IS DISTINCT FROM EXCLUDED.publisher_code;

-- 등록 전 도메인으로 검증된 본문 구조의 통합 코드 재사용
WITH candidates AS (
    SELECT DISTINCT ON (new_scope,p.identifier)
        left(encode(sha256(convert_to(d.publisher_code,'UTF8')),'hex'),16)
            || substring(p.scope from 17) AS new_scope,
        p.identifier,p.properties,
        p.context || jsonb_build_object('publisher_code',d.publisher_code,'previous_scope',p.scope) AS context,
        p.updated_at
    FROM ops.publisher_adaptive_profiles p
    JOIN dw.publisher_domains d
      ON left(p.scope,16) = left(encode(sha256(convert_to(d.domain,'UTF8')),'hex'),16)
    WHERE d.publisher_code IS NOT NULL
      AND p.scope <> left(encode(sha256(convert_to(d.publisher_code,'UTF8')),'hex'),16)
          || substring(p.scope from 17)
    ORDER BY new_scope,p.identifier,p.updated_at DESC
), copied AS (
    INSERT INTO ops.publisher_adaptive_profiles(scope,identifier,properties,context,updated_at)
    SELECT new_scope,identifier,properties,context,updated_at FROM candidates
    ON CONFLICT DO NOTHING
    RETURNING scope,identifier,properties,context
)
INSERT INTO ops.publisher_adaptive_history(id,scope,identifier,properties,context)
SELECT uuidv7(),scope,identifier,properties,context FROM copied;

COMMIT;
