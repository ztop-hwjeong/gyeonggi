from scrapling import Selector

from articles.domains.kihoilbo import KihoIlboBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings

URL = "https://www.kihoilbo.co.kr/news/articleView.html?idxno=3039328"
TITLE = "경기도 버스 노사 최종 조정회의"
CAPTION = (
    "29일 수원시 영통구 경기지방노동위원회에서 경기도 버스 노사 "
    "최종 조정 회의가 진행되고 있다."
)


def test_kihoilbo_accepts_matched_unique_photo_caption(seed) -> None:
    seeded = seed.model_copy(
        update={
            "title": TITLE,
            "summary": CAPTION + "김태완 기자 lift@kihoilbo.co.kr",
            "original_url": URL,
        }
    )
    markup = f"""
    <link rel="canonical" href="{URL}"><article id="article-view-content-div">
      <figure class="photo-layout image"><figcaption class="text-left">{CAPTION}
      김태완 기자 lift@kihoilbo.co.kr</figcaption></figure>
    </article><aside>추천 기사 댓글</aside>
    """
    result = KihoIlboBodyPolicy().extract_body(
        seeded, Selector(content=markup), TITLE, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert result.evidence.verified
    assert normalized_text(result.text) == normalized_text(CAPTION)


def test_kihoilbo_delegates_non_photo_article(seed) -> None:
    markup = '<article id="article-view-content-div"><p>일반 기사 본문</p></article>'

    assert (
        KihoIlboBodyPolicy().extract_body(
            seed, Selector(content=markup), seed.title, URL, markup, ExtractionSettings()
        )
        is None
    )


def test_kihoilbo_delegates_article_with_short_paragraph(seed) -> None:
    markup = f"""
    <article id="article-view-content-div"><p>짧은 일반 기사 본문입니다.</p>
      <figure class="photo-layout image">
        <figcaption class="text-left">{CAPTION}</figcaption>
      </figure>
    </article>
    """

    assert (
        KihoIlboBodyPolicy().extract_body(
            seed, Selector(content=markup), seed.title, URL, markup, ExtractionSettings()
        )
        is None
    )


def test_kihoilbo_rejects_credit_only_or_mismatched_caption(seed) -> None:
    seeded = seed.model_copy(
        update={"title": TITLE, "summary": "다른 기사 요약 내용입니다.", "original_url": URL}
    )
    markup = (
        f'<link rel="canonical" href="{URL}"><article id="article-view-content-div">'
        '<figure class="photo-layout image"><figcaption class="text-left">'
        "김태완 기자 lift@kihoilbo.co.kr</figcaption></figure></article>"
    )
    result = KihoIlboBodyPolicy().extract_body(
        seeded, Selector(content=markup), TITLE, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert not result.evidence.verified
