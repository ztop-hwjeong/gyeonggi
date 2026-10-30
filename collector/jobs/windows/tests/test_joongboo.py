from scrapling import Selector

from articles.domains.joongboo import JoongbooBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings

URL = "https://www.joongboo.com/news/articleView.html?idxno=363740800"
TITLE = "[화보] 2026 경기도 피지컬 AI 대전환 선포식"
CAPTIONS = (
    (
        "추미애 경기도지사가 피지컬 AI 기술시연 부스를 둘러보며 관계자 설명을 듣고 "
        "미래 산업 현장을 점검하고 있다."
    ),
    (
        "내빈들이 사족보행 로봇과 인사하며 전환 선포식에 참여하고 "
        "인공지능 기술을 현장에서 직접 체험하고 있다."
    ),
)


def test_joongboo_accepts_all_matched_gallery_captions(seed) -> None:
    seeded = seed.model_copy(update={"title": TITLE, "summary": "임채운 기자", "original_url": URL})
    markup = f"""
    <html><head><link rel="canonical" href="{URL}"></head><body>
    <article class="article-veiw-body view-page">
      <figure class="photo-layout image">{CAPTIONS[0]} 임채운기자</figure>
      <figure class="photo-layout image">{CAPTIONS[1]} 임채운기자</figure>
    </article><aside>추천 기사 댓글</aside></body></html>
    """
    result = JoongbooBodyPolicy().extract_body(
        seeded, Selector(content=markup), TITLE, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert result.evidence.verified
    assert result.evidence.reason == "화보 캡션 제목·URL 일치(요약 대체)"
    assert normalized_text(result.text) == normalized_text("\n".join(CAPTIONS))


def test_joongboo_rejects_mismatched_canonical_url(seed) -> None:
    seeded = seed.model_copy(update={"title": TITLE, "summary": "임채운 기자", "original_url": URL})
    markup = (
        '<html><head><link rel="canonical" href="https://www.joongboo.com/news/articleView.html?idxno=1"></head><body>'
        '<article class="article-veiw-body view-page">'
        f'<figure class="photo-layout image">{CAPTIONS[0]}</figure></article></body></html>'
    )
    result = JoongbooBodyPolicy().extract_body(
        seeded, Selector(content=markup), TITLE, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert not result.evidence.verified


def test_joongboo_rejects_credit_only_gallery(seed) -> None:
    seeded = seed.model_copy(update={"title": TITLE, "summary": "임채운 기자", "original_url": URL})
    markup = (
        f'<html><head><link rel="canonical" href="{URL}"></head><body>'
        '<article class="article-veiw-body view-page">'
        '<figure class="photo-layout image">임채운기자</figure></article></body></html>'
    )
    result = JoongbooBodyPolicy().extract_body(
        seeded, Selector(content=markup), TITLE, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert not result.evidence.verified


def test_joongboo_delegates_non_gallery_article(seed) -> None:
    markup = (
        '<article class="article-veiw-body view-page">'
        '<figure class="photo-layout image">본문</figure></article>'
    )

    assert (
        JoongbooBodyPolicy().extract_body(
            seed, Selector(content=markup), seed.title, URL, markup, ExtractionSettings()
        )
        is None
    )
