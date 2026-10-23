from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from lxml.html import HtmlElement
from scrapling.core.storage import StorageSystemMixin
from scrapling.core.utils._utils import _StorageTools

from articles.storage import DetailRepository


@dataclass(eq=False)
class ProfileContext:
    publisher: str
    origin: str
    source_id: str
    url: str
    validation: dict[str, Any] = field(default_factory=dict)


@lru_cache(maxsize=1)
class PostgresAdaptiveStorage(StorageSystemMixin):
    def __init__(self, repository: DetailRepository, scope: str, context: ProfileContext, url: str):
        super().__init__(url)
        self._repository = repository
        self._scope = scope
        self._context = context

    def retrieve(self, identifier: str) -> dict[str, Any] | None:
        return self._repository.read_profile(self._scope, identifier)

    def save(self, element: HtmlElement, identifier: str) -> None:
        if not self._context.validation.get("verified"):
            raise ValueError("검증을 통과한 adaptive 요소만 저장 가능")
        self._repository.save_profile(
            self._scope,
            identifier,
            _StorageTools.element_to_dict(element),
            {
                "publisher": self._context.publisher,
                "origin": self._context.origin,
                "source_id": self._context.source_id,
                "url": self._context.url,
                "validation": self._context.validation,
            },
        )
