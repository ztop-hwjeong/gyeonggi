BEGIN;

-- 진행 중인 기사 저장과 언론사 재연결의 교착 방지
LOCK TABLE dw.search_items, dw.news_items, dw.article_contents, dw.article_sources, dw.articles IN ACCESS EXCLUSIVE MODE;

CREATE TABLE dw.publisher_source_categories (
    source text NOT NULL CHECK (btrim(source) <> ''),
    source_category_code text NOT NULL CHECK (btrim(source_category_code) <> ''),
    name text NOT NULL CHECK (btrim(name) <> ''),
    sort_order integer NOT NULL,
    PRIMARY KEY (source, source_category_code)
);

ALTER TABLE dw.publisher_source_codes
    ADD COLUMN source_name text,
    ADD COLUMN source_category_code text,
    ADD COLUMN source_data jsonb NOT NULL DEFAULT '{}',
    ADD CONSTRAINT publisher_source_codes_category_fkey
        FOREIGN KEY (source, source_category_code)
        REFERENCES dw.publisher_source_categories(source, source_category_code);
CREATE INDEX publisher_source_codes_publisher_idx ON dw.publisher_source_codes(publisher_code);

ALTER TABLE dw.publishers
    DROP CONSTRAINT publishers_reference_code,
    ALTER COLUMN code SET DEFAULT uuidv7()::text,
    ADD COLUMN category_source text NOT NULL DEFAULT 'manual';
ALTER TABLE dw.publisher_categories ADD COLUMN sort_order integer;

CREATE TEMP TABLE unified_reference ON COMMIT DROP AS
SELECT p.code, p.name, p.category_code AS source_category_code
FROM dw.publishers p;

CREATE TEMP TABLE unified_duplicates(old_code text PRIMARY KEY, publisher_code text NOT NULL) ON COMMIT DROP;
INSERT INTO unified_duplicates(old_code, publisher_code) VALUES
    ('1609', '1447'), ('2723', '1042'), ('2835', '1152');

INSERT INTO dw.publisher_source_categories(source, source_category_code, name, sort_order)
SELECT 'reference', code, name, code::integer FROM dw.publisher_categories;

INSERT INTO dw.publisher_source_codes(source, source_code, publisher_code,
    source_name, source_category_code, source_data)
SELECT 'reference', r.code, coalesce(d.publisher_code, r.code), r.name,
    r.source_category_code,
    jsonb_build_object('code', r.code, 'name', r.name, 'ccode', r.source_category_code,
        'category', c.name, 'type', 'section')
FROM unified_reference r
JOIN dw.publisher_categories c ON c.code = r.source_category_code
LEFT JOIN unified_duplicates d ON d.old_code = r.code;

