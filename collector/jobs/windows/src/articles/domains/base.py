from typing import Protocol

from scrapling import Selector

from articles.models import ArticleSeed


class DomainBodyPolicy(Protocol):
    hosts: tuple[str, ...]

    def has_no_text_body(
        self, seed: ArticleSeed, page: Selector, title: str, url: str, markup: str
    ) -> bool: ...
