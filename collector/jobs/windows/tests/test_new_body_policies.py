import pytest
from scrapling import Selector

from articles.domains.ajunews import AjuNewsBodyPolicy, has_verified_official_photo_body
from articles.domains.asiatoday import AsiaTodayBodyPolicy
from articles.domains.kado import KadoBodyPolicy
from articles.domains.mk import MkBodyPolicy
from articles.domains.naeil import NaeilBodyPolicy
from articles.domains.newscj import NewscjBodyPolicy
from articles.domains.newspim import NewsPimBodyPolicy
from articles.domains.nocut import NoCutBodyPolicy
from articles.extraction import ArticleExtractor, ExtractionRejectedError
from articles.matching import normalized_text
from config import ExtractionSettings

PHOTO_BODY = (
    "데이터 분과 출범식에서 인사말을 하고 있다. 경기도 성남시 경기기업성장센터에서 "
    "열린 행사다. 2026.10.29 아주경제=홍길동 기자"
)
PHOTO_SUMMARY = "[사진=홍길동 기자] " + PHOTO_BODY
NEWSCJ_SHORT_PHOTO_BODY = (
    "더불어민주당 후보가 부산을 찾은 날 황현필 강사가 지지 발언을 했다. 그는 부산포에서 "
    "승리하고 조선의 제해권을 장악했듯이 후보가 부산에서 승리하고 압도적인 승리로 이 나라의 "
    "대통령이 될 수 있기를 바란다며 역사의 정의로움에 비켜서지 않을 대통령이라고 말했다."
)
NEWSCJ_SHORT_PHOTO_SUMMARY = (
    "압도적인 승리로 이 나라의 대통령이 될 수 있기를 바란다며 역사의 정의로움에 "
    "비켜서지 않을 대통령이라고 말했다."
)
KADO_CAPTION = (
    "▲ 소나무재선충병 방제협의회에 관계자가 참석한 가운데 "
    "춘천국유림관리소에서 방제 대책 회의가 열렸다."
)
KADO_COPYRIGHT = "저작권자 ⓒ 강원도민일보(https://www.kado.net) 무단전재 및 재배포금지"
KADO_SUMMARY = KADO_CAPTION + KADO_COPYRIGHT


@pytest.mark.parametrize(
    ("policy", "url", "container", "excluded"),
    [
        (
            AjuNewsBodyPolicy(),
            "https://www.ajunews.com/view/1",
            '<div id="articleBody" class="article_con">{body}{excluded}</div>',
            '<div class="relate_box">관련기사 황현필</div>'
            '<ul class="related"><li>기자 관련 기사 황현필</li></ul>'
            '<div class="byline">기자 이름과 기자의 다른기사 황현필</div>'
            '<div class="keyword_tag">#황현필</div>'
            '<div class="news_like_bad">좋아요0 나빠요0</div>'
            '<p class="copy">무단전재 금지</p>'
            '<div class="view_bottom_cont">댓글</div>'
            '<div class="recommend_news">추천 기사 황현필</div>',
        ),
        (
            AsiaTodayBodyPolicy(),
            "https://www.asiatoday.co.kr/view.php?key=1",
            '<div class="view_news_box"><div class="news_bm">{body}</div></div>',
            '<aside class="view_aside_box">많이 본 뉴스 황현필</aside>'
            '<div class="cont_news_box3">댓글</div>',
        ),
        (
            NaeilBodyPolicy(),
            "https://www.naeil.com/news_view/?id=1",
            '<div class="article-view">{body}</div>',
            '<div class="article-wrap">공유 메뉴</div><aside>많이 본 뉴스 황현필</aside>',
        ),
        (
            NewsPimBodyPolicy(),
            "https://www.newspim.com/news/view/1",
            '<div id="news-contents">{body}</div>',
            "<section>주요 포토 황현필</section><aside>다른 기사 황현필</aside>",
        ),
    ],
)
def test_policy_keeps_only_article_container(
    seed, article_text, policy, url, container, excluded
) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    body = (
        article_text + "<script>selector-script</script><style>.selector-style {}</style>사진 설명"
    )
    body_container = container.format(body=body, excluded=excluded)
    outside = "" if "{excluded}" in container else excluded
    markup = f"<html><body>{body_container}{outside}</body></html>"
    result = policy.extract_body(
        seeded, Selector(content=markup, url=url), seeded.title, url, markup, ExtractionSettings()
    )

    assert result is not None
    assert result.evidence.verified
    assert normalized_text(result.text) == normalized_text(article_text + "사진 설명")
    assert "황현필" not in result.text
    assert "selector-script" not in result.text
    assert "selector-style" not in result.text


