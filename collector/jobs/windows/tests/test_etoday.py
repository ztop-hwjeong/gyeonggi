import pytest
from scrapling import Selector

from articles.domains.etoday import ETodayBodyPolicy
from articles.extraction import ArticleExtractor, ExtractionRejectedError
from articles.matching import normalized_text
from config import ExtractionSettings


def test_etoday_policy_excludes_related_and_reporter_news(seed, article_text) -> None:
    summary = article_text[:180] + ".."
    seeded = seed.model_copy(update={"summary": summary})
    markup = f"""
    <html><body>
      <div class="articleView" itemprop="articleBody">{article_text}</div>
      <div class="relation_newslist">관련 뉴스 황현필 강연</div>
      <div class="reporter_topNews">기자 주요 뉴스 황현필</div>
    </body></html>
    """
    result = ETodayBodyPolicy().extract_body(
        seeded,
        Selector(content=markup, url="https://www.etoday.co.kr/news/view/1"),
        seeded.title,
        "https://www.etoday.co.kr/news/view/1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None
    assert normalized_text(result.text) == normalized_text(article_text)
    assert "황현필" not in result.text


def test_etoday_policy_refuses_ambiguous_article_body(seed) -> None:
    markup = """
    <div class="articleView" itemprop="articleBody">첫 본문</div>
    <div class="articleView" itemprop="articleBody">둘째 본문</div>
    """
    result = ETodayBodyPolicy().extract_body(
        seed,
        Selector(content=markup, url="https://www.etoday.co.kr/news/view/1"),
        seed.title,
        "https://www.etoday.co.kr/news/view/1",
        markup,
        ExtractionSettings(),
    )

    assert result is None


def test_etoday_verified_body_boundary_rejects_footer_summary(
    seed, article_text, repository
) -> None:
    summary = article_text[:180] + ".."
    seeded = seed.model_copy(update={"summary": summary})
    markup = f"""
    <html><title>{seeded.title}</title><body><h1>{seeded.title}</h1>
      <div class="articleView" itemprop="articleBody">전혀 다른 원문 내용입니다.</div>
      <footer>{article_text} 황현필 관련 뉴스</footer>
    </body></html>
    """
    with pytest.raises(ExtractionRejectedError, match="본문 길이 부족"):
        ArticleExtractor(repository, ExtractionSettings()).extract(
            seeded, markup.encode(), "https://www.etoday.co.kr/news/view/1"
        )
