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


@pytest.mark.parametrize("change", ["none", "canonical", "title", "summary", "non_photo"])
def test_etoday_short_photo_requires_article_identity_and_matching_summary(seed, change):
    url = "https://www.etoday.co.kr/news/view/1"
    text = (
        "경기도 소재 중소기업 열아홉 곳이 참여한 상생마켓이 열렸다. "
        "식품과 패션 상품을 판매하고 판로 확대를 지원한다."
    )
    seeded = seed.model_copy(
        update={"title": "[포토] 경기도 상생마켓", "summary": text, "original_url": url}
    )
    canonical, title = url, seeded.title
    if change == "canonical":
        canonical += "2"
    elif change == "title":
        title = "[포토] 전혀 다른 기사"
    elif change == "summary":
        seeded = seeded.model_copy(
            update={
                "summary": "학교 교육 정책에 관한 전혀 다른 내용의 요약문으로 "
                "학부모의 참여와 교육과정 개선을 다루는 기사입니다."
            }
        )
    elif change == "non_photo":
        seeded = seeded.model_copy(update={"title": "경기도 상생마켓"})
        title = seeded.title
    markup = (
        f'<link rel="canonical" href="{canonical}">'
        f'<div class="articleView" itemprop="articleBody">{text}</div>'
    )
    result = ETodayBodyPolicy().extract_body(
        seeded, Selector(content=markup), title, url, markup, ExtractionSettings()
    )
    assert result is not None
    assert result.evidence.verified is (change == "none")
