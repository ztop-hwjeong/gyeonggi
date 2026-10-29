from scrapling import Selector

from articles.domains.sedaily import SedailyBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings


def test_sedaily_policy_keeps_article_body_without_hwang_recommendation(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <div id="article-body" class="view">{article_text}<figcaption>사진 설명</figcaption></div>
    <aside>보수 학부모단체, 황현필 강연 앞두고 사과 촉구 이 기사를 추천합니다.</aside>
    """
    result = SedailyBodyPolicy().extract_body(
        seeded,
        Selector(content=markup),
        seeded.title,
        "https://www.sedaily.com/NewsView/1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None
    assert normalized_text(result.text) == normalized_text(article_text)
    assert "황현필" not in result.text
    assert "사진 설명" not in result.text


def test_sedaily_policy_refuses_ambiguous_or_unverified_article_body(seed) -> None:
    markup = """
    <div id="article-body" class="view">첫 본문</div>
    <div id="article-body" class="view">황현필 추천 기사</div>
    """
    assert (
        SedailyBodyPolicy().extract_body(
            seed,
            Selector(content=markup),
            seed.title,
            "https://www.sedaily.com/NewsView/1",
            markup,
            ExtractionSettings(),
        )
        is None
    )