CREATE TEMP TABLE unified_bigkinds (
    code text PRIMARY KEY, rownum numeric, area text, gubun_code text,
    gubun_sort_num text, area_code text, gubun text, name text
) ON COMMIT DROP;
INSERT INTO unified_bigkinds(code,rownum,area,gubun_code,gubun_sort_num,area_code,gubun,name) VALUES
    ('01100101','1.0','서울','10','010','10','전국일간지','경향신문'),
    ('01100201','2.0','서울','10','010','10','전국일간지','국민일보'),
    ('01100301','3.0','서울','10','010','10','전국일간지','내일신문'),
    ('01100401','4.0','서울','10','010','10','전국일간지','동아일보'),
    ('01100501','5.0','서울','10','010','10','전국일간지','문화일보'),
    ('01100611','6.0','서울','10','010','10','전국일간지','서울신문'),
    ('01100701','7.0','서울','10','010','10','전국일간지','세계일보'),
    ('01100751','8.0','서울','10','010','10','전국일간지','아시아투데이'),
    ('01100801','9.0','서울','10','010','10','전국일간지','조선일보'),
    ('01100901','10.0','서울','10','010','10','전국일간지','중앙일보'),
    ('01101001','11.0','서울','10','010','10','전국일간지','한겨레'),
    ('01101101','12.0','서울','10','010','10','전국일간지','한국일보'),
    ('02100051','13.0','서울','20','020','10','경제일간지','대한경제'),
    ('02100101','14.0','서울','20','020','10','경제일간지','매일경제'),
    ('02100201','15.0','서울','20','020','10','경제일간지','머니투데이'),
    ('02100401','16.0','서울','20','020','10','경제일간지','메트로경제'),
    ('02100861','17.0','서울','20','020','10','경제일간지','브릿지경제'),
    ('02100311','18.0','서울','20','020','10','경제일간지','서울경제'),
    ('02100801','19.0','서울','20','020','10','경제일간지','아시아경제'),
    ('02100851','20.0','서울','20','020','10','경제일간지','아주경제'),
    ('04101008','21.0','서울','20','020','10','경제일간지','이데일리'),
    ('02100351','22.0','서울','20','020','10','경제일간지','이투데이'),
    ('02100501','23.0','서울','20','020','10','경제일간지','파이낸셜뉴스'),
    ('02100601','24.0','서울','20','020','10','경제일간지','한국경제'),
    ('02100701','25.0','서울','20','020','10','경제일간지','헤럴드경제'),
    ('01300101','26.0','강원','30','030','30','지역일간지','강원도민일보'),
    ('01300201','27.0','강원','30','030','30','지역일간지','강원일보'),
    ('01200501','28.0','경기','30','030','20','지역일간지','경기신문'),
    ('01200101','29.0','경기','30','030','20','지역일간지','경기일보'),
    ('01500151','30.0','경상','30','030','50','지역일간지','경남도민일보'),
    ('01500051','31.0','경상','30','030','50','지역일간지','경남신문'),
    ('01500101','32.0','경상','30','030','50','지역일간지','경남일보'),
    ('01501101','33.0','경상','30','030','50','지역일간지','경북도민일보'),
    ('01501201','34.0','경상','30','030','50','지역일간지','경북매일신문'),
    ('01500201','35.0','경상','30','030','50','지역일간지','경북일보'),
    ('01500301','36.0','경상','30','030','50','지역일간지','경상일보'),
    ('01200201','37.0','경기','30','030','20','지역일간지','경인일보'),
    ('01620001','38.0','전라','30','030','60','지역일간지','광남일보'),
    ('01600201','39.0','전라','30','030','60','지역일간지','광주매일신문'),
    ('01600301','40.0','전라','30','030','60','지역일간지','광주일보'),
    ('01500401','41.0','경상','30','030','50','지역일간지','국제신문'),
    ('01400801','42.0','충청','30','030','40','지역일간지','금강일보'),
    ('01200301','43.0','경기','30','030','20','지역일간지','기호일보'),
    ('01600451','44.0','전라','30','030','60','지역일간지','남도일보'),
    ('01501001','45.0','경상','30','030','50','지역일간지','대구신문'),
    ('01500501','46.0','경상','30','030','50','지역일간지','대구일보'),
    ('01400201','47.0','충청','30','030','40','지역일간지','대전일보'),
    ('01400301','48.0','충청','30','030','40','지역일간지','동양일보'),
    ('01500601','49.0','경상','30','030','50','지역일간지','매일신문'),
    ('01600501','50.0','전라','30','030','60','지역일간지','무등일보'),
    ('01500701','51.0','경상','30','030','50','지역일간지','부산일보'),
    ('01600601','52.0','전라','30','030','60','지역일간지','새전북신문'),
    ('01500801','53.0','경상','30','030','50','지역일간지','영남일보'),
    ('01500901','54.0','경상','30','030','50','지역일간지','울산매일'),
    ('01501301','55.0','경상','30','030','50','지역일간지','울산신문'),
    ('01200401','56.0','경기','30','030','20','지역일간지','인천일보'),
    ('01600801','57.0','전라','30','030','60','지역일간지','전남일보'),
    ('01600901','58.0','전라','30','030','60','지역일간지','전라일보'),
    ('01601001','59.0','전라','30','030','60','지역일간지','전북도민일보'),
    ('01601101','60.0','전라','30','030','60','지역일간지','전북일보'),
    ('01700101','61.0','제주','30','030','70','지역일간지','제민일보'),
    ('01700401','62.0','제주','30','030','70','지역일간지','제주일보'),
    ('01400351','63.0','충청','30','030','40','지역일간지','중도일보'),
    ('01400401','64.0','충청','30','030','40','지역일간지','중부매일'),
    ('01400501','65.0','경기','30','030','20','지역일간지','중부일보'),
    ('01400551','66.0','충청','30','030','40','지역일간지','충북일보'),
    ('01400601','67.0','충청','30','030','40','지역일간지','충청일보'),
    ('01400101','68.0','충청','30','030','40','지역일간지','충청타임즈'),
    ('01400701','69.0','충청','30','030','40','지역일간지','충청투데이'),
    ('01700201','70.0','제주','30','030','70','지역일간지','한라일보'),
    ('05520352','71.0','충청','31','031','40','지역주간지','당진시대'),
    ('05300152','72.0','강원','31','031','30','지역주간지','설악신문'),
    ('05510752','73.0','경상','31','031','50','지역주간지','영주시민신문'),
    ('05202752','74.0','경기','31','031','20','지역주간지','평택시민신문'),
    ('05420702','75.0','충청','31','031','40','지역주간지','홍성신문'),
    ('08100101','76.0','서울','40','040','10','방송사','KBS'),
    ('08100201','77.0','서울','40','040','10','방송사','MBC'),
    ('08200101','78.0','경기','40','040','20','방송사','OBS'),
    ('08100301','79.0','서울','40','040','10','방송사','SBS'),
    ('08100401','80.0','서울','40','040','10','방송사','YTN'),
    ('07100702','81.0','서울','50','050','10','전문지','기자협회보'),
    ('07101201','82.0','서울','50','050','10','전문지','디지털타임스'),
    ('07100251','83.0','서울','50','050','10','전문지','미디어오늘'),
    ('07200502','84.0','서울','50','050','10','전문지','소년한국일보'),
    ('06100252','85.0','서울','50','050','10','전문지','시사IN'),
    ('01101202','86.0','서울','50','050','10','전문지','일요신문'),
    ('07100501','87.0','서울','50','050','10','전문지','전자신문'),
    ('06101202','88.0','서울','50','050','10','전문지','주간한국'),
    ('06101302','89.0','서울','50','050','10','전문지','한겨레21'),
    ('07100502','90.0','서울','50','050','10','전문지','환경일보'),
    ('10100101','91.0','서울','100','100','10','스포츠신문','스포츠서울'),
    ('10100401','92.0','서울','100','100','10','스포츠신문','스포츠월드'),
    ('10100301','93.0','서울','100','100','10','스포츠신문','스포츠한국'),
    ('04100958','94.0','서울','110','110','10','인터넷신문','EBN'),
    ('07100602','95.0','서울','110','110','10','인터넷신문','PD-저널'),
    ('04100058','96.0','서울','110','110','10','인터넷신문','노컷뉴스'),
    ('07100001','97.0','서울','110','110','10','인터넷신문','뉴스펭귄'),
    ('04100078','98.0','서울','110','110','10','인터넷신문','뉴스핌'),
    ('04100158','99.0','서울','110','110','10','인터넷신문','데일리안'),
    ('04100608','100.0','서울','110','110','10','인터넷신문','브레이크뉴스'),
    ('04101808','101.0','서울','110','110','10','인터넷신문','비즈워치'),
    ('04102008','102.0','서울','110','110','10','인터넷신문','쿠키뉴스'),
    ('04104008','103.0','서울','110','110','10','인터넷신문','프레시안'),
    ('04400108','104.0','서울','110','110','10','인터넷신문','헬로디디')
