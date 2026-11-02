import pytest
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


@pytest.mark.parametrize("change", ["none", "summary", "canonical", "title", "blank"])
def test_kyeongin_short_appointment_requires_exact_complete_summary(seed, change):
    text = "■교육부 (11월 2일자)\n◇경기도교육청 제1부교육감 이상돈"
    url = "https://www.kyeongin.com/article/1773774"
    seeded = seed.model_copy(
        update={"title": "[인사] 교육부", "summary": text, "original_url": url}
    )
    canonical, title = url, seeded.title
    if change == "summary":
        seeded = seeded.model_copy(update={"summary": "다른 기관의 인사 발령 내용"})
    elif change == "canonical":
        canonical += "2"
    elif change == "title":
        title = "[인사] 다른 기관"
    elif change == "blank":
        text = ""
    markup = (
        f'<link rel="canonical" href="{canonical}"><div id="article-body"><p>{text}</p>'
        '<p>/기자 reporter@example.org</p><p class="copyright">저작권</p></div>'
    )
    result = KyeonginBodyPolicy().extract_body(
        seeded, Selector(content=markup), title, url, markup, ExtractionSettings()
    )
    assert result is not None
    assert result.evidence.verified is (change == "none")
    assert "저작권" not in result.text
    assert "reporter@" not in result.text
