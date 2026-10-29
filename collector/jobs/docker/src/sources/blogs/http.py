import html
import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import parse_qs, urljoin, urlsplit

from collector_http.client import ChromiumHttpClient
from curl_cffi.requests import Response
from scrapling import Selector

from sources.blogs.models import BlogSeed


def validate_public_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise ValueError("공개 HTTP URL 필요")
    if parts.port not in (None, 80, 443):
        raise ValueError("허용되지 않은 URL 포트")
    addresses = socket.getaddrinfo(parts.hostname, None, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("공개 IP 주소 확인 실패")
    for address in addresses:
        if not ipaddress.ip_address(address[4][0]).is_global:
            raise ValueError("공개 IP 주소 필요")
    return url


def fetch_blog(
    http: ChromiumHttpClient,
    seed: BlogSeed,
    save_response: Callable[[str, str, Response], None],
) -> tuple[str, bytes, str]:
    url = validate_public_url(str(seed.url))
    response = http.request_raw("GET", url)
    save_response("html", url, response)
    if response.status_code != 200:
        raise ValueError(f"블로그 HTTP {response.status_code}")
    if urlsplit(url).hostname != "blog.naver.com":
        return url, response.content, response.headers.get("Content-Type", "")

    frame = Selector(content=response.text, url=url).css("iframe#mainFrame")
    if not frame or not frame[0].attrib.get("src"):
        raise ValueError("네이버 본문 프레임 없음")
    post_url = validate_public_url(urljoin(url, html.unescape(frame[0].attrib["src"])))
    source_parts = urlsplit(url)
    post_parts = urlsplit(post_url)
    source_path = source_parts.path.strip("/").split("/")
    query = parse_qs(post_parts.query)
    if (
        post_parts.hostname != "blog.naver.com"
        or not post_parts.path.endswith("/PostView.naver")
        or len(source_path) != 2
        or query.get("blogId") != [source_path[0]]
        or query.get("logNo") != [source_path[1]]
    ):
        raise ValueError("네이버 글 ID·호스트 불일치")
    post = http.request_raw("GET", post_url)
    save_response("postview", post_url, post)
    if post.status_code != 200:
        raise ValueError(f"네이버 PostView HTTP {post.status_code}")
    return post_url, post.content, post.headers.get("Content-Type", "")