;

INSERT INTO dw.publisher_source_categories(source, source_category_code, name, sort_order)
SELECT 'bigkinds', gubun_code, min(gubun), gubun_code::integer
FROM unified_bigkinds GROUP BY gubun_code;

CREATE TEMP TABLE unified_aliases(source_name text PRIMARY KEY, publisher_code text NOT NULL) ON COMMIT DROP;
INSERT INTO unified_aliases(source_name, publisher_code) VALUES
    ('메트로경제', '2286'), ('울산매일', '2184'), ('PD-저널', '2042');

CREATE TEMP TABLE unified_bk_only(code text PRIMARY KEY, name text, category_code text) ON COMMIT DROP;
INSERT INTO unified_bk_only(code,name,category_code) VALUES
    ('01620001','광남일보','general_daily'),
    ('01700201','한라일보','general_daily'),
    ('05300152','설악신문','online_specialty'),
    ('05510752','영주시민신문','online_specialty'),
    ('05202752','평택시민신문','online_specialty'),
    ('05420702','홍성신문','online_specialty'),
    ('07100502','환경일보','online_specialty');

INSERT INTO dw.publisher_categories(code,name,sort_order) VALUES
    ('wire','통신사',1), ('general_daily','종합일간지',2), ('economic','경제지',3),
    ('broadcast','방송사',4), ('online_specialty','온라인 뉴스/전문지',5);

