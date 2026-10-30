from scrapling import Selector

from articles.domains.ohmynews import OhmynewsBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings


def test_ohmynews_policy_keeps_caption_and_excludes_ad_script_and_comments(
    seed, article_text
) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <div class="at_contents" itemprop="articleBody">
      <p>{article_text}</p><figure><figcaption>현장 사진 설명</figcaption></figure>
      <div id="dvCenterAd">AD 광고</div><script>추천 스크립트</script><style>추천 CSS</style>
      <div class="arc-btns-wrap">댓글 보기</div>
    </div><div class="tag_area">관련 기사 황현필</div><section>댓글 보기</section>
    """
    result = OhmynewsBodyPolicy().extract_body(
        seeded,
        Selector(content=markup),
        seeded.title,
        "https://www.ohmynews.com/NWS_Web/View/1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None and result.evidence.verified
    assert normalized_text(article_text) in normalized_text(result.text)
    assert "현장 사진 설명" in result.text
    assert all(
        value not in result.text
        for value in ("황현필", "댓글 보기", "추천 스크립트", "추천 CSS", "AD 광고")
    )


def test_ohmynews_policy_returns_unverified_selected_body(seed) -> None:
    markup = "<div class='at_contents' itemprop='articleBody'>다른 본문입니다.</div>"
    result = OhmynewsBodyPolicy().extract_body(
        seed,
        Selector(content=markup),
        seed.title,
        "https://www.ohmynews.com/NWS_Web/View/1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None and not result.evidence.verified
