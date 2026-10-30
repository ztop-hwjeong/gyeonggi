from scrapling import Selector

from articles.domains.hankookilbo import HankookIlboBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings

URL = "https://www.hankookilbo.com/news/article/A2026103003310005898"
CAPTION = "노사 양측과 조정위원들이 협상을 타결한 뒤 기념촬영을 하고 있다."


def test_hankookilbo_removes_only_image_zoom_button(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <div id="article-view-content" class="article-view">
      <p>{article_text}</p>
      <div class="editor-img-box"><div class="img-box"><button class="img-zoomin no-print">
        이미지 확대보기</button></div><figcaption>{CAPTION}</figcaption></div>
    </div>
    """
    result = HankookIlboBodyPolicy().extract_body(
        seeded, Selector(content=markup), seeded.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert result.evidence.verified
    assert "이미지 확대보기" not in result.text
    assert CAPTION in result.text
    assert normalized_text(article_text) in normalized_text(result.text)


def test_hankookilbo_delegates_ambiguous_article_body(seed) -> None:
    markup = """
    <div id="article-view-content" class="article-view">첫 본문</div>
    <div id="article-view-content" class="article-view">둘째 본문</div>
    """

    assert (
        HankookIlboBodyPolicy().extract_body(
            seed, Selector(content=markup), seed.title, URL, markup, ExtractionSettings()
        )
        is None
    )
