from scrapling import Selector

from articles.domains.thepublic import ThePublicBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings

URL = "https://www.thepublic.kr/news/articleView.html?idxno=1"
ARTICLE_OPEN = '<article class="article-view-content-div article-veiw-body view-page articleBody">'


def test_thepublic_keeps_body_caption_and_excludes_comments(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <article class="article-view-content-div article-veiw-body view-page articleBody">
      <script>댓글과 추천은 본문이 아님</script><p>{article_text}</p>
      <figcaption>사진 설명</figcaption>
    </article><div>개의 댓글 황현필 추천 기사</div>
    """
    result = ThePublicBodyPolicy().extract_body(
        seeded,
        Selector(content=markup),
        seeded.title,
        URL,
        markup,
        ExtractionSettings(),
    )

    assert result is not None
    assert normalized_text(result.text) == normalized_text(article_text + "\n사진 설명")
    assert "황현필" not in result.text
    assert result.evidence.verified


def test_thepublic_returns_unverified_unique_body(seed) -> None:
    markup = ARTICLE_OPEN + "전혀 다른 짧은 원문</article>"
    result = ThePublicBodyPolicy().extract_body(
        seed, Selector(content=markup), seed.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert not result.evidence.verified
