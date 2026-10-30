from scrapling import Selector

from articles.domains.newsis import NewsisBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings


def test_newsis_policy_keeps_caption_and_excludes_viewer_footer(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <div class="articleView"><div class="view" itemprop="articleBody"><div class="viewer"><article>
      <p>{article_text}</p><figure><figcaption>현장 사진 설명</figcaption></figure>
      <script>광고 코드</script><style>추천 CSS</style>
    </article><div class="viewerBottom">저작권</div></div></div></div>
    <div class="rankNews">많이 본 뉴스 황현필</div>
    """
    result = NewsisBodyPolicy().extract_body(
        seeded,
        Selector(content=markup),
        seeded.title,
        "https://www.newsis.com/view/1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None and result.evidence.verified
    assert normalized_text(article_text) in normalized_text(result.text)
    assert "현장 사진 설명" in result.text
    assert all(value not in result.text for value in ("저작권", "황현필", "광고 코드", "추천 CSS"))


def test_newsis_policy_returns_unverified_selected_body(seed) -> None:
    markup = """
    <div class='articleView'><div class='view' itemprop='articleBody'><div class='viewer'>
      <article>다른 본문입니다.</article>
    </div></div></div>
    """
    result = NewsisBodyPolicy().extract_body(
        seed,
        Selector(content=markup),
        seed.title,
        "https://www.newsis.com/view/1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None and not result.evidence.verified
