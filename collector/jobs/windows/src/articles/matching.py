import unicodedata

from rapidfuzz.fuzz import partial_ratio

from articles.models import ArticleSeed, Evidence
from config import ExtractionSettings


def normalized_text(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKC", text).casefold() if char.isalnum()
    )


def verify_article(
    seed: ArticleSeed, title: str, text: str, settings: ExtractionSettings
) -> Evidence:
    target = normalized_text(text)
    summary = normalized_text(seed.summary)
    title_score = partial_ratio(normalized_text(seed.title), normalized_text(title))
    summary_score = partial_ratio(summary, target)
    revised_match = (
        title_score >= settings.revised_title_similarity
        and summary_score >= settings.revised_summary_similarity
    )
    snippets = [
        summary[start : start + settings.snippet_window_chars]
        for start in range(0, len(summary), settings.snippet_step_chars)
        if len(summary[start : start + settings.snippet_window_chars]) >= settings.min_summary_chars
    ]
    scores = [partial_ratio(snippet, target) for snippet in snippets]
    fraction = (
        sum(score >= settings.snippet_similarity for score in scores) / len(scores) if scores else 0
    )
    reasons = []
    if "\ufffd" in title or "\ufffd" in text:
        reasons.append("제목·본문 문자 인코딩 확인 필요")
    if len(target) < settings.min_body_chars:
        reasons.append("본문 길이 부족")
    if len(target) < len(summary) + settings.min_added_body_chars:
        reasons.append("목록 요약보다 충분한 본문 필요")
    if title_score < settings.title_similarity:
        reasons.append("제목 불일치")
    if not snippets:
        reasons.append("검증할 요약 문장 부족")
    elif fraction < settings.snippet_match_fraction and not revised_match:
        reasons.append("요약 문장 일치 부족")
    return Evidence(
        verified=not reasons,
        title_score=title_score,
        snippet_scores=scores,
        snippet_match_fraction=fraction,
        body_chars=len(target),
        summary_score=summary_score,
        reason="; ".join(reasons)
        if reasons
        else (
            "제목·요약 유사도 일치(편집 차이 허용)"
            if fraction < settings.snippet_match_fraction
            else "제목·요약 문장 일치"
        ),
    )
