from copy import deepcopy
from datetime import date
from unittest.mock import Mock

import pytest
from collector_storage.publishers import publisher_code
from pydantic import HttpUrl

from articles.models import ArticleSeed, PublisherIdentity
from articles.storage import DetailRepository


@pytest.fixture
def article_text() -> str:
    return "\n".join(
        [
            "경기도교육청은 학생들의 독서 습관을 기르기 위해 학교와 지역 도서관이 함께 "
            "참여하는 독서 교육 프로그램을 운영한다고 밝혔다. 학생들은 다양한 분야의 책을 "
            "읽고 친구들과 의견을 나누며 스스로 생각하는 힘을 기르게 된다.",
            "이번 프로그램은 지역의 교육 여건에 맞춰 학교가 직접 내용을 구성하는 방식으로 "
            "진행된다. 교사와 사서는 학생의 관심 분야를 조사하고 토론과 체험 활동을 결합한 "
            "교육 과정을 함께 준비했다.",
            "교육청은 참여 학교에 필요한 자료와 운영비를 지원하며 학부모를 대상으로 하는 "
            "설명회도 마련했다. 학생들이 학교에서 시작한 독서 활동을 가정에서도 이어갈 수 "
            "있도록 여러 지원 방법을 안내할 예정이다.",
            "참여를 희망하는 학교는 교육지원청을 통해 운영 계획을 제출할 수 있다. 담당자는 "
            "학생의 자율적인 참여와 지역 사회의 협력이 중요하다며 운영 사례를 공유하고 "
            "향후 지원 범위를 확대하겠다고 말했다.",
        ]
    )


@pytest.fixture
def seed(article_text: str) -> ArticleSeed:
    return ArticleSeed(
        source_id="test-article",
        publisher="테스트언론",
        title="경기도교육청 독서 교육 프로그램 운영",
        original_url=HttpUrl("https://example.org/news/1"),
        published_on=date(2026, 10, 23),
        summary=article_text[:180] + "..",
    )


@pytest.fixture
def article_html(seed: ArticleSeed, article_text: str) -> bytes:
    paragraphs = "".join(f"<p>{line}</p>" for line in article_text.splitlines())
    return (
        f"<html><head><title>{seed.title}</title></head><body>"
        "<nav>로그인 광고 메뉴 목록</nav>"
        f'<article id="news-body"><h1>{seed.title}</h1>{paragraphs}</article>'
        "<aside>다른 기사와 광고</aside></body></html>"
    ).encode()


@pytest.fixture
def repository() -> Mock:
    repository = Mock(spec=DetailRepository)
    repository.resolve_publisher.side_effect = lambda url: PublisherIdentity(
        code=publisher_code(url) or "unknown",
        name=None,
    )
    profiles: dict[tuple[str, str], dict] = {}

    def read(scope: str, identifier: str) -> dict | None:
        return deepcopy(profiles.get((scope, identifier)))

    def save(scope: str, identifier: str, properties: dict, context: dict) -> None:
        profiles[scope, identifier] = deepcopy(properties)

    repository.read_profile.side_effect = read
    repository.save_profile.side_effect = save
    return repository
