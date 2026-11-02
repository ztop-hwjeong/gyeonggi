INSERT INTO dw.publisher_domains (domain, publisher_code, evidence)
VALUES
    ('agrinet.co.kr', '2396', '{"method":"verified_og_site_name","reference_name":"한국농어민신문"}'::jsonb),
    ('www.agrinet.co.kr', '2396', '{"method":"verified_og_site_name","reference_name":"한국농어민신문"}'::jsonb),
    ('ibabynews.com', '2295', '{"method":"verified_og_site_name","reference_name":"베이비뉴스"}'::jsonb),
    ('www.ibabynews.com', '2295', '{"method":"verified_og_site_name","reference_name":"베이비뉴스"}'::jsonb),
    ('fntimes.com', '2040', '{"method":"verified_og_site_name","reference_name":"한국금융신문"}'::jsonb),
    ('www.fntimes.com', '2040', '{"method":"verified_og_site_name","reference_name":"한국금융신문"}'::jsonb),
    ('it.chosun.com', '2242', '{"method":"verified_og_site_name","reference_name":"IT조선"}'::jsonb)
ON CONFLICT (domain) DO UPDATE
SET publisher_code = EXCLUDED.publisher_code,
    evidence = dw.publisher_domains.evidence || EXCLUDED.evidence;
