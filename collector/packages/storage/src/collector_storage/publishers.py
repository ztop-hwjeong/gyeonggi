import re
from urllib.parse import parse_qs, urlsplit

NAVER_NEWS_HOSTS = {"n.news.naver.com", "news.naver.com", "m.news.naver.com"}

def publisher_code(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.lower().removeprefix("www.")
    if host in NAVER_NEWS_HOSTS:
        article = re.search(r"/article/(\d{3})/\d+", parsed.path)
        oid = article[1] if article else parse_qs(parsed.query).get("oid", [""])[0]
        return f"naver:{oid}" if re.fullmatch(r"\d{3}", oid) else None
    return host