CREATE TEMP TABLE unified_type_overrides(code text PRIMARY KEY, category_code text NOT NULL) ON COMMIT DROP;
INSERT INTO unified_type_overrides(code,category_code) VALUES
    ('1001','wire'),
    ('1003','wire'),
    ('1029','online_specialty'),
    ('1030','online_specialty'),
    ('1049','broadcast'),
    ('1092','online_specialty'),
    ('1138','online_specialty'),
    ('1348','wire'),
    ('1293','online_specialty'),
    ('1408','broadcast'),
    ('1416','broadcast'),
    ('1421','wire'),
    ('1427','broadcast'),
    ('1438','broadcast'),
    ('1451','broadcast'),
    ('1464','broadcast'),
    ('1470','broadcast'),
    ('1655','broadcast'),
    ('1657','broadcast'),
    ('1659','broadcast'),
    ('1660','broadcast'),
    ('1661','broadcast'),
    ('2002','wire'),
    ('2015','online_specialty'),
    ('2016','online_specialty'),
    ('2017','online_specialty'),
    ('2019','broadcast'),
    ('2025','wire'),
    ('2036','online_specialty'),
    ('2046','online_specialty'),
    ('2048','online_specialty'),
    ('2069','online_specialty'),
    ('2085','online_specialty'),
    ('2096','online_specialty'),
    ('2110','online_specialty'),
    ('2137','online_specialty'),
    ('2141','online_specialty'),
    ('2177','online_specialty'),
    ('2179','online_specialty'),
    ('2214','online_specialty'),
    ('2227','economic'),
    ('2234','broadcast'),
    ('2267','online_specialty'),
    ('2274','broadcast'),
    ('2286','economic'),
    ('2291','wire'),
    ('2314','broadcast'),
    ('2345','online_specialty'),
    ('2351','online_specialty'),
    ('2404','online_specialty'),
    ('2405','online_specialty'),
    ('2429','online_specialty'),
    ('2439','online_specialty'),
    ('2452','online_specialty'),
    ('2497','online_specialty'),
    ('2505','online_specialty'),
    ('2506','online_specialty'),
    ('2513','online_specialty'),
    ('2519','online_specialty'),
    ('2522','online_specialty'),
    ('2525','online_specialty'),
    ('2544','broadcast'),
    ('2568','online_specialty'),
    ('2569','online_specialty'),
    ('2586','online_specialty'),
    ('2650','online_specialty'),
    ('2657','online_specialty'),
    ('2678','online_specialty'),
    ('2688','online_specialty'),
    ('2699','online_specialty'),
    ('2704','online_specialty'),
    ('2714','online_specialty'),
    ('2716','online_specialty'),
    ('2748','online_specialty'),
    ('2752','online_specialty'),
    ('2795','online_specialty'),
    ('2808','online_specialty'),
    ('2839','online_specialty'),
    ('2855','online_specialty'),
    ('2883','online_specialty'),
    ('2894','online_specialty'),
    ('2904','online_specialty')
