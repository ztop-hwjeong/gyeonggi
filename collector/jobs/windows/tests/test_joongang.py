import pytest
from scrapling import Selector

from articles.domains.joongang import JoongangBodyPolicy
from config import ExtractionSettings


@pytest.mark.parametrize("change", ["none", "truncated", "canonical"])
def test_complete_short_personnel_notice_requires_matching_article(seed, change):
    url = "https://www.joongang.co.kr/article/25474829"
    summary = "◆행정안전부 ▶경기도 행정2부지사 손임성 ◆산림청 ▶동부지방산림청장 이광호"
    seeded = seed.model_copy(
        update={"original_url": url, "title": "[인사] 행정안전부 外", "summary": summary}
    )
    text = summary if change != "truncated" else "◆행정안전부 ▶경기도 행정2부지사 손임성"
    canonical = url if change != "canonical" else url + "1"
    markup = f'<link rel="canonical" href="{canonical}"><div id="article_body">{text}</div>'
    result = JoongangBodyPolicy().extract_body(
        seeded, Selector(content=markup), seeded.title, url, markup, ExtractionSettings()
    )
    assert result is not None
    assert result.evidence.verified is (change == "none")


@pytest.mark.parametrize("change", ["none", "canonical", "summary"])
def test_edited_title_requires_same_article_and_complete_summary(seed, article_text, change):
    url = "https://www.joongang.co.kr/article/25474783"
    seeded = seed.model_copy(update={"original_url": url})
    canonical = url if change != "canonical" else url + "2"
    if change == "summary":
        seeded = seeded.model_copy(
            update={
                "summary": "다른 지역에서 발생한 별개의 사건을 취재한 기사이며 "
                "관계자들의 반응과 조사 과정을 전하는 내용입니다."
            }
        )
    markup = f'<link rel="canonical" href="{canonical}"><div id="article_body">{article_text}</div>'
    result = JoongangBodyPolicy().extract_body(
        seeded,
        Selector(content=markup),
        "편집 과정에서 완전히 바뀐 기사 제목",
        url,
        markup,
        ExtractionSettings(),
    )
    assert result is not None
    assert result.evidence.verified is (change == "none")