def test_ajunews_excludes_byline_reactions_tags_and_copyright(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <div id="articleBody" class="article_con">
      {article_text}<div class="byline">기자의 다른기사</div>
      <div class="keyword_tag">#경기도</div>
      <div class="news_like_bad">좋아요0 나빠요0</div>
      <p class="copy">무단전재 금지</p>
    </div>
    """

    result = AjuNewsBodyPolicy().extract_body(
        seeded,
        Selector(content=markup, url="https://www.ajunews.com/view/1"),
        seeded.title,
        "https://www.ajunews.com/view/1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None
    assert result.evidence.verified
    assert normalized_text(result.text) == normalized_text(article_text)


@pytest.mark.parametrize(
    ("url", "title", "summary", "body", "verified"),
    [
        (
            "https://www.ajunews.com/view/1",
            "[포토] 데이터 분과 출범식",
            PHOTO_SUMMARY,
            PHOTO_BODY,
            True,
        ),
        (
            "https://www.ajunews.com/view/1",
            "\u200b\u200b\u200b[포토] 데이터 분과 출범식",
            PHOTO_SUMMARY,
            PHOTO_BODY,
            True,
        ),
        (
            "https://www.ajunews.com/view/1",
            "[포토] 데이터 분과 출범식",
            "[사진=홍길동 기자] 다른 사진 설명입니다. " + PHOTO_BODY,
            PHOTO_BODY,
            False,
        ),
        (
            "https://example.org/view/1",
            "[포토] 데이터 분과 출범식",
            PHOTO_SUMMARY,
            PHOTO_BODY,
            False,
        ),
        (
            "https://www.ajunews.com/view/1",
            "데이터 분과 출범식",
            PHOTO_SUMMARY,
            PHOTO_BODY,
            False,
        ),
    ],
)
def test_ajunews_official_photo_caption_requires_exact_listing_body(
    seed, url, title, summary, body, verified
) -> None:
    seeded = seed.model_copy(update={"title": title, "summary": summary, "original_url": url})

    assert has_verified_official_photo_body(seeded, title, body, ExtractionSettings()) is verified


def test_newscj_keeps_korean_article_and_excludes_translation_widget(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <article id="article-view-content-div" itemprop="articleBody">
      <p>{article_text}</p>
      <div class="raw-html"><table><tr><td>표 설명</td></tr></table></div>
      <div class="raw-html">
        <style>#btn-en-article {{ display: flex; }}</style>
        <div id="btn-en-article">영문 기사 보기 (View English Article)</div>
        <div>본 영어 번역은 구글 자동 번역 서비스를 기반으로 제공됩니다.</div>
        <div id="btn-en-article">원문보기 (View Original Korean Article)</div>
      </div>
      <div class="ad-template">광고</div>
    </article>
    """
    result = NewscjBodyPolicy().extract_body(
        seeded,
        Selector(content=markup, url="https://www.newscj.com/news/articleView.html?idxno=1"),
        seeded.title,
        "https://www.newscj.com/news/articleView.html?idxno=1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None
    assert result.evidence.verified
    assert normalized_text(result.text) == normalized_text(article_text + " 표 설명")


@pytest.mark.parametrize(
    ("seed_title", "summary", "body", "current_url", "verified"),
    [
        (
            "[포토] 황현필 지지 발언",
            NEWSCJ_SHORT_PHOTO_SUMMARY,
            NEWSCJ_SHORT_PHOTO_BODY,
            "https://www.newscj.com/news/articleView.html?idxno=1",
            True,
        ),
        (
            "[포토] 황현필 지지 발언",
            NEWSCJ_SHORT_PHOTO_BODY,
            NEWSCJ_SHORT_PHOTO_BODY,
            "https://www.newscj.com/news/articleView.html?idxno=2",
            False,
        ),
        (
            "[포토] 황현필 지지 발언",
            "목록 요약과 다른 기사 내용입니다. 제목과 무관한 설명을 충분히 추가합니다.",
            NEWSCJ_SHORT_PHOTO_BODY,
            "https://www.newscj.com/news/articleView.html?idxno=1",
            False,
        ),
        (
            "[포토] 황현필 지지 발언",
            "[사진=기자]",
            "[사진=기자]",
            "https://www.newscj.com/news/articleView.html?idxno=1",
            False,
        ),
    ],
)
def test_newscj_short_photo_requires_matching_listing_and_article_id(
    seed, seed_title, summary, body, current_url, verified
) -> None:
    seeded = seed.model_copy(
        update={
            "title": seed_title,
            "summary": summary,
            "original_url": "https://www.newscj.com/news/articleView.html?idxno=1",
        }
    )
    markup = (
        '<article id="article-view-content-div" itemprop="articleBody">'
        f"<p>{body}</p></article>"
    )
    result = NewscjBodyPolicy().extract_body(
        seeded,
        Selector(content=markup, url=current_url),
        seeded.title,
        current_url,
        markup,
        ExtractionSettings(),
    )

    assert result is not None
    assert result.evidence.verified is verified


def test_kado_excludes_reaction_and_comment_ui(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <section class="article-body">
      <aside class="article-sns">공유하기</aside>
      <div id="article-view-content-div" itemprop="articleBody">
        <p>{article_text}</p>
        <div style="text-align:center">▲ 사진 설명</div>
        <script>댓글 좋아요</script>
      </div>
      <article class="article-writer">기자의 다른기사</article>
      <div id="emoji-for">좋아요 0</div>
      <section class="comment">댓글 0</section>
    </section>
    """
    result = KadoBodyPolicy().extract_body(
        seeded,
        Selector(content=markup, url="https://www.kado.net/news/articleView.html?idxno=1"),
        seeded.title,
        "https://www.kado.net/news/articleView.html?idxno=1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None
    assert result.evidence.verified
    assert normalized_text(result.text) == normalized_text(article_text + " ▲ 사진 설명")


@pytest.mark.parametrize(
    ("summary", "current_url", "with_paragraph", "verified"),
    [
        (
            KADO_SUMMARY,
            "https://www.kado.net/news/articleView.html?idxno=1",
            False,
            True,
        ),
        (
            KADO_SUMMARY,
            "https://www.kado.net/news/articleView.html?idxno=2",
            False,
            False,
        ),
        (
            KADO_CAPTION.replace("소나무", "산불") + KADO_COPYRIGHT,
            "https://www.kado.net/news/articleView.html?idxno=1",
            False,
            False,
        ),
        (
            KADO_SUMMARY,
            "https://www.kado.net/news/articleView.html?idxno=1",
            True,
            False,
        ),
    ],
)
def test_kado_short_photo_requires_caption_and_article_id(
    seed, summary, current_url, with_paragraph, verified
) -> None:
    caption = KADO_CAPTION
    seeded = seed.model_copy(
        update={
            "summary": summary,
            "original_url": "https://www.kado.net/news/articleView.html?idxno=1",
        }
    )
    paragraph = "<p>일반 기사 본문입니다.</p>" if with_paragraph else ""
    markup = f"""
    <div id="article-view-content-div" itemprop="articleBody">
      {paragraph}<figure><img alt="{caption}"><figcaption>{caption}</figcaption></figure>
    </div>
    """
    result = KadoBodyPolicy().extract_body(
        seeded,
        Selector(content=markup, url=current_url),
        seeded.title,
        current_url,
        markup,
        ExtractionSettings(),
    )

    assert result is not None
    assert result.evidence.verified is verified
    if verified:
        assert result.text == caption


def test_mk_excludes_photo_zoom_and_keeps_caption_and_byline(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <div class="sec_body">
      <div class="news_cnt_detail_wrap" itemprop="articleBody">
        <p class="writer-intro">오상준 골프 칼럼니스트</p>
        <p>{article_text}</p>
        <div class="thumb_area img"><figure>
          <div class="thumb"><button class="btn btn_ic btn_zoom">
            <span class="is_blind">사진 확대</span>
          </button></div>
          <figcaption><span class="thum_figure_txt">골프장 사진 설명</span></figcaption>
        </figure></div>
        <script>사진 확대</script>
      </div>
      <aside>다른 기사</aside>
    </div>
    """
    result = MkBodyPolicy().extract_body(
        seeded,
        Selector(content=markup, url="https://www.mk.co.kr/news/sports/1"),
        seeded.title,
        "https://www.mk.co.kr/news/sports/1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None
    assert result.evidence.verified
    assert normalized_text(result.text) == normalized_text(
        "오상준 골프 칼럼니스트 " + article_text + " 골프장 사진 설명"
    )
    assert "사진 확대" not in result.text


def test_mk_old_article_body_excludes_photo_zoom(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <div id="article_body" class="article_body">
      <p>{article_text}</p>
      <div class="thumb_area img"><figure>
        <button class="btn btn_ic btn_zoom"><span>사진 확대</span></button>
        <figcaption>구형 사진 설명</figcaption>
      </figure></div>
    </div>
    """

    result = MkBodyPolicy().extract_body(
        seeded,
        Selector(content=markup, url="https://www.mk.co.kr/news/sports/1"),
        seeded.title,
        "https://www.mk.co.kr/news/sports/1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None
    assert result.evidence.verified
    assert normalized_text(result.text) == normalized_text(article_text + " 구형 사진 설명")
    assert "사진 확대" not in result.text


def test_nocut_keeps_article_and_caption_without_related_or_advertising(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <div id="pnlViewBox">
      <div id="pnlContent" itemprop="articleBody">
        <span class="fr-img-caption"><span class="fr-inner">사진 설명</span>
          <iframe src="https://ads.example.test"></iframe>
        </span>
        <p>{article_text}</p><script>광고 스크립트</script>
      </div>
      <div id="divCommonRelated">지금 뜨는 뉴스 황현필</div>
    </div>
    <footer>제보 구독</footer>
    """

    result = NoCutBodyPolicy().extract_body(
        seeded,
        Selector(content=markup, url="https://www.nocutnews.co.kr/news/1"),
        seeded.title,
        "https://www.nocutnews.co.kr/news/1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None
    assert result.evidence.verified
    assert normalized_text(result.text) == normalized_text("사진 설명 " + article_text)
    assert "지금 뜨는 뉴스" not in result.text
    assert "제보" not in result.text
    assert "구독" not in result.text


def test_nocut_keeps_direct_article_summary_without_external_summary(seed, article_text) -> None:
    core_summary = (
        "황현필 역사바로잡기연구소장이 광주 금남로 집회를 두고 "
        "인륜을 저버리는 행위라고 강하게 말했다."
    )
    seeded = seed.model_copy(update={"summary": core_summary})
    markup = f"""
    <div id="pnlViewBox">
      <div class="summary_l" data-type="summary"><p>{core_summary}</p></div>
      <div id="pnlContent" itemprop="articleBody"><p>{article_text}</p></div>
    </div>
    <div class="summary_l" data-type="summary"><p>외부 추천 요약 황현필</p></div>
    """

    result = NoCutBodyPolicy().extract_body(
        seeded,
        Selector(content=markup, url="https://www.nocutnews.co.kr/news/1"),
        seeded.title,
        "https://www.nocutnews.co.kr/news/1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None
    assert result.evidence.verified
    assert core_summary in result.text
    assert article_text in result.text
    assert "외부 추천 요약" not in result.text


@pytest.mark.parametrize(
    ("policy", "url", "container"),
    [
        (
            AjuNewsBodyPolicy(),
            "https://www.ajunews.com/view/1",
            '<div id="articleBody" class="article_con">{body}</div>',
        ),
        (
            AsiaTodayBodyPolicy(),
            "https://www.asiatoday.co.kr/view.php?key=1",
            '<div class="view_news_box"><div class="news_bm">{body}</div></div>',
        ),
        (
            NaeilBodyPolicy(),
            "https://www.naeil.com/news_view/?id=1",
            '<div class="article-view">{body}</div>',
        ),
        (
            NewsPimBodyPolicy(),
            "https://www.newspim.com/news/view/1",
            '<div id="news-contents">{body}</div>',
        ),
    ],
)
def test_policy_blocks_generic_fallback_when_selected_body_fails_verification(
    seed, repository, policy, url, container
) -> None:
    markup = (
        f"<html><title>{seed.title}</title><body>{container.format(body='짧은 다른 내용')}"
        f"</body><footer>{seed.summary}</footer></html>"
    )
    with pytest.raises(ExtractionRejectedError):
        ArticleExtractor(repository, ExtractionSettings()).extract(seed, markup.encode(), url)


@pytest.mark.parametrize(
    ("page_title", "seed_title", "summary_matches", "photo", "verified"),
    [
        ("[부고] 단문 기사", "[부고] 단문 기사", True, False, True),
        ("사진 기사", "사진 기사", True, True, True),
        ("다른 제목", "[부고] 단문 기사", True, False, False),
        ("[부고] 단문 기사", "[부고] 단문 기사", False, False, False),
        ("[부고] 단문 기사", "[부고] 단문 기사", False, False, False),
    ],
)
def test_newspim_short_photo_or_obituary_requires_exact_listing_identity(
    seed, page_title, seed_title, summary_matches, photo, verified
) -> None:
    url = "https://www.newspim.com/news/view/1"
    body = "유숙 씨 별세와 빈소 안내를 담은 뉴스핌 단문 기사입니다. " * 4
    summary = body if summary_matches else "전혀 다른 목록 요약입니다. " * 4
    seeded = seed.model_copy(update={"title": seed_title, "summary": summary})
    photo_table = "<table><tr><td>사진</td></tr></table>" if photo else ""
    markup = f'<div id="news-contents">{photo_table}{body}</div>'
    result = NewsPimBodyPolicy().extract_body(
        seeded, Selector(content=markup), page_title, url, markup, ExtractionSettings()
    )

    assert result is not None
    assert result.evidence.verified is verified
