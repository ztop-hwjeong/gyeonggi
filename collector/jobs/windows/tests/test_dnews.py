from scrapling import Selector

from articles.domains.dnews import DnewsBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings

URL = "https://www.dnews.co.kr/uhtml/view.jsp?idxno=202610291349403640771"
SUBTITLE = "선도지구 새 변수 부상"
CAPTION = "성남 분당신도시 전경. / 사진 : 성남시 제공"


def test_dnews_keeps_article_subtitle_and_caption_without_surrounding_ui(
    seed, article_text
) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <div class="newsCont"><div class="dateFont">기사입력
      <span class="btnFont">폰트크기 변경</span></div>
      <div class="text"><p>{SUBTITLE}</p><td class="news_view_img_subject">{CAPTION}</td>
        <p>{article_text}</p><script>광고</script></div>
      <div class="article_news">관련기사</div>
      <div class="journalist_view_more">기자의 다른기사 보기</div>
      <b>대한경제i 앱을 다운받으세요</b>
    </div>
    """
    result = DnewsBodyPolicy().extract_body(
        seeded, Selector(content=markup), seeded.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert result.evidence.verified
    assert SUBTITLE in result.text
    assert CAPTION in result.text
    assert normalized_text(article_text) in normalized_text(result.text)
    assert "폰트크기 변경" not in result.text
    assert "관련기사" not in result.text
    assert "다른기사" not in result.text
    assert "앱을 다운" not in result.text


def test_dnews_delegates_ambiguous_article_body(seed) -> None:
    markup = """
    <div class="newsCont"><div class="text">첫 본문</div></div>
    <div class="newsCont"><div class="text">둘째 본문</div></div>
    """

    assert (
        DnewsBodyPolicy().extract_body(
            seed, Selector(content=markup), seed.title, URL, markup, ExtractionSettings()
        )
        is None
    )


def test_dnews_accepts_short_notice_only_when_summary_and_article_id_match(seed) -> None:
    short_body = (
        "▲ 김성애씨 별세, 이승우씨 모친상 = 29일, "
        "분당차병원장례식장(경기도 성남시 야탑로), 발인 31일 오전."
    )
    seeded = seed.model_copy(
        update={"summary": short_body, "original_url": URL, "title": "[부고] 이승우씨 모친상"}
    )
    markup = f"""
    <meta property="og:url" content="{URL}">
    <div class="newsCont"><div class="text"><p>{short_body}</p></div></div>
    """
    result = DnewsBodyPolicy().extract_body(
        seeded, Selector(content=markup), seeded.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert result.evidence.verified
    assert result.evidence.reason == "대한경제 단문 제목·요약·기사번호 일치"


def test_dnews_rejects_short_notice_with_partial_summary_or_different_article_id(seed) -> None:
    body = (
        "▲ 김성애씨 별세, 이승우씨 모친상 = 29일, "
        "분당차병원장례식장(경기도 성남시 야탑로), 발인 31일 오전."
    )
    seeded = seed.model_copy(
        update={"summary": body[:30], "original_url": URL, "title": "[부고] 이승우씨 모친상"}
    )
    markup = f"""
    <meta property="og:url" content="https://www.dnews.co.kr/uhtml/view.jsp?idxno=other">
    <div class="newsCont"><div class="text"><p>{body}</p></div></div>
    """
    result = DnewsBodyPolicy().extract_body(
        seeded, Selector(content=markup), seeded.title, URL, markup, ExtractionSettings()
    )

    assert result is not None
    assert not result.evidence.verified
