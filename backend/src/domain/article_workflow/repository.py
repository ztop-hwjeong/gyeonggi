from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import ResourceClosedError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.article_workflow.models import (
    DecisionHistory,
    DecisionInfo,
    DecisionWrite,
    EvaluationResult,
    FilterConditions,
    FilterRuleInfo,
    FilterRuleUpdate,
    FilterRuleWrite,
    ReapplyRequest,
    ReapplyResult,
    TargetInfo,
    TargetUpdate,
    TargetWrite,
)
from domain.article_workflow.tables import (
    analysis_targets,
    article_decision_history,
    article_filter_rule_versions,
    article_filter_rules,
    article_inclusions,
    article_target_links,
)
from domain.collection.tables import article_contents, materials


class WorkflowError(RuntimeError):
    pass


class WorkflowNotFound(WorkflowError):
    pass


class WorkflowInvalidMaterial(WorkflowError):
    pass


class WorkflowConflict(WorkflowError):
    pass


class ArticleWorkflow:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None]:
        try:
            async with self._session.begin():
                yield
        except SQLAlchemyError as error:
            raise WorkflowError("기사 판단 저장소 연결 실패") from error

    async def rows(self, statement) -> list[dict]:
        result = await self._session.execute(statement)
        try:
            return [dict(row) for row in result.mappings().all()]
        except ResourceClosedError:
            return []

    async def targets(self) -> list[TargetInfo]:
        async with self.transaction():
            return [
                TargetInfo.model_validate(row)
                for row in await self.rows(
                    select(analysis_targets)
                    .where(analysis_targets.c.archived_at.is_(None))
                    .order_by(
                        analysis_targets.c.kind,
                        analysis_targets.c.name,
                        analysis_targets.c.id,
                    )
                )
            ]

    async def save_target(
        self, body: TargetWrite | TargetUpdate, target_id: UUID | None = None
    ) -> TargetInfo:
        async with self.transaction():
            if target_id is None:
                rows = await self.rows(
                    insert(analysis_targets)
                    .values(id=uuid4(), **body.model_dump(exclude={"version"}))
                    .returning(analysis_targets)
                )
            else:
                assert isinstance(body, TargetUpdate)
                rows = await self.rows(
                    update(analysis_targets)
                    .where(
                        analysis_targets.c.id == target_id,
                        analysis_targets.c.version == body.version,
                        analysis_targets.c.archived_at.is_(None),
                    )
                    .values(
                        kind=body.kind,
                        name=body.name,
                        description=body.description,
                        version=analysis_targets.c.version + 1,
                        updated_at=func.now(),
                    )
                    .returning(analysis_targets)
                )
                if not rows:
                    raise WorkflowConflict("분석 대상 없음 또는 버전 충돌")
            return TargetInfo.model_validate(rows[0])

    async def archive_target(self, target_id: UUID, version: int) -> None:
        async with self.transaction():
            rows = await self.rows(
                update(analysis_targets)
                .where(
                    analysis_targets.c.id == target_id,
                    analysis_targets.c.version == version,
                    analysis_targets.c.archived_at.is_(None),
                )
                .values(archived_at=func.now(), updated_at=func.now())
                .returning(analysis_targets.c.id)
            )
            if not rows:
                raise WorkflowConflict("분석 대상 없음 또는 버전 충돌")

    async def rules(self) -> list[FilterRuleInfo]:
        async with self.transaction():
            rows = await self.rows(
                select(article_filter_rules)
                .where(article_filter_rules.c.deleted_at.is_(None))
                .order_by(article_filter_rules.c.priority.desc(), article_filter_rules.c.id)
            )
            return [FilterRuleInfo.model_validate(row) for row in rows]

    async def _require_target(self, target_id: UUID | None) -> None:
        if target_id is None:
            return
        rows = await self.rows(
            select(analysis_targets.c.id).where(
                analysis_targets.c.id == target_id,
                analysis_targets.c.archived_at.is_(None),
            )
        )
        if not rows:
            raise WorkflowNotFound("분석 대상 없음")

    async def save_rule(
        self, body: FilterRuleWrite | FilterRuleUpdate, rule_id: UUID | None = None
    ) -> FilterRuleInfo:
        async with self.transaction():
            await self._require_target(body.target_id)
            definition = body.model_dump(mode="json", exclude={"version"}, by_alias=True)
            params = {
                "name": body.name,
                "target_id": body.target_id,
                "priority": body.priority,
                "decision": body.decision,
                "conditions": definition["conditions"],
                "enabled": body.enabled,
            }
            if rule_id is None:
                rows = await self.rows(
                    insert(article_filter_rules)
                    .values(id=uuid4(), **params)
                    .returning(article_filter_rules)
                )
            else:
                assert isinstance(body, FilterRuleUpdate)
                rows = await self.rows(
                    update(article_filter_rules)
                    .where(
                        article_filter_rules.c.id == rule_id,
                        article_filter_rules.c.version == body.version,
                        article_filter_rules.c.deleted_at.is_(None),
                    )
                    .values(
                        **params,
                        version=article_filter_rules.c.version + 1,
                        updated_at=func.now(),
                    )
                    .returning(article_filter_rules)
                )
                if not rows:
                    raise WorkflowConflict("판단 규칙 없음 또는 버전 충돌")
            rule = rows[0]
            await self.rows(
                insert(article_filter_rule_versions).values(
                    rule_id=rule["id"], version=rule["version"], definition=definition
                )
            )
            return FilterRuleInfo.model_validate(rule)

    async def rule_versions(self, rule_id: UUID) -> list[dict]:
        async with self.transaction():
            return await self.rows(
                select(
                    article_filter_rule_versions.c.version,
                    article_filter_rule_versions.c.definition,
                    article_filter_rule_versions.c.created_at,
                )
                .where(article_filter_rule_versions.c.rule_id == rule_id)
                .order_by(article_filter_rule_versions.c.version.desc())
            )

    async def delete_rule(self, rule_id: UUID, version: int) -> None:
        async with self.transaction():
            rows = await self.rows(
                update(article_filter_rules)
                .where(
                    article_filter_rules.c.id == rule_id,
                    article_filter_rules.c.version == version,
                    article_filter_rules.c.deleted_at.is_(None),
                )
                .values(deleted_at=func.now(), enabled=False, updated_at=func.now())
                .returning(article_filter_rules.c.id)
            )
            if not rows:
                raise WorkflowConflict("판단 규칙 없음 또는 버전 충돌")

    async def _article(self, article_id: UUID) -> dict:
        content = (
            select(article_contents.c.body)
            .where(article_contents.c.material_id == materials.c.id)
            .order_by(article_contents.c.created_at.desc(), article_contents.c.id.desc())
            .limit(1)
            .lateral("latest_content")
        )
        rows = await self.rows(
            select(
                materials.c.id,
                materials.c.kind,
                materials.c.title,
                func.coalesce(materials.c.summary, "").label("summary"),
                func.coalesce(content.c.body, "").label("body"),
            )
            .select_from(materials.outerjoin(content, literal(True)))
            .where(materials.c.id == article_id)
            .with_for_update(of=materials)
        )
        if not rows:
            raise WorkflowNotFound("기사 없음")
        if rows[0]["kind"] != "news":
            raise WorkflowInvalidMaterial("뉴스 기사에만 적용 가능")
        return rows[0]

    async def _current(self, article_id: UUID, target_id: UUID | None) -> dict | None:
        if target_id is None:
            rows = await self.rows(
                select(article_inclusions)
                .where(article_inclusions.c.article_id == article_id)
                .with_for_update()
            )
        else:
            rows = await self.rows(
                select(article_target_links)
                .where(
                    article_target_links.c.article_id == article_id,
                    article_target_links.c.target_id == target_id,
                )
                .with_for_update()
            )
        return rows[0] if rows else None

    async def _history(
        self,
        article_id: UUID,
        target_id: UUID | None,
        previous: str | None,
        decision: str | None,
        action: str,
        origin: str,
        reason: str,
        matched_terms: list[str],
        rule_id: UUID | None,
        rule_version: int | None,
    ) -> None:
        await self.rows(
            insert(article_decision_history).values(
                article_id=article_id,
                target_id=target_id,
                previous_decision=previous,
                decision=decision,
                action=action,
                origin=origin,
                reason=reason,
                matched_terms=matched_terms,
                rule_id=rule_id,
                rule_version=rule_version,
            )
        )

    async def _save_decision(
        self,
        article_id: UUID,
        target_id: UUID | None,
        decision: str,
        origin: str,
        reason: str,
        matched_terms: list[str] | None = None,
        rule_id: UUID | None = None,
        rule_version: int | None = None,
    ) -> DecisionInfo:
        current = await self._current(article_id, target_id)
        if current and current["origin"] == "manual" and origin == "auto":
            return DecisionInfo.model_validate(current)
        terms = matched_terms or []
        if current and all(
            current[key] == value
            for key, value in (
                ("decision", decision),
                ("origin", origin),
                ("reason", reason),
                ("matched_terms", terms),
                ("rule_id", rule_id),
                ("rule_version", rule_version),
            )
        ):
            return DecisionInfo.model_validate(current)
        if target_id is None:
            statement = pg_insert(article_inclusions).values(
                article_id=article_id,
                decision=decision,
                origin=origin,
                reason=reason,
                matched_terms=terms,
                rule_id=rule_id,
                rule_version=rule_version,
            )
            rows = await self.rows(
                statement.on_conflict_do_update(
                    index_elements=[article_inclusions.c.article_id],
                    set_={
                        "decision": statement.excluded.decision,
                        "origin": statement.excluded.origin,
                        "reason": statement.excluded.reason,
                        "matched_terms": statement.excluded.matched_terms,
                        "rule_id": statement.excluded.rule_id,
                        "rule_version": statement.excluded.rule_version,
                        "updated_at": func.now(),
                    },
                ).returning(article_inclusions)
            )
        else:
            statement = pg_insert(article_target_links).values(
                article_id=article_id,
                target_id=target_id,
                decision=decision,
                origin=origin,
                reason=reason,
                matched_terms=terms,
                rule_id=rule_id,
                rule_version=rule_version,
            )
            rows = await self.rows(
                statement.on_conflict_do_update(
                    index_elements=[
                        article_target_links.c.article_id,
                        article_target_links.c.target_id,
                    ],
                    set_={
                        "decision": statement.excluded.decision,
                        "origin": statement.excluded.origin,
                        "reason": statement.excluded.reason,
                        "matched_terms": statement.excluded.matched_terms,
                        "rule_id": statement.excluded.rule_id,
                        "rule_version": statement.excluded.rule_version,
                        "updated_at": func.now(),
                    },
                ).returning(article_target_links)
            )
        await self._history(
            article_id,
            target_id,
            current["decision"] if current else None,
            decision,
            "override" if origin == "manual" else "evaluate",
            origin,
            reason,
            terms,
            rule_id,
            rule_version,
        )
        return DecisionInfo.model_validate({**rows[0], "target_id": target_id})

    async def _remove_auto(self, article_id: UUID, target_id: UUID | None) -> None:
        current = await self._current(article_id, target_id)
        if not current or current["origin"] == "manual":
            return
        await self.rows(
            delete(article_target_links).where(
                article_target_links.c.article_id == article_id,
                article_target_links.c.target_id == target_id,
                article_target_links.c.origin == "auto",
            )
        )
        await self._history(
            article_id,
            target_id,
            current["decision"],
            None,
            "release",
            "auto",
            "일치하는 판단 규칙 없음",
            [],
            None,
            None,
        )

    async def inclusion(self, article_id: UUID) -> DecisionInfo:
        async with self.transaction():
            await self._article(article_id)
            current = await self._current(article_id, None)
            return (
                DecisionInfo.model_validate(current)
                if current
                else DecisionInfo(
                    article_id=article_id, decision="include", origin="auto", reason=""
                )
            )

    async def require_news(self, article_id: UUID) -> None:
        async with self.transaction():
            await self._article(article_id)

    async def target_links(self, article_id: UUID) -> list[DecisionInfo]:
        async with self.transaction():
            await self._article(article_id)
            rows = await self.rows(
                select(article_target_links)
                .where(article_target_links.c.article_id == article_id)
                .order_by(article_target_links.c.target_id)
            )
            return [DecisionInfo.model_validate(row) for row in rows]

    async def history(self, article_id: UUID) -> list[DecisionHistory]:
        async with self.transaction():
            await self._article(article_id)
            rows = await self.rows(
                select(article_decision_history)
                .where(article_decision_history.c.article_id == article_id)
                .order_by(
                    article_decision_history.c.created_at.desc(),
                    article_decision_history.c.id.desc(),
                )
                .limit(200)
            )
            return [DecisionHistory.model_validate(row) for row in rows]

    async def override(
        self, article_id: UUID, body: DecisionWrite, target_id: UUID | None = None
    ) -> DecisionInfo | None:
        async with self.transaction():
            await self._article(article_id)
            await self._require_target(target_id)
            if body.decision == "release":
                current = await self._current(article_id, target_id)
                if current and current["origin"] == "manual":
                    table = article_inclusions if target_id is None else article_target_links
                    criteria = [table.c.article_id == article_id]
                    if target_id is not None:
                        criteria.append(table.c.target_id == target_id)
                    await self.rows(delete(table).where(*criteria))
                    await self._history(
                        article_id,
                        target_id,
                        current["decision"],
                        None,
                        "release",
                        "manual",
                        body.reason,
                        [],
                        None,
                        None,
                    )
                return None
            return await self._save_decision(
                article_id, target_id, body.decision, "manual", body.reason
            )

    @staticmethod
    def matches(conditions: FilterConditions, text_value: str) -> list[str] | None:
        body = text_value.casefold()
        if any(term.casefold() not in body for term in conditions.all_terms):
            return None
        matched_any = [term for term in conditions.any_terms if term.casefold() in body]
        if conditions.any_terms and not matched_any:
            return None
        if any(term.casefold() in body for term in conditions.none_terms):
            return None
        return [*conditions.all_terms, *matched_any]

    async def evaluate(
        self, article_id: UUID, target_scope: UUID | None = None
    ) -> EvaluationResult:
        async with self.transaction():
            article = await self._article(article_id)
            await self._require_target(target_scope)
            body = " ".join((article["title"], article["summary"], article["body"]))
            rules_query = select(article_filter_rules).where(
                article_filter_rules.c.enabled.is_(True),
                article_filter_rules.c.deleted_at.is_(None),
            )
            targets_query = select(analysis_targets.c.id).where(
                analysis_targets.c.archived_at.is_(None)
            )
            if target_scope is not None:
                rules_query = rules_query.where(article_filter_rules.c.target_id == target_scope)
                targets_query = targets_query.where(analysis_targets.c.id == target_scope)
            rules = await self.rows(
                rules_query.order_by(
                    article_filter_rules.c.priority.desc(), article_filter_rules.c.id
                )
            )
            target_rows = await self.rows(targets_query)
            matched: dict[UUID | None, list[tuple[dict, list[str]]]] = {}
            for rule in rules:
                conditions = FilterConditions.model_validate(rule["conditions"])
                terms = self.matches(conditions, body)
                if terms is not None:
                    matched.setdefault(rule["target_id"], []).append((rule, terms))
            global_rules = matched.get(None, [])
            if target_scope is not None:
                current = await self._current(article_id, None)
                inclusion = (
                    DecisionInfo.model_validate(current)
                    if current
                    else DecisionInfo(
                        article_id=article_id, decision="include", origin="auto", reason=""
                    )
                )
            elif global_rules:
                winning, terms = global_rules[0]
                inclusion = await self._save_decision(
                    article_id,
                    None,
                    winning["decision"],
                    "auto",
                    winning["name"],
                    terms,
                    winning["id"],
                    winning["version"],
                )
            else:
                current = await self._current(article_id, None)
                if current and current["origin"] == "auto":
                    inclusion = await self._save_decision(
                        article_id, None, "include", "auto", "일치하는 판단 규칙 없음"
                    )
                else:
                    inclusion = (
                        DecisionInfo.model_validate(current)
                        if current
                        else DecisionInfo(
                            article_id=article_id, decision="include", origin="auto", reason=""
                        )
                    )
            targets: list[DecisionInfo] = []
            for target in target_rows:
                target_id = target["id"]
                applicable = matched.get(target_id, [])
                if applicable:
                    winning, terms = applicable[0]
                    targets.append(
                        await self._save_decision(
                            article_id,
                            target_id,
                            winning["decision"],
                            "auto",
                            winning["name"],
                            terms,
                            winning["id"],
                            winning["version"],
                        )
                    )
                else:
                    await self._remove_auto(article_id, target_id)
            return EvaluationResult(
                article_id=article_id,
                inclusion=inclusion,
                targets=targets,
                matched_rule_ids=[
                    rule["id"] for ruleset in matched.values() for rule, _ in ruleset
                ],
            )

    async def reapply(self, body: ReapplyRequest) -> ReapplyResult:
        async with self.transaction():
            await self._require_target(body.target_id)
            if body.scope == "selected":
                ids = list(dict.fromkeys(body.article_ids or []))
                existing = await self.rows(
                    select(materials.c.id, materials.c.kind).where(materials.c.id.in_(ids))
                )
                if len(existing) != len(ids):
                    raise WorkflowNotFound("선택 기사 없음")
                if any(row["kind"] != "news" for row in existing):
                    raise WorkflowInvalidMaterial("선택 항목에 뉴스 이외 자료 포함")
            else:
                statement = (
                    select(materials.c.id)
                    .where(materials.c.kind == "news")
                    .order_by(materials.c.id)
                )
                ids = [row["id"] for row in await self.rows(statement)]
        for article_id in ids:
            await self.evaluate(article_id, body.target_id if body.scope == "target" else None)
        return ReapplyResult(processed_count=len(ids))
