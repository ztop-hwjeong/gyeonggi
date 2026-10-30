from scrapling import Selector

from articles.domains.imaeil import IMAEILBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings

URL = "https://www.imaeil.com/page/view/1"


def test_imaeil_keeps_body_caption_and_excludes_rank_news(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <div id="articlebody" class="articleBody"><template>광고</template><p>{article_text}</p>
      <figcaption>사진 설명</figcaption></div>
    <div class="ranknews">많이 본 뉴스 황현필</div>
    """
    result = IMAEILBodyPolicy().extract_body(
        seeded, Selector(content=markup), seeded.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert normalized_text(result.text) == normalized_text(article_text + "\n사진 설명")
    assert "황현필" not in result.text
    assert result.evidence.verified


def test_imaeil_returns_unverified_unique_body(seed) -> None:
    markup = '<div id="articlebody" class="articleBody">전혀 다른 짧은 원문</div>'
    result = IMAEILBodyPolicy().extract_body(
        seed, Selector(content=markup), seed.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert not result.evidence.verified
