import re
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
    # 검색 요약의 생략 구간을 가로질러 서로 떨어진 문장을 연결하지 않는 검증
    fragments = [
        part for raw in re.split(r"\.{2,}|…+", seed.summary) if (part := normalized_text(raw))
    ]
    title_score = partial_ratio(normalized_text(seed.title), normalized_text(title))
    summary_score = partial_ratio(summary, target)
    revised_match = (
        any(len(fragment) >= settings.min_summary_chars for fragment in fragments)
        and title_score >= settings.revised_title_similarity
        and summary_score >= settings.revised_summary_similarity
    )
    minimum_fragment = 1 if len(fragments) > 1 else settings.min_summary_chars
    snippets = [
        fragment[start : start + settings.snippet_window_chars]
        for fragment in fragments
        for start in range(0, len(fragment), settings.snippet_step_chars)
        if len(fragment[start : start + settings.snippet_window_chars]) >= minimum_fragment
    ]
    scores = [partial_ratio(snippet, target) for snippet in snippets]
    fraction = (
        sum(score >= settings.snippet_similarity for score in scores) / len(scores) if scores else 0
    )
    matched_chars = sum(
        len(snippet)
        for snippet, score in zip(snippets, scores, strict=True)
        if score >= settings.snippet_similarity
    )
    if len(fragments) > 1:
        # 짧은 구절의 개수보다 일치한 전체 글자 수를 기준으로 한 생략 요약 검증
        fraction = matched_chars / sum(map(len, snippets)) if snippets else 0
    reasons = []
    if "\ufffd" in title or "\ufffd" in text:
        reasons.append("제목·본문 문자 인코딩 확인 필요")
    if len(target) < settings.min_body_chars:
        reasons.append("본문 길이 부족")
    if len(target) < len(summary) + settings.min_added_body_chars:
        reasons.append("목록 요약보다 충분한 본문 필요")
    if title_score < settings.title_similarity:
        reasons.append("제목 불일치")
    if not snippets or len(summary) < settings.min_summary_chars:
        reasons.append("검증할 요약 문장 부족")
    elif (
        fraction < settings.snippet_match_fraction or matched_chars < settings.min_summary_chars
    ) and not revised_match:
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
            or matched_chars < settings.min_summary_chars
            else "제목·요약 문장 일치"
        ),
    )
