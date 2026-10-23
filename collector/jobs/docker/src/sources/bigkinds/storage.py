import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from sources.bigkinds.client import search_payload
from sources.bigkinds.models import (
    ArticleListing,
    CollectionSummary,
    ListCollectionRequest,
    NormalizedPage,
    StoredResponse,
)


def write_model(path: Path, value: BaseModel) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def store_response(
    directory: Path, request: ListCollectionRequest, page_number: int, body: bytes
) -> StoredResponse:
    raw = directory / "raw" / f"page-{page_number:06d}-{uuid4().hex}"
    raw.mkdir(parents=True)
    response = StoredResponse(
        page_number=page_number, body_path=raw / "response.json", metadata_path=raw / "request.json"
    )
    response.body_path.write_bytes(body)
    response.metadata_path.write_text(
        json.dumps(
            {
                "received_at": datetime.now(UTC).isoformat(),
                "request": search_payload(request, page_number),
                "response_sha256": sha256(body).hexdigest(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return response


def store_listings(
    directory: Path, page_number: int, total_count: int, articles: list[ArticleListing]
) -> NormalizedPage:
    pages = directory / "pages"
    pages.mkdir(exist_ok=True)
    path = pages / f"page-{page_number:06d}.jsonl"
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        for article in articles:
            output.write(article.model_dump_json() + "\n")
    temporary.replace(path)
    return NormalizedPage(
        page_number=page_number,
        total_count=total_count,
        article_count=len(articles),
        source_ids=tuple(article.source_id for article in articles),
        items_path=path,
    )


def finalize_collection(
    summary: CollectionSummary, pages: list[NormalizedPage]
) -> CollectionSummary:
    identifiers: set[str] = set()
    retrieved = 0
    temporary = summary.output_directory / "articles.jsonl.tmp"
    with temporary.open("w", encoding="utf-8") as output:
        for page in pages:
            added = 0
            with page.items_path.open(encoding="utf-8") as source:
                for line in source:
                    article = ArticleListing.model_validate_json(line)
                    retrieved += 1
                    if article.source_id not in identifiers:
                        identifiers.add(article.source_id)
                        output.write(article.model_dump_json() + "\n")
                        added += 1
            if page.article_count and added == 0:
                raise UnexpectedPaginationError("페이지 이동 후 새로운 기사 없음")
    temporary.replace(summary.output_directory / "articles.jsonl")
    first_count = pages[0].total_count
    counts_changed = any(page.total_count != first_count for page in pages)
    complete = not counts_changed and len(identifiers) == first_count
    result = summary.model_copy(
        update={
            "status": "completed" if complete else "partial",
            "finished_at": datetime.now(UTC),
            "pages_collected": len(pages),
            "initial_total_count": first_count,
            "latest_total_count": pages[-1].total_count,
            "retrieved_count": retrieved,
            "unique_count": len(identifiers),
            "duplicate_count": retrieved - len(identifiers),
            "stop_reason": None
            if complete
            else "검색 건수 변동"
            if counts_changed
            else "페이지 제한 또는 검색 건수와 결과 불일치",
        }
    )
    write_model(summary.output_directory / "manifest.json", result)
    return result


class UnexpectedPaginationError(RuntimeError):
    pass