;

-- 원분류는 보존하고 혼합 분류의 매체 유형은 언론사별로 지정
UPDATE dw.publishers p SET
    category_code = coalesce(o.category_code,
        CASE r.source_category_code
            WHEN '1' THEN 'general_daily'
            WHEN '2' THEN 'broadcast'
            WHEN '3' THEN 'economic'
            WHEN '6' THEN 'general_daily'
            ELSE 'online_specialty' END),
    category_source = 'unified'
FROM unified_reference r
LEFT JOIN unified_type_overrides o ON o.code = r.code
WHERE p.code = r.code;

UPDATE dw.publishers SET category_code = 'economic' WHERE code = '2286';

INSERT INTO dw.publishers(code,name,category_code,category_source)
SELECT code,name,category_code,'bigkinds' FROM unified_bk_only;
INSERT INTO dw.publishers(name,category_code,category_source)
VALUES ('서울와이어','economic','manual');

INSERT INTO dw.publisher_source_codes(source,source_code,publisher_code,
    source_name,source_category_code,source_data)
SELECT 'bigkinds', b.code,
    coalesce(a.publisher_code, r.code, x.code), b.name, b.gubun_code,
    jsonb_build_object('CODE',b.code,'ROWNUM',b.rownum,'AREA',b.area,
        'GUBUN_CODE',b.gubun_code,'GUBUN_SORT_NUM',b.gubun_sort_num,
        'AREA_CODE',b.area_code,'GUBUN',b.gubun,'NAME',b.name)
FROM unified_bigkinds b
LEFT JOIN unified_aliases a ON a.source_name = b.name
LEFT JOIN (SELECT name,min(code) AS code FROM unified_reference GROUP BY name) r ON r.name = b.name
LEFT JOIN unified_bk_only x ON x.name = b.name;

UPDATE dw.publisher_source_codes s
SET publisher_code = d.publisher_code
FROM unified_duplicates d
WHERE s.publisher_code = d.old_code;
UPDATE dw.publisher_domains d
SET publisher_code = r.publisher_code
FROM unified_duplicates r
WHERE d.publisher_code = r.old_code;
UPDATE dw.articles a
SET publisher_code = r.publisher_code,
    publisher = p.name
FROM unified_duplicates r JOIN dw.publishers p ON p.code = r.publisher_code
WHERE a.publisher_code = r.old_code;

CREATE TEMP TABLE unified_domains(domain text PRIMARY KEY, publisher_code text NOT NULL) ON COMMIT DROP;
INSERT INTO unified_domains(domain,publisher_code) VALUES
    ('cctoday.co.kr','2160'),
    ('ebn.co.kr','2093'),
    ('edu.chosun.com','2546'),
    ('gwangnam.co.kr','01620001'),
    ('hani.co.kr','1028'),
    ('hidomin.com','2377'),
    ('hkbs.co.kr','07100502'),
    ('hsnews.co.kr','05420702'),
    ('idomin.com','2163'),
    ('ihalla.com','01700201'),
    ('imnews.imbc.com','1214'),
    ('inews365.com','2231'),
    ('isplus.com','1241'),
    ('iusm.co.kr','2184'),
    ('jeonmae.co.kr','2844'),
    ('joynews24.com','2712'),
    ('kjdaily.com','2263'),
    ('kookje.co.kr','1658'),
    ('ksilbo.co.kr','2277'),
    ('kwangju.co.kr','2857'),
    ('mydaily.co.kr','1117'),
    ('namdonews.com','2539'),
    ('news.bizwatch.co.kr','1648'),
    ('news.jtbc.co.kr','1437'),
    ('newspenguin.com','2849'),
    ('newsworks.co.kr','2525'),
    ('osen.co.kr','1109'),
    ('pttimes.com','05202752'),
    ('sisaweek.com','2337'),
    ('soraknews.co.kr','05300152'),
    ('sports.hankooki.com','2359'),
    ('sports.khan.co.kr','1144'),
    ('sportschosun.com','1076'),
    ('sportsworldi.com','1396'),
    ('xportsnews.com','1311'),
    ('yjinews.com','05510752')
