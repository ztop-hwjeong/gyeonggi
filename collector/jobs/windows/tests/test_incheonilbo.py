from scrapling import Selector

from articles.domains.incheonilbo import IncheonIlboBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings

URL = "https://www.incheonilbo.com/news/galleryView.html?idxno=1"


def test_incheonilbo_accepts_matched_photo_caption_only(seed) -> None:
    caption = (
        "경기도 버스노조 총파업을 예고일을 하루 앞둔 29일 조정회의가 "
        "수원에서 장시간 진행되고 있다."
    )
    seeded = seed.model_copy(
        update={"title": "[포토] 경기 버스 총파업 중대 기로", "summary": "[인천일보] " + caption}
    )
    markup = f"""
    <div class="dis-none for-content"><img alt="이미지">
      <p>{caption} /전광현 기자 photo@example.com</p></div>
    <article>이미지 슬라이드 작동버튼 SNS 기사보내기 개의 댓글</article>
    """
    result = IncheonIlboBodyPolicy().extract_body(
        seeded, Selector(content=markup), seeded.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert result.evidence.verified
    assert result.evidence.reason == "포토 캡션 제목·요약 일치"
    assert normalized_text(result.text) == normalized_text(caption)
    assert "댓글" not in result.text


def test_incheonilbo_rejects_short_caption_without_summary_match(seed) -> None:
    markup = (
        '<div class="dis-none for-content">전혀 다른 사진 설명입니다. '
        "/전광현 기자 photo@example.com</div>"
    )
    result = IncheonIlboBodyPolicy().extract_body(
        seed, Selector(content=markup), seed.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert not result.evidence.verified


def test_incheonilbo_rejects_credit_only_photo(seed) -> None:
    markup = '<div class="dis-none for-content">/전광현 기자 photo@example.com</div>'
    result = IncheonIlboBodyPolicy().extract_body(
        seed, Selector(content=markup), seed.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert not result.evidence.verified
