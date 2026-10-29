from dataclasses import dataclass
from typing import Protocol

from scrapling import Selector

from articles.models import ArticleSeed, Evidence
from config import ExtractionSettings


@dataclass(frozen=True)
class DomainBody:
    text: str
    evidence: Evidence


class DomainBodyPolicy(Protocol):
    hosts: tuple[str, ...]

    def has_no_text_body(
        self, seed: ArticleSeed, page: Selector, title: str, url: str, markup: str
    ) -> bool: ...

    def extract_body(
        self,
        seed: ArticleSeed,
        page: Selector,
        title: str,
        url: str,
        markup: str,
        settings: ExtractionSettings,
    ) -> DomainBody | None: ...