;

INSERT INTO unified_domains(domain,publisher_code)
SELECT 'seoulwire.com',code FROM dw.publishers WHERE name = '서울와이어';

INSERT INTO dw.publisher_domains(domain,publisher_code,evidence)
SELECT u.domain,u.publisher_code,
    jsonb_build_object('method','source_identity','publisher_code',u.publisher_code)
FROM unified_domains u
ON CONFLICT (domain) DO UPDATE SET
    publisher_code = EXCLUDED.publisher_code,
    evidence = dw.publisher_domains.evidence || EXCLUDED.evidence;

-- 원문 URL과 제공사 코드가 동일한 경우에만 신규 도메인 연결
WITH inferred AS (
    SELECT dw.article_publisher_domain(s.original_url) AS domain,
        min(c.publisher_code) AS publisher_code
    FROM dw.article_sources s
    JOIN dw.publisher_source_codes c ON c.source = 'bigkinds'
        AND c.source_code = split_part(s.source_id,'.',1)
    WHERE s.source = 'bigkinds' AND s.original_url IS NOT NULL
    GROUP BY 1 HAVING count(DISTINCT c.publisher_code) = 1
)
INSERT INTO dw.publisher_domains(domain,publisher_code,evidence)
SELECT domain,publisher_code,jsonb_build_object('method','bigkinds_source_id')
FROM inferred WHERE domain IS NOT NULL
ON CONFLICT (domain) DO UPDATE SET
    publisher_code = coalesce(dw.publisher_domains.publisher_code, EXCLUDED.publisher_code),
    evidence = dw.publisher_domains.evidence || EXCLUDED.evidence;

-- 제공사 식별자는 원문 URL이 없는 빅카인즈 기사에도 유효
CREATE FUNCTION dw.resolve_article_publisher(
    article_source text, article_source_id text, article_url text, article_original_url text
) RETURNS text LANGUAGE sql AS $$
    SELECT coalesce(
        (SELECT publisher_code FROM dw.publisher_source_codes
         WHERE source = 'bigkinds' AND source_code = split_part(article_source_id,'.',1)
           AND article_source = 'bigkinds'),
        dw.resolve_publisher_code(dw.article_publisher_identifier(article_original_url)),
        dw.resolve_publisher_code(dw.article_publisher_identifier(article_url))
    );
$$;

