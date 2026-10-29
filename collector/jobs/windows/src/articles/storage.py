from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID, uuid4

from collector_storage.objects import RawObject, RawObjectStore
from collector_storage.publishers import publisher_code
from sqlalchemy import func, literal, or_, select, union_all, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from articles.domains import domain_host
from articles.models import (
    ArticleDetail,
    ArticleSeed,
    DetailAttempt,
    DetailRunSummary,
    DetailStage,
    FetchSnapshot,
    PublisherIdentity,
)
from articles.tables import (
    adaptive_history,
    adaptive_profiles,
    article_browser_policies,
    article_contents,
    articles,
    attempts,
    detail_results,
    detail_runs,
    news_items,
    publisher_domains,
    publishers,
    responses,
    search_items,
    search_run_items,
)


class DetailRepository:
    def __init__(self, engine: Engine, objects: RawObjectStore) -> None:
        self._engine = engine
        self._objects = objects

    def pending_naver_news(
        self, limit: int, search_run_id: UUID | None = None
    ) -> list[ArticleSeed]:
        return self.pending_articles(limit, "naver_news", search_run_id)

    def pending_articles(
        self,
        limit: int,
        source: Literal["bigkinds", "naver_news"] | None = None,
        search_run_id: UUID | None = None,
    ) -> list[ArticleSeed]:
        listings = union_all(
            select(
                literal("naver_news").label("source"),
                search_items.c.source_id,
                search_items.c.data,
                search_items.c.article_id,
                search_items.c.first_seen_at,
            ).where(search_items.c.provider == "naver", search_items.c.channel == "news"),
            select(
                news_items.c.source,
                news_items.c.source_id,
                news_items.c.data,
                news_items.c.article_id,
                news_items.c.first_seen_at,
            ).where(news_items.c.source == "bigkinds"),
        ).subquery()
        collected = (
            select(article_contents.c.id)
            .where(article_contents.c.article_id == listings.c.article_id)
            .exists()
        )
        skipped = (
            select(detail_results.c.run_id)
            .where(
                detail_results.c.source_id == listings.c.source_id,
                detail_results.c.result["seed"]["source"].astext == listings.c.source,
                detail_results.c.result["status"].astext == "skipped",
            )
            .exists()
        )
        last_failure = (
            select(func.max(detail_runs.c.created_at))
            .select_from(
                detail_results.join(detail_runs, detail_runs.c.id == detail_results.c.run_id)
            )
            .where(
                detail_results.c.source_id == listings.c.source_id,
                detail_results.c.result["seed"]["source"].astext == listings.c.source,
                detail_results.c.result["status"].astext == "failed",
            )
            .scalar_subquery()
        )
        scope = []
        if source is not None:
            scope.append(listings.c.source == source)
        if search_run_id is not None:
            scope.append(listings.c.source == "naver_news")
            scope.append(
                select(search_run_items.c.source_id)
                .where(
                    search_run_items.c.run_id == search_run_id,
                    search_run_items.c.source_id == listings.c.source_id,
                )
                .exists()
            )
        candidates = (
            select(
                listings.c.source,
                listings.c.source_id,
                listings.c.data,
                articles.c.publisher,
                articles.c.publisher_code,
                listings.c.first_seen_at,
                func.row_number()
                .over(
                    partition_by=listings.c.article_id,
                    order_by=[listings.c.first_seen_at, listings.c.source_id],
                )
                .label("rank"),
            )
            .join(articles, articles.c.id == listings.c.article_id)
            .where(
                ~collected,
                ~skipped,
                or_(
                    last_failure.is_(None),
                    last_failure <= datetime.now(UTC) - timedelta(hours=1),
                ),
                *scope,
            )
            .subquery()
        )
        statement = (
            select(candidates)
            .where(candidates.c.rank == 1)
            .order_by(candidates.c.first_seen_at.desc(), candidates.c.source_id)
            .limit(limit)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            ArticleSeed(
                source=row["source"],
                source_id=row["source_id"],
                title=row["data"]["title"],
                summary=row["data"].get("summary", ""),
                publisher=row["publisher"] or row["data"].get("publisher") or None,
                publisher_code=row["publisher_code"]
                or publisher_code(row["data"].get("original_url") or row["data"].get("url") or ""),
                original_url=row["data"].get("original_url") or row["data"].get("url"),
                published_on=row["data"].get("published_on"),
                published_at=row["data"].get("published_at"),
            )
            for row in rows
        ]

    def resolve_publisher(self, url: str) -> PublisherIdentity | None:
        code = publisher_code(url)
        if code is None:
            return None
        lookup = select(publishers.c.code, publishers.c.name).where(
            publishers.c.code == func.dw.resolve_publisher_code(code)
        )
        with self._engine.connect() as connection:
            row = connection.execute(lookup).one_or_none()
        if row is None:
            return PublisherIdentity(code=code, name=None, method="domain")
        return PublisherIdentity(code=row.code, name=row.name)

    def allows_rendered_browser(self, url: str | None) -> bool:
        host = domain_host(url)
        if host is None:
            return False
        with self._engine.connect() as connection:
            mode = connection.execute(
                select(article_browser_policies.c.browser_mode).where(
                    article_browser_policies.c.domain == host
                )
            ).scalar_one_or_none()
        return mode == "rendered_after_http_failure"

    def save_run(self, summary: DetailRunSummary) -> None:
        statement = insert(detail_runs).values(
            id=UUID(summary.run_id), summary=summary.model_dump(mode="json")
        )
        with self._engine.begin() as connection:
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[detail_runs.c.id],
                    set_={"summary": statement.excluded.summary},
                )
            )

    def save_response(
        self,
        run_id: UUID,
        seed: ArticleSeed,
        stage: DetailStage,
        url: str,
        status: int,
        content_type: str,
        body: bytes,
        retry_after: str | None,
    ) -> FetchSnapshot:
        snapshot = FetchSnapshot(
            response_id=uuid4(),
            url=url,
            status_code=status,
            content_type=content_type,
            sha256=sha256(body).hexdigest(),
            received_at=datetime.now(UTC),
            retry_after=retry_after,
        )
        reference = self._objects.put(
            f"articles/{run_id}/{stage}/{snapshot.response_id}", body, content_type
        )
        with self._engine.begin() as connection:
            connection.execute(
                insert(responses).values(
                    id=snapshot.response_id,
                    run_id=run_id,
                    source_id=seed.source_id,
                    stage=stage,
                    seed=seed.model_dump(mode="json"),
                    metadata=snapshot.model_dump(mode="json"),
                    raw_object=reference.model_dump(mode="json"),
                )
            )
        return snapshot

    def read_body(self, snapshot: FetchSnapshot) -> bytes:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(responses.c.raw_object).where(responses.c.id == snapshot.response_id)
            ).scalar_one_or_none()
        if row is None:
            raise LookupError("수집 원본 응답 없음")
        reference = RawObject.model_validate(row)
        if reference.sha256 != snapshot.sha256:
            raise RuntimeError("수집 원본 메타데이터 해시 불일치")
        return self._objects.read(reference)

    def save_attempt(self, run_id: UUID, seed: ArticleSeed, attempt: DetailAttempt) -> None:
        statement = insert(attempts).values(
            run_id=run_id,
            source_id=seed.source_id,
            stage=attempt.stage,
            result=attempt.model_dump(mode="json"),
        )
        with self._engine.begin() as connection:
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[attempts.c.run_id, attempts.c.source_id, attempts.c.stage],
                    set_={"result": statement.excluded.result},
                )
            )

    def save_detail(self, run_id: UUID, result: ArticleDetail) -> None:
        result_statement = insert(detail_results).values(
            run_id=run_id,
            source_id=result.seed.source_id,
            result=result.model_dump(mode="json"),
        )
        with self._engine.begin() as connection:
            connection.execute(
                result_statement.on_conflict_do_update(
                    index_elements=[detail_results.c.run_id, detail_results.c.source_id],
                    set_={"result": result_statement.excluded.result},
                )
            )
            selected = next((item for item in result.attempts if item.status == "accepted"), None)
            if selected is not None and selected.extraction is not None:
                content = selected.extraction
                digest = sha256(content.text.encode()).hexdigest()
                content_statement = insert(article_contents).values(
                    source=result.seed.source,
                    source_id=result.seed.source_id,
                    content_hash=digest,
                    title=content.title,
                    body=content.text,
                    stage=selected.stage,
                    run_id=run_id,
                    provenance=selected.model_dump(mode="json"),
                    original_published_on=content.original_published_on,
                    original_published_at=content.original_published_at,
                    original_modified_on=content.original_modified_on,
                    original_modified_at=content.original_modified_at,
                    collected_at=datetime.now(UTC),
                )
                article_id = connection.execute(
                    content_statement.on_conflict_do_update(
                        index_elements=[
                            article_contents.c.source,
                            article_contents.c.source_id,
                            article_contents.c.content_hash,
                        ],
                        set_={
                            "original_published_on": (
                                func.coalesce(
                                    content_statement.excluded.original_published_on,
                                    article_contents.c.original_published_on,
                                )
                            ),
                            "original_published_at": (
                                func.coalesce(
                                    content_statement.excluded.original_published_at,
                                    article_contents.c.original_published_at,
                                )
                            ),
                            "original_modified_on": (
                                func.coalesce(
                                    content_statement.excluded.original_modified_on,
                                    article_contents.c.original_modified_on,
                                )
                            ),
                            "original_modified_at": (
                                func.coalesce(
                                    content_statement.excluded.original_modified_at,
                                    article_contents.c.original_modified_at,
                                )
                            ),
                            "collected_at": content_statement.excluded.collected_at,
                            "provenance": content_statement.excluded.provenance,
                        },
                    ).returning(article_contents.c.article_id)
                ).scalar_one()
                if result.seed.publisher_code:
                    domain = publisher_code(str(result.seed.original_url or ""))
                    registered_code = connection.scalar(
                        select(
                            func.coalesce(
                                select(publisher_domains.c.publisher_code)
                                .where(publisher_domains.c.domain == domain)
                                .scalar_subquery(),
                                func.dw.resolve_publisher_code(result.seed.publisher_code),
                            )
                        )
                    )
                    # 미등록 도메인은 원문·수집 이력만 보존하고 언론사 연결을 뒤로 미루는 저장
                    if registered_code is not None:
                        connection.execute(
                            update(articles)
                            .where(articles.c.id == article_id)
                            .values(publisher_code=registered_code)
                        )

    def read_profile(self, scope: str, identifier: str) -> dict[str, Any] | None:
        with self._engine.connect() as connection:
            return connection.execute(
                select(adaptive_profiles.c.properties).where(
                    adaptive_profiles.c.scope == scope,
                    adaptive_profiles.c.identifier == identifier,
                )
            ).scalar_one_or_none()

    def save_profile(self, scope: str, identifier: str, properties: dict, context: dict) -> None:
        statement = insert(adaptive_profiles).values(
            scope=scope, identifier=identifier, properties=properties, context=context
        )
        with self._engine.begin() as connection:
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[adaptive_profiles.c.scope, adaptive_profiles.c.identifier],
                    set_={
                        "properties": statement.excluded.properties,
                        "context": statement.excluded.context,
                    },
                )
            )
            connection.execute(
                insert(adaptive_history).values(
                    id=uuid4(),
                    scope=scope,
                    identifier=identifier,
                    properties=properties,
                    context=context,
                )
            )


class ArticleStore:
    def __init__(self, repository: DetailRepository, run_id: UUID, seed: ArticleSeed) -> None:
        self.repository = repository
        self._run_id = run_id
        self._seed = seed

    def save_response(
        self,
        stage: DetailStage,
        url: str,
        status: int,
        content_type: str,
        body: bytes,
        retry_after: str | None = None,
    ) -> FetchSnapshot:
        return self.repository.save_response(
            self._run_id, self._seed, stage, url, status, content_type, body, retry_after
        )
