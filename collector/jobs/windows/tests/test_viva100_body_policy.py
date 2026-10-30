from scrapling import Selector

from articles.domains.viva100 import Viva100BodyPolicy
from config import ExtractionSettings


def test_viva100_keeps_article_caption_and_reporter_without_reporter_links(seed, article_text):
    url = "https://www.viva100.com/article/1"
    markup = (
        '<div class="news_content"><figure><figcaption>사진 설명</figcaption></figure>'
        f"<p>{article_text}</p><p>기자 이름 reporter@viva100.com</p>"
        '<div class="reporter_more">기자의 다른 기사 더보기</div>'
        "<script>본문오염</script></div><aside>다른 기사</aside>"
    )
    result = Viva100BodyPolicy().extract_body(
        seed, Selector(content=markup), seed.title, url, markup, ExtractionSettings()
    )
    assert result is not None and result.evidence.verified
    assert "사진 설명" in result.text and "reporter@viva100.com" in result.text
    assert "기자의 다른 기사 더보기" not in result.text and "본문오염" not in result.text


def test_viva100_returns_unverified_selected_body_to_block_fallback(seed):
    url = "https://www.viva100.com/article/1"
    markup = (
        '<div class="news_content">짧은 실제 본문'
        '<div class="reporter_more">기자의 다른 기사 더보기</div></div>'
    )
    result = Viva100BodyPolicy().extract_body(
        seed, Selector(content=markup), seed.title, url, markup, ExtractionSettings()
    )
    assert result is not None and not result.evidence.verified
