from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.collection.errors import (
    CollectionConflictError,
    CollectionNotFoundError,
    CollectionUnavailableError,
)
from domain.collection.models import (
    Pagination,
    PreviewCreate,
    RequestInfo,
    RequestPage,
    RequestQuery,
    ResultItem,
    ResultPage,
    RuleDefinition,
    RuleInfo,
    RulePage,
    RuleUpdate,
    RuleVersion,
    RunCreate,
)


class CollectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None]:
        try:
            async with self._session.begin():
                yield
        except SQLAlchemyError as error:
            raise CollectionUnavailableError("수집 관리 저장소 연결 실패") from error

    async def rows(self, sql: str, parameters: dict | None = None):
        return (await self._session.execute(text(sql), parameters or {})).mappings().all()

    async def rules(self, page: Pagination) -> RulePage:
        async with self.transaction():
            total = (await self.rows("SELECT count(*) AS total FROM ops.collection_rules"))[0][
                "total"
            ]
            rows = await self.rows(
                "SELECT * FROM ops.collection_rules ORDER BY updated_at DESC, id "
                "LIMIT :limit OFFSET :offset",
                page.model_dump(),
            )
            return RulePage(items=[RuleInfo.model_validate(row) for row in rows], total=total)

    async def rule(self, rule_id: UUID) -> RuleInfo:
        async with self.transaction():
            rows = await self.rows(
                "SELECT * FROM ops.collection_rules WHERE id=:id", {"id": rule_id}
            )
            if not rows:
                raise CollectionNotFoundError("검색 규칙 없음")
            return RuleInfo.model_validate(rows[0])

    async def versions(self, rule_id: UUID) -> list[RuleVersion]:
        async with self.transaction():
            rows = await self.rows(
                "SELECT * FROM ops.collection_rule_versions WHERE rule_id=:id "
                "ORDER BY version DESC",
                {"id": rule_id},
            )
            if not rows:
                raise CollectionNotFoundError("검색 규칙 없음")
            return [RuleVersion.model_validate(row) for row in rows]

    async def save_rule(self, definition: RuleDefinition, rule_id: UUID | None = None) -> RuleInfo:
        async with self.transaction():
            if rule_id is None:
                rule_id = uuid4()
                version = 1
            else:
                rows = await self.rows(
                    "SELECT version FROM ops.collection_rules WHERE id=:id FOR UPDATE",
                    {"id": rule_id},
                )
                if not rows:
                    raise CollectionNotFoundError("검색 규칙 없음")
                if (
                    not isinstance(definition, RuleUpdate)
                    or rows[0]["version"] != definition.version
                ):
                    raise CollectionConflictError(
                        "다른 사용자가 변경했어요. 새로고침 후 다시 저장해 주세요."
                    )
                version = definition.version + 1
            payload = RuleDefinition.model_validate(definition.model_dump(exclude={"version"}))
            params = {"id": rule_id, "version": version, "definition": payload.model_dump_json()}
            rows = await self.rows(
                "INSERT INTO ops.collection_rules(id,version,definition) "
                "VALUES (:id,:version,CAST(:definition AS jsonb)) ON CONFLICT(id) DO UPDATE "
                "SET version=EXCLUDED.version, definition=EXCLUDED.definition, "
                "updated_at=now(), next_run_at=now() RETURNING *",
                params,
            )
            await self.rows(
                "INSERT INTO ops.collection_rule_versions(rule_id,version,definition) "
                "VALUES (:id,:version,CAST(:definition AS jsonb)) RETURNING version",
                params,
            )
            return RuleInfo.model_validate(rows[0])

    async def enqueue(self, request_id: UUID, body: RunCreate | PreviewCreate) -> RequestInfo:
        async with self.transaction():
            existing = await self.rows(
                "SELECT * FROM ops.collection_requests WHERE id=:id", {"id": request_id}
            )
            if existing:
                saved = RequestInfo.model_validate(existing[0])
                matches = (saved.source, saved.start_date, saved.end_date) == (
                    body.source,
                    body.start_date,
                    body.end_date,
                )
                if isinstance(body, RunCreate):
                    matches = matches and (saved.rule_id, saved.rule_version, saved.mode) == (
                        body.rule_id,
                        body.version,
                        body.mode,
                    )
                else:
                    matches = (
                        matches and saved.mode == "preview" and saved.definition == body.definition
                    )
                if not matches:
                    raise CollectionConflictError("같은 요청 키를 다른 조건에 사용할 수 없어요.")
                return saved
            rule_id, version = None, None
            if isinstance(body, RunCreate):
                rows = await self.rows(
                    "SELECT * FROM ops.collection_rules WHERE id=:id FOR SHARE",
                    {"id": body.rule_id},
                )
                if not rows:
                    raise CollectionNotFoundError("검색 규칙 없음")
                rule = RuleInfo.model_validate(rows[0])
                if rule.version != body.version:
                    raise CollectionConflictError(
                        "검색 규칙이 변경됐어요. 최신 버전으로 다시 요청해 주세요."
                    )
                definition, rule_id, version = rule.definition, rule.id, rule.version
                mode = body.mode
            else:
                definition, mode = body.definition, "preview"
            if body.source not in definition.sources:
                raise CollectionConflictError("검색 규칙에 등록한 채널만 수집할 수 있어요.")
            rows = await self.rows(
                "INSERT INTO ops.collection_requests "
                "(id,rule_id,rule_version,source,mode,definition,start_date,end_date) "
                "VALUES (:id,:rule,:version,:source,:mode,CAST(:definition AS jsonb),:start,:end) "
                "ON CONFLICT(id) DO NOTHING RETURNING *",
                {
                    "id": request_id,
                    "rule": rule_id,
                    "version": version,
                    "source": body.source,
                    "mode": mode,
                    "definition": definition.model_dump_json(),
                    "start": body.start_date,
                    "end": body.end_date,
                },
            )
            if not rows:
                # 동시 중복 요청은 다음 조회로 재시도 가능한 충돌 처리
                raise CollectionConflictError(
                    "동일 요청이 처리 중이에요. 같은 요청 키로 다시 조회해 주세요."
                )
            return RequestInfo.model_validate(rows[0])

    async def requests(self, query: RequestQuery) -> RequestPage:
        async with self.transaction():
            condition = " WHERE (CAST(:rule_id AS uuid) IS NULL OR rule_id=:rule_id)"
            total = (
                await self.rows(
                    "SELECT count(*) AS total FROM ops.collection_requests" + condition,
                    {"rule_id": query.rule_id},
                )
            )[0]["total"]
            rows = await self.rows(
                "SELECT * FROM ops.collection_requests"
                + condition
                + " ORDER BY created_at DESC,id LIMIT :limit OFFSET :offset",
                query.model_dump(),
            )
            return RequestPage(items=[RequestInfo.model_validate(row) for row in rows], total=total)

    async def request(self, request_id: UUID) -> RequestInfo:
        async with self.transaction():
            rows = await self.rows(
                "SELECT * FROM ops.collection_requests WHERE id=:id", {"id": request_id}
            )
            if not rows:
                raise CollectionNotFoundError("수집 요청 없음")
            return RequestInfo.model_validate(rows[0])

    async def cancel(self, request_id: UUID) -> RequestInfo:
        async with self.transaction():
            rows = await self.rows(
                "UPDATE ops.collection_requests SET status=CASE "
                "WHEN status='queued' THEN 'cancelled' "
                "ELSE 'cancelling' END,updated_at=now() WHERE id=:id "
                "AND status IN ('queued','submitted','running','cancelling') RETURNING *",
                {"id": request_id},
            )
            if not rows:
                raise CollectionConflictError("진행 중인 요청만 취소할 수 있어요.")
            return RequestInfo.model_validate(rows[0])

    async def results(self, request_id: UUID, page: Pagination) -> ResultPage:
        async with self.transaction():
            exists = await self.rows(
                "SELECT id FROM ops.collection_requests WHERE id=:id", {"id": request_id}
            )
            if not exists:
                raise CollectionNotFoundError("수집 요청 없음")
            total = (
                await self.rows(
                    "SELECT count(*) AS total FROM st.collection_request_items "
                    "WHERE request_id=:id",
                    {"id": request_id},
                )
            )[0]["total"]
            rows = await self.rows(
                "SELECT data FROM st.collection_request_items WHERE request_id=:id "
                "ORDER BY source_id LIMIT :limit OFFSET :offset",
                {"id": request_id, **page.model_dump()},
            )
            return ResultPage(
                items=[ResultItem.model_validate(row["data"]) for row in rows], total=total
            )
