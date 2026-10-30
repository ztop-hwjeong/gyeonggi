from scrapling import Selector

from articles.domains.busan import BusanBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings

URL = "https://www.busan.com/view/busan/view.php?code=1"


def test_busan_keeps_body_caption_and_excludes_recommendations(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <div class="article_content"><script>광고와 댓글</script><p>{article_text}</p>
      <figcaption>사진 설명</figcaption></div>
    <section>당신을 위한 추천 기사 라이브리 댓글 작성 황현필</section>
    """
    result = BusanBodyPolicy().extract_body(
        seeded, Selector(content=markup), seeded.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert normalized_text(result.text) == normalized_text(article_text + "\n사진 설명")
    assert "황현필" not in result.text
    assert result.evidence.verified


def test_busan_returns_unverified_unique_body(seed) -> None:
    markup = '<div class="article_content">전혀 다른 짧은 원문</div>'
    result = BusanBodyPolicy().extract_body(
        seed, Selector(content=markup), seed.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert not result.evidence.verified
