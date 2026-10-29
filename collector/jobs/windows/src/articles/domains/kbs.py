from urllib.parse import parse_qs, urlsplit

from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text
from articles.models import ArticleSeed
from config import ExtractionSettings


class KbsBodyPolicy:
    hosts: tuple[str, ...] = ("news.kbs.co.kr",)

    def has_no_text_body(
        self, seed: ArticleSeed, page: Selector, title: str, url: str, markup: str
    ) -> bool:
        original = urlsplit(str(seed.original_url))
        news_id = parse_qs(urlsplit(url).query).get("ncd", [""])[0]
        original_id = parse_qs(original.query).get("ncd", [""])[0]
        body_elements = page.css("#cont_newstext")
        printable_body_elements = page.css("#mailHtmlContents .view_con_text")
        legacy_video = f"_{news_id}.mp4" in markup
        current_video = bool(
            f'newsCode: "{news_id}"' in markup
            and printable_body_elements
            and all(not node.get_all_text(strip=True).strip() for node in printable_body_elements)
            and page.css(".player-app")
        )
        return bool(
            original.hostname in self.hosts
            and news_id.isdecimal()
            and news_id == original_id
            and normalized_text(title) == normalized_text(seed.title)
            and body_elements
            and all(not node.get_all_text(strip=True).strip() for node in body_elements)
            and (legacy_video or current_video)
        )

    def extract_body(
        self,
        seed: ArticleSeed,
        page: Selector,
        title: str,
        url: str,
        markup: str,
        settings: ExtractionSettings,
    ) -> DomainBody | None:
        return None
