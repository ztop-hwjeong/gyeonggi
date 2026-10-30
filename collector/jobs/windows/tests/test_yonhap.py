from scrapling import Selector

from articles.domains.yonhap import YonhapBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings


def test_yonhap_policy_keeps_caption_and_excludes_related_script_and_footer(
    seed, article_text
) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <article id="articleWrap"><div class="story-news article">
      <div id="newsWriterCarousel01">기자 최신 기사</div>
      <p>{article_text}</p><figure><figcaption>현장 사진 설명</figcaption></figure>
      <aside>광고 문구</aside><div class="related-zone">관련 뉴스 황현필</div>
      <p class="txt-copyright">저작권 및 댓글</p><script>추천 스크립트</script>
      <style>추천 CSS</style>
    </div></article>
    """
    result = YonhapBodyPolicy().extract_body(
        seeded,
        Selector(content=markup),
        seeded.title,
        "https://www.yna.co.kr/view/1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None and result.evidence.verified
    assert normalized_text(article_text) in normalized_text(result.text)
    assert "현장 사진 설명" in result.text
    assert all(
        value not in result.text for value in ("황현필", "저작권", "추천 스크립트", "추천 CSS")
    )


def test_yonhap_policy_returns_unverified_selected_body(seed) -> None:
    markup = (
        "<article id='articleWrap'><div class='story-news article'>다른 본문입니다.</div></article>"
    )
    result = YonhapBodyPolicy().extract_body(
        seed,
        Selector(content=markup),
        seed.title,
        "https://www.yna.co.kr/view/1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None and not result.evidence.verified
