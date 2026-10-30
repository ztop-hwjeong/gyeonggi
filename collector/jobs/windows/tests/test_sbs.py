from scrapling import Selector

from articles.domains.sbs import SbsBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings

URL = "https://news.sbs.co.kr/news/endPage.do?news_id=N1"


def test_sbs_keeps_article_without_player_or_english_link(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <div class="main_text"><script>PIP 닫기</script><p>{article_text}</p>
      <p>(영상취재 : 이상학, 자막 : 정한욱)</p></div>
    <div class="main_text">영문 기사 보기 https://news.sbs.co.kr/english</div>
    <button>PIP 닫기</button>
    """
    result = SbsBodyPolicy().extract_body(
        seeded, Selector(content=markup), seeded.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert result.evidence.verified
    assert "영상취재" in result.text
    assert "PIP 닫기" not in result.text
    assert "영문 기사 보기" not in result.text
    assert normalized_text(article_text) in normalized_text(result.text)


def test_sbs_delegates_when_main_text_is_ambiguous(seed) -> None:
    markup = '<div class="main_text">첫 본문</div><div class="main_text">둘째 본문</div>'

    assert (
        SbsBodyPolicy().extract_body(
            seed, Selector(content=markup), seed.title, URL, markup, ExtractionSettings()
        )
        is None
    )


def test_sbs_returns_unverified_unique_body(seed) -> None:
    markup = '<div class="main_text">전혀 다른 짧은 원문</div>'
    result = SbsBodyPolicy().extract_body(
        seed, Selector(content=markup), seed.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert not result.evidence.verified


def test_sbs_accepts_only_length_failed_substantive_short_article(seed) -> None:
    short_text = "가 " * 190
    seeded = seed.model_copy(update={"summary": "가 " * 60, "original_url": URL})
    markup = f'<link rel="canonical" href="{URL}"><div class="main_text">{short_text}</div>'
    result = SbsBodyPolicy().extract_body(
        seeded, Selector(content=markup), seeded.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert result.evidence.verified
    assert result.evidence.reason == "SBS 본문 단문 제목·요약 일치"


def test_sbs_rejects_short_article_with_partial_or_wrong_title(seed) -> None:
    short_text = "가 " * 190
    seeded = seed.model_copy(update={"summary": "나 " * 60, "original_url": URL})
    markup = f'<link rel="canonical" href="{URL}"><div class="main_text">{short_text}</div>'
    result = SbsBodyPolicy().extract_body(
        seeded, Selector(content=markup), "다른 제목", URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert not result.evidence.verified
