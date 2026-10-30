from scrapling import Selector

from articles.domains.seoul import SeoulBodyPolicy
from articles.matching import normalized_text
from config import ExtractionSettings


def test_seoul_policy_uses_atic_cnt_and_preserves_article_caption(seed, article_text) -> None:
    seeded = seed.model_copy(update={"summary": article_text[:180] + ".."})
    markup = f"""
    <div class="content">
      <div class="atic_title">{seed.title}</div>
      <div class="atic_cnt">
        {article_text}<script>lightBox('추천')</script>
        <p class="photo">사진 설명</p>Copyright 서울신문
      </div>
      <div class="cnt_newest">광양 재자원화 거점된다 과메기철 돌아왔네</div>
      <div id="new_iframeLivere" class="atic_reply">댓글</div>
    </div>
    """
    result = SeoulBodyPolicy().extract_body(
        seeded,
        Selector(content=markup),
        seeded.title,
        "https://go.seoul.co.kr/news/newsView.php?id=1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None
    assert normalized_text(result.text) == normalized_text(
        article_text + " 사진 설명 Copyright 서울신문"
    )
    assert "광양 재자원화" not in result.text
    assert "댓글" not in result.text
    assert "lightBox" not in result.text


def test_seoul_policy_returns_unverified_result_when_article_container_is_ambiguous(seed) -> None:
    markup = """
    <div class="content">
      <div class="atic_cnt">첫 기사</div><div class="atic_cnt">추천 기사</div>
    </div>
    """
    result = SeoulBodyPolicy().extract_body(
        seed,
        Selector(content=markup),
        seed.title,
        "https://go.seoul.co.kr/news/newsView.php?id=1",
        markup,
        ExtractionSettings(),
    )

    assert result is not None
    assert not result.evidence.verified