CREATE OR REPLACE FUNCTION dw.assign_search_publisher() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE resolved text; display_name text;
BEGIN
    IF NEW.provider <> 'naver' OR NEW.channel <> 'news' THEN RETURN NEW; END IF;
    resolved := coalesce(
        dw.resolve_article_publisher('naver_news',NEW.source_id,
            NEW.data->>'url',NEW.data->>'original_url'),
        dw.resolve_publisher_code(NEW.data->>'publisher_domain'),
        dw.resolve_publisher_code(NEW.data->>'publisher_code'));
    SELECT name INTO display_name FROM dw.publishers WHERE code = resolved;
    NEW.data := NEW.data || jsonb_build_object(
        'publisher_code',resolved,'publisher',coalesce(display_name,NEW.data->>'publisher'));
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION dw.sync_article_source_publisher() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE resolved text; display_name text;
BEGIN
    resolved := dw.resolve_article_publisher(NEW.source,NEW.source_id,NEW.url,NEW.original_url);
    IF resolved IS NOT NULL THEN
        SELECT name INTO display_name FROM dw.publishers WHERE code = resolved;
        UPDATE dw.articles SET publisher_code = resolved, publisher = display_name
        WHERE id = NEW.article_id
            AND (publisher_code IS DISTINCT FROM resolved OR publisher IS DISTINCT FROM display_name);
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION dw.sync_publisher_source_code() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source = 'naver' THEN
        UPDATE dw.search_items SET data = data
        WHERE provider = 'naver' AND channel = 'news'
          AND dw.article_publisher_identifier(coalesce(nullif(data->>'original_url',''),data->>'url'))
              = 'naver:' || NEW.source_code;
    ELSIF NEW.source = 'bigkinds' THEN
        UPDATE dw.article_sources SET original_url = original_url
        WHERE source = 'bigkinds' AND split_part(source_id,'.',1) = NEW.source_code;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION dw.sync_publisher_domain() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE dw.search_items SET data = data
    WHERE provider = 'naver' AND channel = 'news'
      AND (data->>'publisher_domain' = NEW.domain
           OR dw.article_publisher_domain(data->>'original_url') = NEW.domain);
    UPDATE dw.article_sources s SET original_url = original_url
    WHERE dw.article_publisher_domain(coalesce(nullif(s.original_url,''),s.url)) = NEW.domain;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION dw.sync_publisher_name() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE dw.articles SET publisher = NEW.name WHERE publisher_code = NEW.code;
    UPDATE dw.search_items SET data = data
    WHERE provider = 'naver' AND channel = 'news'
      AND dw.resolve_article_publisher('naver_news',source_id,data->>'url',data->>'original_url') = NEW.code;
    RETURN NEW;
END;
$$;

-- 저장된 적응형 설정을 기존 식별자와 통합 식별자에서 함께 조회 가능하도록 복사
CREATE TEMP TABLE unified_scope_remap(identifier text PRIMARY KEY, publisher_code text NOT NULL) ON COMMIT DROP;
INSERT INTO unified_scope_remap(identifier,publisher_code)
SELECT domain,publisher_code FROM dw.publisher_domains WHERE publisher_code IS NOT NULL
ON CONFLICT DO NOTHING;
INSERT INTO unified_scope_remap(identifier,publisher_code)
SELECT old_code,publisher_code FROM unified_duplicates
ON CONFLICT DO NOTHING;
WITH candidates AS (
    SELECT DISTINCT ON (new_scope,p.identifier)
        left(encode(sha256(convert_to(r.publisher_code,'UTF8')),'hex'),16)
            || substring(p.scope from 17) AS new_scope,
        p.identifier,p.properties,
        p.context || jsonb_build_object('publisher_code',r.publisher_code,'previous_scope',p.scope) AS context,
        p.updated_at
    FROM ops.publisher_adaptive_profiles p
    JOIN unified_scope_remap r
      ON left(p.scope,16) = left(encode(sha256(convert_to(r.identifier,'UTF8')),'hex'),16)
    WHERE p.scope <> left(encode(sha256(convert_to(r.publisher_code,'UTF8')),'hex'),16)
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

DELETE FROM dw.publishers p USING unified_duplicates d WHERE p.code = d.old_code;
DELETE FROM dw.publisher_categories WHERE code IN ('1','2','3','4','5','6','7','8');
ALTER TABLE dw.publisher_categories ALTER COLUMN sort_order SET NOT NULL;

UPDATE dw.article_sources SET original_url = original_url;
UPDATE dw.search_items SET data = data WHERE provider = 'naver' AND channel = 'news';

COMMIT;
