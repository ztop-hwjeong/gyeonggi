from dataclasses import dataclass
from uuid import UUID

from analysis.models import Article

MIN_BODY_CHARS = 200
SHINGLE_WIDTH = 7
MIN_SIMILARITY = 0.85
MATCHING_BASIS = f"normalized_7_char_shingle_jaccard>={MIN_SIMILARITY}"


@dataclass(frozen=True)
class ReprintCandidate:
    article_id: UUID
    content_hash: str
    body: str
    publisher: str | None


@dataclass(frozen=True)
class ReprintMatch:
    article_id: UUID
    content_hash: str
    similarity: float


def _shingles(body: str) -> set[str]:
    normalized = "".join(body.casefold().split())
    if len(normalized) < MIN_BODY_CHARS:
        return set()
    return {
        normalized[index : index + SHINGLE_WIDTH]
        for index in range(len(normalized) - SHINGLE_WIDTH + 1)
    }


def find_reprints(
    article: Article, publisher: str | None, candidates: list[ReprintCandidate]
) -> list[ReprintMatch]:
    if not publisher or not (original := _shingles(article.body)):
        return []
    matches = []
    for candidate in candidates:
        if not candidate.publisher or " ".join(candidate.publisher.casefold().split()) == " ".join(
            publisher.casefold().split()
        ):
            continue
        compared = _shingles(candidate.body)
        if not compared:
            continue
        similarity = len(original & compared) / len(original | compared)
        if similarity >= MIN_SIMILARITY:
            matches.append(ReprintMatch(candidate.article_id, candidate.content_hash, similarity))
    return matches
