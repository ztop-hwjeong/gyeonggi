from scrapling import Selector

from articles.domains.kyeongin import KyeonginBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings

URL = "https://www.kyeongin.com/article/1773712"
TITLE = "[포토] 파업 예고한 경기도 버스노조"
CAPTION = (
    "경기도 내 버스업체 노사의 총파업 여부를 결정할 최종 조정회의가 열리는 29일 "
    "수원역 앞 버스정류장 전광판에 파업 관련 안내 문구가 나오고 있다."
)


def test_kyeongin_accepts_caption_with_exact_photo_title_and_canonical_url(seed) -> None:
    seeded = seed.model_copy(update={"title": TITLE, "summary": "[사진기사]", "original_url": URL})
    markup = f"""
    <link rel="canonical" href="{URL}"><figcaption class="caption">{CAPTION}
      2026.10.29 /최은성기자 ces7198@kyeongin.com</figcaption>
    <section>추천 기사 SNS 댓글</section>
    """
    result = KyeonginBodyPolicy().extract_body(
        seeded, Selector(content=markup), seeded.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert result.evidence.verified
    assert result.evidence.reason == "포토 캡션 제목·URL 일치"
    assert normalized_text(result.text) == normalized_text(CAPTION)


def test_kyeongin_rejects_mismatched_canonical_url(seed) -> None:
    seeded = seed.model_copy(update={"title": TITLE, "summary": "[사진기사]", "original_url": URL})
    markup = (
        '<link rel="canonical" href="https://www.kyeongin.com/article/999">'
        f'<figcaption class="caption">{CAPTION}</figcaption>'
    )
    result = KyeonginBodyPolicy().extract_body(
        seeded, Selector(content=markup), seeded.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert not result.evidence.verified


def test_kyeongin_rejects_credit_only_caption(seed) -> None:
    seeded = seed.model_copy(update={"title": TITLE, "summary": "[사진기사]", "original_url": URL})
    markup = (
        f'<link rel="canonical" href="{URL}"><figcaption class="caption">'
        "2026.10.29 /최은성기자 ces7198@kyeongin.com</figcaption>"
    )
    result = KyeonginBodyPolicy().extract_body(
        seeded, Selector(content=markup), seeded.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert not result.evidence.verified


def test_kyeongin_delegates_non_photo_article(seed) -> None:
    markup = f'<figcaption class="caption">{CAPTION}</figcaption>'

    assert (
        KyeonginBodyPolicy().extract_body(
            seed, Selector(content=markup), seed.title, URL, markup, ExtractionSettings()
        )
        is None
    )
