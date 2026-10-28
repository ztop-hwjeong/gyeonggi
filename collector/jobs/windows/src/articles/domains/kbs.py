from urllib.parse import parse_qs, urlsplit

from scrapling import Selector

from articles.matching import normalized_text
from articles.models import ArticleSeed


class KbsBodyPolicy:
    hosts: tuple[str, ...] = ("news.kbs.co.kr",)

    def has_no_text_body(
        self, seed: ArticleSeed, page: Selector, title: str, url: str, markup: str
    ) -> bool:
        original = urlsplit(str(seed.original_url))
        news_id = parse_qs(urlsplit(url).query).get("ncd", [""])[0]
        original_id = parse_qs(original.query).get("ncd", [""])[0]
        body_elements = page.css("#cont_newstext")
        return bool(
            original.hostname in self.hosts
            and news_id.isdecimal()
            and news_id == original_id
            and f"_{news_id}.mp4" in markup
            and normalized_text(title) == normalized_text(seed.title)
            and body_elements
            and all(not node.get_all_text(strip=True).strip() for node in body_elements)
        )
