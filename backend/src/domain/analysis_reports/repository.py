from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import (
    and_,
    case,
    delete,
    func,
    insert,
    literal,
    null,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from domain.analysis_reports.models import (
    RelevanceEnqueue,
    RelevancePreview,
    RelevanceRequest,
    ReportArticle,
    ReportArticleDetail,
    ReportArticlePage,
    ReportBulkDecision,
    ReportCreate,
    ReportDecisionWrite,
    ReportInfo,
    ReportUpdate,
)
from domain.analysis_reports.pricing import ESTIMATED_OUTPUT_TOKENS, estimate_request_cost
from domain.analysis_reports.tables import (
    analysis_report_decision_history,
    analysis_report_decisions,
    analysis_reports,
    report_relevance_runs,
)
from domain.article_workflow.membership import is_target_member
from domain.article_workflow.tables import analysis_targets
from domain.collection.tables import (
    article_contents,
    articles,
    collection_rule_targets,
    collection_rules,
)


class AnalysisReportError(RuntimeError):
    pass


class AnalysisReportNotFound(AnalysisReportError):
    pass


class AnalysisReportConflict(AnalysisReportError):
    pass


class AnalysisReportInvalid(AnalysisReportError):
    pass


class AnalysisReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _rows(self, statement):
        return [dict(x) for x in (await self._session.execute(statement)).mappings().all()]

    async def _terms(self, target_id: UUID, override) -> list[str]:
        if override is not None:
            return list(override)
        rows = await self._rows(
            select(collection_rules.c.definition)
            .select_from(
                collection_rules.join(
                    collection_rule_targets,
                    collection_rules.c.id == collection_rule_targets.c.rule_id,
                )
            )
            .where(collection_rule_targets.c.target_id == target_id)
        )
        result: list[str] = []
        for row in rows:
            definition = row["definition"] or {}
            for term in definition.get("terms", []):
                if isinstance(term, str) and term.strip() and term.strip() not in result:
                    result.append(term.strip())
        return result

    async def _info(self, row: dict) -> ReportInfo:
        return ReportInfo.model_validate(
            {
                **row,
                "keyword_terms": await self._terms(row["target_id"], row["keywords_override"]),
                "keywords_automatic": row["keywords_override"] is None,
            }
        )

    async def get(self, report_id: UUID) -> ReportInfo:
        rows = await self._rows(select(analysis_reports).where(analysis_reports.c.id == report_id))
        if not rows:
            raise AnalysisReportNotFound("보고서 없음")
        return await self._info(rows[0])

    async def delete(self, report_id: UUID, version: int) -> None:
        current = await self._session.scalar(
            select(analysis_reports.c.version)
            .where(analysis_reports.c.id == report_id)
            .with_for_update()
        )
        if current is None:
            raise AnalysisReportNotFound("보고서 없음")
        if current != version:
            raise AnalysisReportConflict("보고서가 변경됐습니다. 새로고침 후 삭제해 주세요.")
        # 이미 모델 호출을 시작한 실행과 대기 실행 삭제 사이의 경합 방지
        statuses = await self._session.scalars(
            select(report_relevance_runs.c.status)
            .where(report_relevance_runs.c.report_id == report_id)
            .with_for_update()
        )
        if "running" in statuses.all():
            raise AnalysisReportConflict("진행 중인 AI 판정이 있습니다. 완료 후 삭제해 주세요.")
        await self._session.execute(
            delete(analysis_reports).where(analysis_reports.c.id == report_id)
        )
        await self._session.commit()

    async def list(
        self, kind: str | None = None, target_id: UUID | None = None
    ) -> list[ReportInfo]:
        stmt = select(analysis_reports).order_by(
            analysis_reports.c.target_kind,
            analysis_reports.c.target_id,
            analysis_reports.c.is_default.desc(),
            analysis_reports.c.created_at,
            analysis_reports.c.id,
        )
        if kind:
            stmt = stmt.where(analysis_reports.c.target_kind == kind)
        if target_id:
            stmt = stmt.where(analysis_reports.c.target_id == target_id)
        return [await self._info(row) for row in await self._rows(stmt)]

    async def create(self, body: ReportCreate) -> ReportInfo:
        target = await self._rows(
            select(analysis_targets).where(
                analysis_targets.c.id == body.target_id, analysis_targets.c.archived_at.is_(None)
            )
        )
        if not target or target[0]["kind"] not in ("regular", "current_issue"):
            raise AnalysisReportInvalid("보고서 지원 분석 대상 없음")
        override = null() if body.keywords_automatic else (body.keyword_terms or [])
        title = body.title.strip() if body.title else target[0]["name"]
        if not title:
            raise AnalysisReportInvalid("보고서 제목 필요")
        rows = await self._rows(
            insert(analysis_reports)
            .values(
                id=uuid4(),
                target_id=body.target_id,
                target_kind=target[0]["kind"],
                title=title,
                description=target[0]["description"]
                if body.description is None
                else body.description,
                relevance_criteria="\n".join(
                    value for value in (target[0]["name"], target[0]["description"]) if value
                ),
                keywords_override=override,
                start_at=body.start_at,
                end_at=body.end_at,
            )
            .returning(analysis_reports)
        )
        await self._session.commit()
        return await self._info(rows[0])

    async def update(self, report_id: UUID, body: ReportUpdate) -> ReportInfo:
        current = await self.get(report_id)
        start_at = body.start_at if "start_at" in body.model_fields_set else current.start_at
        end_at = body.end_at if "end_at" in body.model_fields_set else current.end_at
        if start_at is not None and end_at is not None and start_at >= end_at:
            raise AnalysisReportInvalid("보고서 종료 시각은 시작 시각 이후 필요")
        values = {"version": analysis_reports.c.version + 1, "updated_at": func.now()}
        for key in ("title", "description", "start_at", "end_at", "relevance_criteria"):
            if key in body.model_fields_set:
                values[key] = getattr(body, key)
        if body.keywords_automatic is not None:
            values["keywords_override"] = (
                null() if body.keywords_automatic else (body.keyword_terms or [])
            )
        elif body.keyword_terms is not None:
            values["keywords_override"] = body.keyword_terms
        rows = await self._rows(
            update(analysis_reports)
            .where(analysis_reports.c.id == report_id, analysis_reports.c.version == body.version)
            .values(**values)
            .returning(analysis_reports)
        )
        if not rows:
            raise AnalysisReportConflict("보고서 없음 또는 버전 충돌")
        await self._session.commit()
        return await self._info(rows[0])

    @staticmethod
    def _escaped(term: str) -> str:
        return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _matches_terms(self, content_id, terms: Sequence[str]):
        if not terms:
            return literal(False)
        patterns = ["%" + self._escaped(term) + "%" for term in terms]
        title_matches = (
            select(articles.c.id)
            .where(or_(*(articles.c.title.ilike(pattern, escape="\\") for pattern in patterns)))
            .correlate(None)
        )
        body_matches = (
            select(article_contents.c.id)
            .where(
                or_(*(article_contents.c.body.ilike(pattern, escape="\\") for pattern in patterns))
            )
            .correlate(None)
        )
        # 과거 본문만 일치하는 기사를 포함하지 않도록 최신 본문 ID로 비교
        return func.coalesce(
            or_(articles.c.id.in_(title_matches), content_id.in_(body_matches)), False
        )

    def _classified_candidates(
        self, report: ReportInfo, q: str | None = None, article_ids: Sequence[UUID] | None = None
    ):
        report_id = report.id
        terms = report.keyword_terms
        eligible = select(articles.c.id).where(is_target_member(articles.c.id, report.target_id))
        if article_ids is not None:
            eligible = eligible.where(articles.c.id.in_(article_ids))
        if report.start_at is not None:
            eligible = eligible.where(articles.c.original_published_at >= report.start_at)
        if report.end_at is not None:
            eligible = eligible.where(articles.c.original_published_at < report.end_at)
        eligible_ids = eligible.cte("report_eligible_articles").prefix_with(
            "MATERIALIZED", dialect="postgresql"
        )
        # 키워드와 집계마다 본문 이력을 다시 탐색하지 않도록 최신 버전 고정
        latest = (
            select(
                article_contents.c.article_id,
                article_contents.c.id.label("content_id"),
                article_contents.c.content_hash,
            )
            .where(article_contents.c.article_id.in_(select(eligible_ids.c.id)))
            .ext(distinct_on(article_contents.c.article_id))
            .order_by(
                article_contents.c.article_id,
                article_contents.c.created_at.desc(),
                article_contents.c.id.desc(),
            )
            .cte("report_latest_bodies")
            .prefix_with("MATERIALIZED", dialect="postgresql")
        )
        criteria_hash = sha256(report.relevance_criteria.encode()).hexdigest()
        runs = (
            select(report_relevance_runs)
            .where(report_relevance_runs.c.report_id == report_id)
            .order_by(
                report_relevance_runs.c.article_id,
                report_relevance_runs.c.created_at.desc(),
                report_relevance_runs.c.id.desc(),
            )
            .ext(distinct_on(report_relevance_runs.c.article_id))
            .cte("report_latest_relevance")
            .prefix_with("MATERIALIZED", dialect="postgresql")
        )
        keyword_match = self._matches_terms(latest.c.content_id, terms)
        ai_status = case(
            (runs.c.status.is_(None), "unjudged"),
            (
                or_(
                    runs.c.content_hash.is_distinct_from(latest.c.content_hash),
                    runs.c.criteria_hash.is_distinct_from(criteria_hash),
                    runs.c.title.is_distinct_from(articles.c.title),
                ),
                "outdated",
            ),
            else_=runs.c.status,
        ).label("ai_status")
        base = (
            select(
                articles.c.id,
                articles.c.title,
                articles.c.original_published_at,
                keyword_match.label("is_keyword_match"),
                analysis_report_decisions.c.decision.label("report_decision"),
                analysis_report_decisions.c.reason.label("report_decision_reason"),
                latest.c.content_id,
                latest.c.content_hash,
                runs.c.id.label("relevance_run_id"),
                runs.c.status.label("run_status"),
                runs.c.relevance.label("ai_relevance"),
                ai_status,
            )
            .select_from(
                articles.outerjoin(latest, latest.c.article_id == articles.c.id)
                .outerjoin(
                    analysis_report_decisions,
                    and_(
                        analysis_report_decisions.c.report_id == report_id,
                        analysis_report_decisions.c.article_id == articles.c.id,
                    ),
                )
                .outerjoin(runs, runs.c.article_id == articles.c.id)
            )
            .where(articles.c.id.in_(select(eligible_ids.c.id)))
        )
        if q:
            base = base.where(self._matches_terms(latest.c.content_id, [q]))
        # 집계 중간 결과에는 본문·요약·AI 근거를 담지 않고 선택 페이지에서만 조회
        return base.cte("classified_report_candidates").prefix_with(
            "MATERIALIZED", dialect="postgresql"
        )

    @staticmethod
    def _candidate_filters(classified, keyword_match, inclusion, ai_relevance, has_terms):
        filters = []
        if keyword_match == "unmatched":
            filters.append(~classified.c.is_keyword_match if has_terms else literal(False))
        if keyword_match == "matched":
            filters.append(classified.c.is_keyword_match)
        if inclusion == "included":
            filters.append(classified.c.report_decision == "include")
        elif inclusion == "unreviewed":
            filters.append(classified.c.report_decision.is_(None))
        elif inclusion == "excluded":
            filters.append(classified.c.report_decision == "exclude")
        if ai_relevance == "unjudged":
            filters.append(classified.c.ai_status == "unjudged")
        elif ai_relevance == "pending":
            filters.append(classified.c.ai_status.in_(("queued", "submitted", "running")))
        elif ai_relevance in ("failed", "outdated"):
            filters.append(classified.c.ai_status == ai_relevance)
        elif ai_relevance in ("related", "unrelated", "uncertain"):
            filters.append(
                and_(
                    classified.c.ai_status == "completed", classified.c.ai_relevance == ai_relevance
                )
            )
        return filters

    async def articles(
        self,
        report_id: UUID,
        keyword_match: str,
        inclusion: str,
        q: str | None,
        offset: int,
        limit: int,
        ai_relevance: str = "all",
    ) -> ReportArticlePage:
        report = await self.get(report_id)
        terms = report.keyword_terms
        classified = self._classified_candidates(report, q)
        unmatched = ~classified.c.is_keyword_match if terms else literal(False)
        filters = self._candidate_filters(
            classified, keyword_match, inclusion, ai_relevance, bool(terms)
        )
        # 동일한 판정 집합에서 건수와 페이지를 함께 조회해 결과 범위 일치
        statistics = (
            select(
                func.count().label("total"),
                func.count().filter(classified.c.is_keyword_match).label("matched"),
                func.count().filter(unmatched).label("unmatched"),
                func.count().filter(classified.c.report_decision == "include").label("included"),
                func.count().filter(classified.c.report_decision == "exclude").label("excluded"),
                func.count().filter(classified.c.report_decision.is_(None)).label("unreviewed"),
                func.count().filter(classified.c.ai_status == "unjudged").label("ai_unjudged"),
                func.count()
                .filter(
                    and_(
                        classified.c.ai_status == "completed",
                        classified.c.ai_relevance == "related",
                    )
                )
                .label("ai_related"),
                func.count()
                .filter(
                    and_(
                        classified.c.ai_status == "completed",
                        classified.c.ai_relevance == "unrelated",
                    )
                )
                .label("ai_unrelated"),
                func.count()
                .filter(
                    and_(
                        classified.c.ai_status == "completed",
                        classified.c.ai_relevance == "uncertain",
                    )
                )
                .label("ai_uncertain"),
                func.count()
                .filter(classified.c.ai_status.in_(("queued", "submitted", "running")))
                .label("ai_pending"),
                func.count().filter(classified.c.ai_status == "failed").label("ai_failed"),
                func.count().filter(classified.c.ai_status == "outdated").label("ai_outdated"),
                func.count()
                .filter(and_(*filters) if filters else literal(True))
                .label("filtered_total"),
            )
            .select_from(classified)
            .cte("report_statistics")
        )
        page = (
            select(classified)
            .where(*filters)
            .order_by(classified.c.original_published_at.desc().nullslast(), classified.c.id)
            .offset(offset)
            .limit(limit)
            .subquery("report_page")
        )
        rows = await self._rows(
            select(
                statistics,
                page,
                func.coalesce(articles.c.summary, "").label("summary"),
                articles.c.publisher,
                func.coalesce(article_contents.c.body, "").label("body"),
                report_relevance_runs.c.reason.label("ai_reason"),
                report_relevance_runs.c.evidence.label("ai_evidence"),
            )
            .select_from(
                statistics.outerjoin(page, literal(True))
                .outerjoin(articles, articles.c.id == page.c.id)
                .outerjoin(article_contents, article_contents.c.id == page.c.content_id)
                .outerjoin(
                    report_relevance_runs, report_relevance_runs.c.id == page.c.relevance_run_id
                )
            )
            .order_by(page.c.original_published_at.desc().nullslast(), page.c.id)
        )
        countrow = {
            key: rows[0][key]
            for key in (
                "total",
                "matched",
                "unmatched",
                "included",
                "excluded",
                "unreviewed",
                "ai_unjudged",
                "ai_related",
                "ai_unrelated",
                "ai_uncertain",
                "ai_pending",
                "ai_failed",
                "ai_outdated",
                "filtered_total",
            )
        }
        items = []
        for row in rows:
            if row["id"] is None:
                continue
            matched_terms = [
                t
                for t in terms
                if any(t.casefold() in (str(row[k]) or "").casefold() for k in ("title", "body"))
            ]
            items.append(
                ReportArticle(
                    id=row["id"],
                    title=row["title"],
                    summary=row["summary"],
                    publisher=row["publisher"],
                    original_published_at=row["original_published_at"],
                    content_preview=(row["body"] or "")[:500],
                    is_keyword_match=row["is_keyword_match"],
                    matched_keywords=matched_terms,
                    report_decision=row["report_decision"],
                    report_decision_reason=row["report_decision_reason"],
                    ai_status=row["ai_status"],
                    ai_relevance=row["ai_relevance"],
                    ai_reason=row["ai_reason"],
                    ai_evidence=row["ai_evidence"] or [],
                )
            )
        return ReportArticlePage(items=items, **countrow)

    async def _apply_decision(
        self, report_id: UUID, article_id: UUID, body: ReportDecisionWrite
    ) -> None:
        report = await self.get(report_id)
        valid = await self._rows(
            select(articles.c.id).where(
                articles.c.id == article_id, is_target_member(articles.c.id, report.target_id)
            )
        )
        if not valid:
            raise AnalysisReportInvalid("보고서 대상 기사 없음")
        previous = await self._session.scalar(
            select(analysis_report_decisions.c.decision).where(
                analysis_report_decisions.c.report_id == report_id,
                analysis_report_decisions.c.article_id == article_id,
            )
        )
        if body.decision == "release":
            await self._session.execute(
                delete(analysis_report_decisions).where(
                    analysis_report_decisions.c.report_id == report_id,
                    analysis_report_decisions.c.article_id == article_id,
                )
            )
        else:
            stmt = pg_insert(analysis_report_decisions).values(
                report_id=report_id,
                article_id=article_id,
                decision=body.decision,
                reason=body.reason,
            )
            await self._session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[
                        analysis_report_decisions.c.report_id,
                        analysis_report_decisions.c.article_id,
                    ],
                    set_={
                        "decision": stmt.excluded.decision,
                        "reason": stmt.excluded.reason,
                        "updated_at": func.now(),
                    },
                )
            )
        await self._session.execute(
            insert(analysis_report_decision_history).values(
                report_id=report_id,
                article_id=article_id,
                previous_decision=previous,
                action=body.decision,
                reason=body.reason,
            )
        )

    async def decide(self, report_id: UUID, article_id: UUID, body: ReportDecisionWrite) -> None:
        await self._apply_decision(report_id, article_id, body)
        await self._session.commit()

    async def decide_bulk(self, report_id: UUID, body: ReportBulkDecision) -> None:
        ids = list(dict.fromkeys(body.article_ids))
        report = await self.get(report_id)
        valid = await self._rows(
            select(articles.c.id).where(
                articles.c.id.in_(ids), is_target_member(articles.c.id, report.target_id)
            )
        )
        if len(valid) != len(ids):
            raise AnalysisReportInvalid("보고서 대상 기사 없음")
        for article_id in ids:
            await self._apply_decision(report_id, article_id, body)
        await self._session.commit()

    async def _relevance_candidates(
        self, report_id: UUID, request: RelevanceRequest
    ) -> tuple[ReportInfo, Sequence[dict]]:
        report = await self.get(report_id)
        if request.scope == "selected" and not request.article_ids:
            raise AnalysisReportInvalid("선택 기사 필요")
        selected = list(dict.fromkeys(request.article_ids)) if request.scope == "selected" else None
        classified = self._classified_candidates(report, request.q, selected)
        filters = self._candidate_filters(
            classified,
            request.keyword_match,
            request.inclusion,
            request.ai_relevance,
            bool(report.keyword_terms),
        )
        rows = await self._rows(
            select(
                classified,
                func.coalesce(articles.c.summary, "").label("summary"),
                articles.c.publisher,
                func.coalesce(article_contents.c.body, "").label("body"),
                report_relevance_runs.c.reason.label("ai_reason"),
                report_relevance_runs.c.evidence.label("ai_evidence"),
                report_relevance_runs.c.error.label("ai_error"),
                classified.c.id.label("article_id"),
                classified.c.report_decision.label("decision"),
                classified.c.report_decision_reason.label("decision_reason"),
                classified.c.run_status.label("status"),
                classified.c.ai_relevance.label("relevance"),
            )
            .select_from(
                classified.join(articles, articles.c.id == classified.c.id)
                .outerjoin(article_contents, article_contents.c.id == classified.c.content_id)
                .outerjoin(
                    report_relevance_runs,
                    report_relevance_runs.c.id == classified.c.relevance_run_id,
                )
            )
            .where(*filters)
        )
        return report, rows

    @staticmethod
    def _relevance_preview(
        report: ReportInfo, rows: Sequence[dict], request: RelevanceRequest
    ) -> tuple[RelevancePreview, Sequence[dict]]:
        if not report.relevance_criteria.strip():
            raise AnalysisReportInvalid("관련성 선별 기준 필요")
        criteria_hash = sha256(report.relevance_criteria.encode()).hexdigest()
        eligible: list[dict] = []
        no_body = excluded = current = pending = 0
        for row in rows:
            if row["decision"] == "exclude":
                excluded += 1
                continue
            if not (row["body"] or "").strip() or not row["content_hash"]:
                no_body += 1
                continue
            valid = row["ai_status"] not in ("unjudged", "outdated")
            active = valid and row["status"] in ("queued", "submitted", "running")
            if active:
                current += 1
                pending += 1
                continue
            if request.mode == "unjudged" and valid and row["status"] == "completed":
                current += 1
                continue
            if request.mode == "failed" and not (valid and row["status"] == "failed"):
                continue
            eligible.append(row)
        fingerprint_source = f"{report.id}:{criteria_hash}\n" + "\n".join(
            f"{row['article_id']}:{row['content_hash']}:{row['title']}:{criteria_hash}"
            for row in sorted(eligible, key=lambda value: str(value["article_id"]))
        )
        input_estimates = [
            len(row["title"].encode())
            + len(row["body"].encode())
            + 2 * len(report.relevance_criteria.encode())
            + 800
            for row in eligible
        ]
        preview = RelevancePreview(
            eligible=len(eligible),
            skipped_no_body=no_body,
            skipped_excluded=excluded,
            skipped_current=current,
            pending=pending,
            estimated_input_tokens=sum(input_estimates),
            estimated_output_tokens=ESTIMATED_OUTPUT_TOKENS * len(eligible),
            estimated_cost_usd=float(
                sum(estimate_request_cost(value) for value in input_estimates)
            ),
            fingerprint=sha256(fingerprint_source.encode()).hexdigest(),
        )
        return preview, eligible

    async def preview_relevance(
        self, report_id: UUID, request: RelevanceRequest
    ) -> RelevancePreview:
        report, rows = await self._relevance_candidates(report_id, request)
        preview, _ = self._relevance_preview(report, rows, request)
        return preview

    async def enqueue_relevance(
        self, report_id: UUID, request: RelevanceRequest
    ) -> RelevanceEnqueue:
        if not request.preview_fingerprint:
            raise AnalysisReportInvalid("미리보기 지문 필요")
        # 같은 보고서의 중복 클릭과 기준 수정 사이에 실행 범위 고정
        locked = await self._session.scalar(
            select(analysis_reports.c.id)
            .where(analysis_reports.c.id == report_id)
            .with_for_update()
        )
        if locked is None:
            raise AnalysisReportNotFound("보고서 없음")
        report, rows = await self._relevance_candidates(report_id, request)
        preview, eligible = self._relevance_preview(report, rows, request)
        if preview.fingerprint != request.preview_fingerprint:
            raise AnalysisReportConflict("분석 대상이 변경됨")
        criteria_hash = sha256(report.relevance_criteria.encode()).hexdigest()
        batch_id = (await self._session.execute(select(func.uuidv7()))).scalar_one()
        queued, reused = 0, preview.skipped_current
        for row in eligible:
            inserted = await self._session.scalar(
                pg_insert(report_relevance_runs)
                .values(
                    batch_id=batch_id,
                    report_id=report_id,
                    article_id=row["article_id"],
                    content_id=row["content_id"],
                    content_hash=row["content_hash"],
                    title=row["title"],
                    criteria=report.relevance_criteria,
                    criteria_hash=criteria_hash,
                    model="gpt-6-luna",
                    status="queued",
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        report_relevance_runs.c.report_id,
                        report_relevance_runs.c.article_id,
                        report_relevance_runs.c.content_hash,
                        report_relevance_runs.c.criteria_hash,
                    ],
                    index_where=report_relevance_runs.c.status.in_(
                        ("queued", "submitted", "running")
                    ),
                )
                .returning(report_relevance_runs.c.id)
            )
            if inserted is None:
                reused += 1
            else:
                queued += 1
        await self._session.commit()
        return RelevanceEnqueue(batch_id=batch_id, queued=queued, reused=reused)

    async def article_detail(self, report_id: UUID, article_id: UUID) -> ReportArticleDetail:
        request = RelevanceRequest(scope="selected", article_ids=[article_id])
        report, rows = await self._relevance_candidates(report_id, request)
        if not rows:
            raise AnalysisReportNotFound("보고서 대상 기사 없음")
        row = rows[0]
        status = row["ai_status"]
        return ReportArticleDetail(
            id=row["article_id"],
            title=row["title"],
            summary=row["summary"] or "",
            publisher=row["publisher"],
            original_published_at=row["original_published_at"],
            content_preview=(row["body"] or "")[:500],
            is_keyword_match=row["is_keyword_match"],
            matched_keywords=[
                term
                for term in report.keyword_terms
                if term.casefold() in ((row["title"] or "") + " " + (row["body"] or "")).casefold()
            ],
            report_decision=row["decision"],
            report_decision_reason=row["decision_reason"],
            body=row["body"],
            content_hash=row["content_hash"],
            ai_status=status,
            ai_relevance=row["relevance"],
            ai_reason=row["ai_reason"],
            ai_evidence=row["ai_evidence"] or [],
            ai_error=row["ai_error"],
        )
