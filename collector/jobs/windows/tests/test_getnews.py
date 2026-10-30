from scrapling import Selector

from articles.domains.getnews import GetnewsBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings

URL = "https://www.getnews.co.kr/news/articleView.html?idxno=885362"
CAPTION = "교복 구매 과정의 점검 및 제도 개선 방안을 논의하고 있다. 사진=경기도교육청 제공"


def test_getnews_keeps_article_and_caption_without_toolbar(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <section class="articleViewCon article-view-content">
      <div class="social-group">SNS 기사보내기 Share</div>
      <div class="google-preferences-wrap">Google에서 선호하는 출처로 추가</div></section>
    <article id="article-view-content-div" class="article-veiw-body view-page"><p>{CAPTION}</p>
      <p>{article_text}</p></article>
    <div class="article-more">다른기사 보기</div>
    """
    result = GetnewsBodyPolicy().extract_body(
        seeded, Selector(content=markup), seeded.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert result.evidence.verified
    assert CAPTION in result.text
    assert normalized_text(article_text) in normalized_text(result.text)
    assert "SNS 기사보내기" not in result.text
    assert "Google에서 선호" not in result.text


def test_getnews_delegates_ambiguous_article_body(seed) -> None:
    markup = """
    <article id="article-view-content-div" class="article-veiw-body view-page">첫 본문</article>
    <article id="article-view-content-div" class="article-veiw-body view-page">둘째 본문</article>
    """

    assert (
        GetnewsBodyPolicy().extract_body(
            seed, Selector(content=markup), seed.title, URL, markup, ExtractionSettings()
        )
        is None
    )
