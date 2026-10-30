"use client";

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { post, put, remove, type Schema, useApi } from "@/shared/api/client";
import { useListLocation } from "@/shared/lib/list-location";
import {
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
  Pager,
} from "@/shared/ui/feedback";
import type { AnalysisTarget } from "../articles/types";

type ReportKind = "regular" | "current_issue";
type KeywordMatch = "all" | "matched" | "unmatched";
type ReviewInclusion = "all" | "unreviewed" | "included" | "excluded";
type AiRelevance =
  | "all"
  | "unjudged"
  | "related"
  | "unrelated"
  | "uncertain"
  | "failed"
  | "pending"
  | "outdated";

type AnalysisReport = Schema["ReportInfo"];
type ReportArticle = Schema["ReportArticle"];
type ReportArticlePage = Schema["ReportArticlePage"];
type RelevancePreview = Schema["RelevancePreview"];
type ArticleDetail = Schema["ReportArticleDetail"];

const reportTabs: { value: ReportKind; label: string }[] = [
  { value: "regular", label: "정기 분석" },
  { value: "current_issue", label: "현안 분석" },
];

const keywordTabs: { value: KeywordMatch; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "matched", label: "키워드 일치" },
  { value: "unmatched", label: "키워드 불일치" },
];

function formatDate(value: string | null) {
  if (!value) return "발행시각 없음";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat("ko-KR", {
        timeZone: "Asia/Seoul",
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function dateTimeInput(value: string | null) {
  if (!value) return "";
  const parts = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value ?? "00";
  return `${part("year")}-${part("month")}-${part("day")}T${part("hour")}:${part("minute")}`;
}

function toIso(value: string) {
  return value ? new Date(`${value}:00+09:00`).toISOString() : null;
}

function reportKindForTarget(kind: AnalysisTarget["kind"]): ReportKind | null {
  if (kind === "regular") return "regular";
  if (kind === "current_issue") return "current_issue";
  return null;
}

function aiLabel(
  status: ReportArticle["ai_status"],
  relevance: ReportArticle["ai_relevance"],
) {
  if (status === "outdated") return "이전 기준";
  if (status === "failed") return "실패";
  if (["queued", "submitted", "running"].includes(status)) return "처리 중";
  if (status !== "completed") return "미판정";
  return relevance === "related"
    ? "관련"
    : relevance === "unrelated"
      ? "무관"
      : relevance === "uncertain"
        ? "보류"
        : "미판정";
}

function highlightedText(text: string, terms: string[]) {
  const pattern = terms
    .filter(Boolean)
    .map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|");
  if (!pattern) return text;
  let offset = 0;
  return text.split(new RegExp(`(${pattern})`, "gi")).map((part) => {
    const key = `${part}-${offset}`;
    offset += part.length;
    return new RegExp(`^(?:${pattern})$`, "i").test(part) ? (
      <mark key={key}>{part}</mark>
    ) : (
      part
    );
  });
}

export function AnalysisReportsWorkspace() {
  const { params: location, offset, update } = useListLocation();
  const selectedKind = (location.get("kind") ?? "regular") as ReportKind;
  const selectedReportId = location.get("report_id") ?? "";
  const targetId = location.get("target_id") ?? "";
  const keywordMatch = (location.get("keyword_match") ?? "all") as KeywordMatch;
  const inclusion = (location.get("inclusion") ?? "all") as ReviewInclusion;
  const aiRelevance = (location.get("ai_relevance") ?? "all") as AiRelevance;
  const queryText = location.get("q") ?? "";
  const [text, setText] = useState(queryText);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [keywordText, setKeywordText] = useState("");
  const [startAt, setStartAt] = useState("");
  const [endAt, setEndAt] = useState("");
  const [relevanceCriteria, setRelevanceCriteria] = useState("");
  const [editingLoaded, setEditingLoaded] = useState("");
  const [saveError, setSaveError] = useState<Error | null>(null);
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<Error | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] =
    useState<AnalysisReport | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<Error | null>(null);
  const [newTargetId, setNewTargetId] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [decisionReason, setDecisionReason] = useState("");
  const [preview, setPreview] = useState<RelevancePreview | null>(null);
  const [previewMode, setPreviewMode] = useState<
    "unjudged" | "failed" | "refresh"
  >("unjudged");
  const [previewScope, setPreviewScope] = useState<"selected" | "filtered">(
    "filtered",
  );
  const [previewError, setPreviewError] = useState<Error | null>(null);
  const [running, setRunning] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const detailTrigger = useRef<HTMLButtonElement | null>(null);
  const reports = useApi<AnalysisReport[]>(
    `/analysis-reports?${new URLSearchParams({ kind: selectedKind, ...(targetId ? { target_id: targetId } : {}) })}`,
    false,
  );
  const report = useApi<AnalysisReport>(
    selectedReportId ? `/analysis-reports/${selectedReportId}` : null,
    false,
  );
  const targets = useApi<AnalysisTarget[]>("/analysis-targets", false);
  const articleParams = new URLSearchParams({
    limit: "20",
    offset: String(offset),
    keyword_match: keywordMatch,
    inclusion,
    ai_relevance: aiRelevance,
    q: queryText,
  });
  const articles = useApi<ReportArticlePage>(
    selectedReportId
      ? `/analysis-reports/${selectedReportId}/articles?${articleParams}`
      : null,
  );
  const detail = useApi<ArticleDetail>(
    detailId && selectedReportId
      ? `/analysis-reports/${selectedReportId}/articles/${detailId}`
      : null,
    false,
  );

  const closeDetail = useCallback(() => {
    setDetailId(null);
    requestAnimationFrame(() => detailTrigger.current?.focus());
  }, []);

  useEffect(() => setText(queryText), [queryText]);
  useEffect(() => {
    if (!report.data || editingLoaded === report.data.id) return;
    setTitle(report.data.title);
    setDescription(report.data.description ?? "");
    setKeywordText(report.data.keyword_terms.join("\n"));
    setStartAt(dateTimeInput(report.data.start_at));
    setEndAt(dateTimeInput(report.data.end_at));
    setRelevanceCriteria(report.data.relevance_criteria ?? "");
    setEditingLoaded(report.data.id);
    setSaveError(null);
  }, [editingLoaded, report.data]);

  const visibleTargets =
    targets.data?.filter(
      (item) => reportKindForTarget(item.kind) === selectedKind,
    ) ?? [];
  const reportTarget = targets.data?.find(
    (item) => item.id === report.data?.target_id,
  );

  useEffect(() => {
    void selectedReportId;
    setSelectedIds([]);
    setDetailId(null);
    setPreview(null);
    setPreviewError(null);
    setDecisionReason("");
    setDeleteConfirmation(null);
    setDeleteError(null);
  }, [selectedReportId]);

  useEffect(() => {
    if (selectedReportId || !targetId || reports.data?.length !== 1) return;
    update({ report_id: reports.data[0].id, target_id: null, offset: 0 });
  }, [reports.data, selectedReportId, targetId, update]);

  function selectReport(id: string) {
    update({ report_id: id, target_id: null, offset: 0 });
  }

  async function deleteReport() {
    if (!deleteConfirmation || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await remove(
        `/analysis-reports/${deleteConfirmation.id}?version=${deleteConfirmation.version}`,
      );
      setDeleteConfirmation(null);
      setSelectedIds([]);
      setDetailId(null);
      setPreview(null);
      update({ report_id: null, target_id: null, offset: 0 });
      await reports.refetch();
    } catch (error) {
      setDeleteError(
        error instanceof Error
          ? error
          : new Error("보고서를 삭제하지 못했어요."),
      );
    } finally {
      setDeleting(false);
    }
  }

  async function saveReport(event: FormEvent) {
    event.preventDefault();
    if (!report.data || saving || !title.trim()) return;
    setSaving(true);
    setSaveError(null);
    try {
      const keywordTerms = keywordText
        .split("\n")
        .map((value) => value.trim())
        .filter(Boolean);
      const keywordChanged =
        keywordTerms.join("\n") !== report.data.keyword_terms.join("\n");
      await put(`/analysis-reports/${report.data.id}`, {
        version: report.data.version,
        title: title.trim(),
        description,
        relevance_criteria: relevanceCriteria,
        start_at: toIso(startAt),
        end_at: toIso(endAt),
        ...(keywordChanged
          ? { keywords_automatic: false, keyword_terms: keywordTerms }
          : {}),
      });
      await Promise.all([
        report.refetch(),
        reports.refetch(),
        articles.refetch(),
      ]);
    } catch (error) {
      setSaveError(
        error instanceof Error ? error : new Error("저장하지 못했어요."),
      );
    } finally {
      setSaving(false);
    }
  }

  async function createReport() {
    if (!newTargetId || creating) return;
    setCreating(true);
    setCreateError(null);
    try {
      const created = await post<AnalysisReport>("/analysis-reports", {
        target_id: newTargetId,
      });
      await reports.refetch();
      setNewTargetId("");
      update({ report_id: created.id, offset: 0 });
    } catch (error) {
      setCreateError(
        error instanceof Error ? error : new Error("보고서를 만들지 못했어요."),
      );
    } finally {
      setCreating(false);
    }
  }

  async function decide(
    article: ReportArticle,
    decision: "include" | "exclude" | "release",
  ) {
    if (!selectedReportId) return;
    setSaveError(null);
    try {
      await put(
        `/analysis-reports/${selectedReportId}/articles/${article.id}/decision`,
        {
          decision,
          reason: decision === "release" ? "" : "보고서 검토",
        },
      );
      await Promise.all([
        articles.refetch(),
        report.refetch(),
        reports.refetch(),
      ]);
    } catch (error) {
      setSaveError(
        error instanceof Error ? error : new Error("판단을 저장하지 못했어요."),
      );
    }
  }

  const scopeBody = (
    scope: "selected" | "filtered",
    mode: "unjudged" | "failed" | "refresh",
  ) => ({
    scope,
    article_ids: scope === "selected" ? selectedIds : [],
    mode,
    keyword_match: keywordMatch,
    inclusion,
    ai_relevance: aiRelevance,
    q: queryText || null,
  });

  async function previewRelevance(
    scope: "selected" | "filtered",
    mode: "unjudged" | "failed" | "refresh",
  ) {
    if (!selectedReportId || (scope === "selected" && !selectedIds.length))
      return;
    setPreviewError(null);
    setPreviewScope(scope);
    setPreviewMode(mode);
    try {
      setPreview(
        await post<RelevancePreview>(
          `/analysis-reports/${selectedReportId}/relevance/preview`,
          scopeBody(scope, mode),
        ),
      );
    } catch (error) {
      setPreviewError(
        error instanceof Error
          ? error
          : new Error("판정 대상을 확인하지 못했어요."),
      );
    }
  }

  async function enqueueRelevance() {
    if (!selectedReportId || !preview || running) return;
    setRunning(true);
    setPreviewError(null);
    try {
      await post(`/analysis-reports/${selectedReportId}/relevance/runs`, {
        ...scopeBody(previewScope, previewMode),
        preview_fingerprint: preview.fingerprint,
      });
      setPreview(null);
      await articles.refetch();
    } catch (error) {
      setPreviewError(
        error instanceof Error ? error : new Error("판정을 시작하지 못했어요."),
      );
    } finally {
      setRunning(false);
    }
  }

  async function bulkDecide(decision: "include" | "exclude" | "release") {
    if (!selectedReportId || !selectedIds.length) return;
    if (decision === "exclude" && !decisionReason.trim()) {
      setSaveError(new Error("제외 사유를 적어 주세요."));
      return;
    }
    try {
      await put(`/analysis-reports/${selectedReportId}/decisions`, {
        article_ids: selectedIds,
        decision,
        reason: decisionReason,
      });
      setSelectedIds([]);
      setDecisionReason("");
      await articles.refetch();
    } catch (error) {
      setSaveError(
        error instanceof Error
          ? error
          : new Error("일괄 판단을 저장하지 못했어요."),
      );
    }
  }

  return (
    <div className="analysis-reports-page">
      <PageHeading
        title="분석 보고서"
        description="보고서별 기사 검토와 포함·제외 판단을 관리합니다."
      />
      <section className="panel">
        <div className="material-tabs" role="tablist" aria-label="분석 종류">
          {reportTabs.map((tab) => (
            <button
              key={tab.value}
              type="button"
              role="tab"
              aria-selected={selectedKind === tab.value}
              className={selectedKind === tab.value ? "active" : ""}
              onClick={() =>
                update({
                  kind: tab.value,
                  report_id: null,
                  target_id: null,
                  offset: 0,
                })
              }
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="report-workspace">
          <aside className="report-list" aria-label="보고서 목록">
            <div className="report-list-heading">
              <strong>보고서</strong>
              <span>{reports.data?.length ?? 0}</span>
            </div>
            {reports.isLoading ? (
              <Loading />
            ) : reports.error ? (
              <ErrorNotice
                error={reports.error}
                retry={() => reports.refetch()}
              />
            ) : reports.data?.length ? (
              <ul>
                {reports.data.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={item.id === selectedReportId ? "active" : ""}
                      onClick={() => selectReport(item.id)}
                    >
                      <strong>{item.title}</strong>
                      <span>
                        {targets.data?.find(
                          (target) => target.id === item.target_id,
                        )?.name ?? "분석 대상"}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <Empty title="생성된 보고서가 없어요" />
            )}
            <div className="report-create">
              <label htmlFor="report-target">새 보고서 대상</label>
              <select
                id="report-target"
                value={newTargetId}
                onChange={(event) => setNewTargetId(event.target.value)}
              >
                <option value="">선택</option>
                {visibleTargets.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              <button
                className="button secondary"
                type="button"
                disabled={!newTargetId || creating}
                onClick={createReport}
              >
                {creating ? "만드는 중" : "보고서 만들기"}
              </button>
              {createError && <p role="alert">{createError.message}</p>}
            </div>
          </aside>
          <div className="report-content">
            {report.error ? (
              <ErrorNotice
                error={report.error}
                retry={() => report.refetch()}
              />
            ) : report.isLoading ? (
              <Loading />
            ) : !report.data ? (
              <Empty title="왼쪽 목록에서 보고서를 선택하세요" />
            ) : (
              <>
                <header className="report-heading">
                  <div className="report-heading-title">
                    <h2>{report.data.title}</h2>
                    <button
                      className="button quiet"
                      type="button"
                      onClick={() => {
                        setDeleteError(null);
                        setDeleteConfirmation(report.data);
                      }}
                    >
                      보고서 삭제
                    </button>
                  </div>
                  <p>{reportTarget?.name ?? "분석 대상"}</p>
                  <p className="report-keyword-summary">
                    검토 키워드 ·{" "}
                    {report.data.keyword_terms.join(" · ") || "미설정"}
                  </p>
                </header>
                <details className="report-settings-panel" key={report.data.id}>
                  <summary>보고서 설정</summary>
                  <form className="report-settings" onSubmit={saveReport}>
                    <div className="field">
                      <label htmlFor="report-title">보고서 제목</label>
                      <input
                        id="report-title"
                        value={title}
                        onChange={(event) => setTitle(event.target.value)}
                        required
                      />
                    </div>
                    <div className="field report-description">
                      <span>분석 대상</span>
                      <strong>{reportTarget?.name ?? "분석 대상"}</strong>
                      {reportTarget?.description && (
                        <small>{reportTarget.description}</small>
                      )}
                    </div>
                    <div className="field">
                      <label htmlFor="report-description">보고서 설명</label>
                      <input
                        id="report-description"
                        value={description}
                        onChange={(event) => setDescription(event.target.value)}
                        maxLength={2000}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="report-keywords">검토 키워드</label>
                      <textarea
                        id="report-keywords"
                        value={keywordText}
                        onChange={(event) => setKeywordText(event.target.value)}
                        placeholder="한 줄에 하나씩 입력"
                      />
                      <p className="hint">
                        제목·최신 본문에 키워드 하나 이상이 있으면 일치로
                        표시합니다. 키워드 필터는 자동 제외가 아닌 검토용입니다.
                      </p>
                      <p className="hint">
                        포함·제외와 해제는 이 보고서에만 적용되며, 원문과 다른
                        보고서의 사용에는 영향을 주지 않습니다.
                      </p>
                    </div>
                    <div className="field">
                      <label htmlFor="relevance-criteria">
                        AI 관련성 판단 기준
                      </label>
                      <textarea
                        id="relevance-criteria"
                        value={relevanceCriteria}
                        onChange={(event) =>
                          setRelevanceCriteria(event.target.value)
                        }
                        placeholder="이 보고서에서 관련 기사로 볼 기준"
                      />
                    </div>
                    <div className="report-period-fields">
                      <div className="field">
                        <label htmlFor="report-start-at">발행시각 시작</label>
                        <input
                          id="report-start-at"
                          type="datetime-local"
                          value={startAt}
                          onChange={(event) => setStartAt(event.target.value)}
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="report-end-at">발행시각 종료</label>
                        <input
                          id="report-end-at"
                          type="datetime-local"
                          value={endAt}
                          onChange={(event) => setEndAt(event.target.value)}
                        />
                      </div>
                      <p className="hint">
                        한국시간 기준이며, 종료 시각은 미만으로 적용합니다.
                      </p>
                    </div>
                    <button
                      className="button"
                      type="submit"
                      disabled={saving || !title.trim()}
                    >
                      {saving ? "저장 중" : "저장"}
                    </button>
                    <button
                      className="button quiet"
                      type="button"
                      disabled={saving || report.data.keywords_automatic}
                      onClick={async () => {
                        setSaving(true);
                        setSaveError(null);
                        try {
                          const restored = await put<AnalysisReport>(
                            `/analysis-reports/${report.data.id}`,
                            {
                              version: report.data.version,
                              keywords_automatic: true,
                            },
                          );
                          setKeywordText(restored.keyword_terms.join("\n"));
                          setEditingLoaded(restored.id);
                          await report.refetch();
                        } catch (error) {
                          setSaveError(
                            error instanceof Error
                              ? error
                              : new Error("자동 키워드를 복원하지 못했어요."),
                          );
                        } finally {
                          setSaving(false);
                        }
                      }}
                    >
                      자동 채움 복원
                    </button>
                    {saveError && <span role="alert">{saveError.message}</span>}
                  </form>
                </details>
                <section className="report-summary" aria-label="기사 수">
                  <span>
                    전체 <strong>{articles.data?.total ?? 0}</strong>
                  </span>
                  <span>
                    일치 <strong>{articles.data?.matched ?? 0}</strong>
                  </span>
                  <span>
                    불일치 <strong>{articles.data?.unmatched ?? 0}</strong>
                  </span>
                  <span>
                    포함 <strong>{articles.data?.included ?? 0}</strong>
                  </span>
                  <span>
                    제외 <strong>{articles.data?.excluded ?? 0}</strong>
                  </span>
                  <span>
                    미검토 <strong>{articles.data?.unreviewed ?? 0}</strong>
                  </span>
                  <span>
                    AI 관련 <strong>{articles.data?.ai_related ?? 0}</strong>
                  </span>
                </section>
                <div className="toolbar report-toolbar">
                  <div
                    className="material-tabs"
                    role="tablist"
                    aria-label="키워드 일치 여부"
                  >
                    {keywordTabs.map((tab) => (
                      <button
                        key={tab.value}
                        type="button"
                        role="tab"
                        disabled={
                          report.data.keyword_terms.length === 0 &&
                          tab.value !== "all"
                        }
                        aria-selected={keywordMatch === tab.value}
                        className={keywordMatch === tab.value ? "active" : ""}
                        onClick={() =>
                          update({
                            keyword_match:
                              tab.value === "all" ? null : tab.value,
                            offset: 0,
                          })
                        }
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>
                  <form
                    className="filters"
                    onSubmit={(event) => {
                      event.preventDefault();
                      update({ q: text, offset: 0 });
                    }}
                  >
                    <select
                      aria-label="보고서 포함 상태"
                      value={inclusion}
                      onChange={(event) =>
                        update({
                          inclusion:
                            event.target.value === "all"
                              ? null
                              : event.target.value,
                          offset: 0,
                        })
                      }
                    >
                      <option value="all">검토 결정 전체</option>
                      <option value="unreviewed">미검토</option>
                      <option value="included">보고서 포함</option>
                      <option value="excluded">보고서 제외</option>
                    </select>
                    <select
                      aria-label="AI 관련성"
                      value={aiRelevance}
                      onChange={(event) =>
                        update({
                          ai_relevance:
                            event.target.value === "all"
                              ? null
                              : event.target.value,
                          offset: 0,
                        })
                      }
                    >
                      <option value="all">AI 관련성 전체</option>
                      <option value="unjudged">미판정</option>
                      <option value="related">관련</option>
                      <option value="unrelated">무관</option>
                      <option value="uncertain">보류</option>
                      <option value="failed">실패</option>
                      <option value="pending">처리 중</option>
                      <option value="outdated">이전 기준</option>
                    </select>
                    <input
                      aria-label="보고서 기사 검색"
                      value={text}
                      onChange={(event) => setText(event.target.value)}
                      placeholder="제목·본문 검색"
                    />
                    <button className="button secondary" type="submit">
                      검색
                    </button>
                  </form>
                </div>
                <div className="report-ai-actions">
                  <button
                    className="button secondary"
                    type="button"
                    onClick={() => previewRelevance("filtered", "unjudged")}
                  >
                    현재조건 미판정 기사 판정
                  </button>
                  <button
                    className="button quiet"
                    type="button"
                    disabled={!selectedIds.length}
                    onClick={() => previewRelevance("selected", "unjudged")}
                  >
                    선택한 {selectedIds.length}건 판정
                  </button>
                  <button
                    className="button quiet"
                    type="button"
                    onClick={() => previewRelevance("filtered", "failed")}
                  >
                    실패 재시도
                  </button>
                </div>
                {articles.error ? (
                  <ErrorNotice
                    error={articles.error}
                    retry={() => articles.refetch()}
                  />
                ) : articles.isLoading ? (
                  <Loading />
                ) : !articles.data?.items.length ? (
                  <Empty title="조건에 맞는 기사가 없어요" />
                ) : (
                  <div className="table-wrap">
                    <table className="article-table report-article-table">
                      <thead>
                        <tr>
                          <th>
                            <input
                              aria-label="현재 페이지 전체 선택"
                              type="checkbox"
                              checked={
                                Boolean(articles.data.items.length) &&
                                articles.data.items.every((article) =>
                                  selectedIds.includes(article.id),
                                )
                              }
                              onChange={(event) =>
                                setSelectedIds(
                                  event.target.checked
                                    ? articles.data.items.map(
                                        (article) => article.id,
                                      )
                                    : [],
                                )
                              }
                            />
                          </th>
                          <th>매체·발행시각</th>
                          <th>기사</th>
                          <th>AI 관련성</th>
                          <th>키워드</th>
                          <th>보고서 판단</th>
                        </tr>
                      </thead>
                      <tbody>
                        {articles.data.items.map((article) => (
                          <tr key={article.id}>
                            <td>
                              <input
                                aria-label={`${article.title} 선택`}
                                type="checkbox"
                                checked={selectedIds.includes(article.id)}
                                onChange={(event) =>
                                  setSelectedIds((current) =>
                                    event.target.checked
                                      ? [...current, article.id]
                                      : current.filter(
                                          (id) => id !== article.id,
                                        ),
                                  )
                                }
                              />
                            </td>
                            <td>
                              <strong>{article.publisher ?? "—"}</strong>
                              <div className="table-sub">
                                {formatDate(article.original_published_at)}
                              </div>
                            </td>
                            <td>
                              <button
                                className="article-link table-title report-article-open"
                                type="button"
                                onClick={(event) => {
                                  detailTrigger.current = event.currentTarget;
                                  setDetailId(article.id);
                                }}
                              >
                                {article.title}
                              </button>
                              <div className="table-sub report-preview">
                                {article.content_preview ??
                                  article.summary ??
                                  "본문 미리보기 없음"}
                              </div>
                            </td>
                            <td>
                              <span
                                className={`ai-status ${article.ai_status}`}
                              >
                                {aiLabel(
                                  article.ai_status,
                                  article.ai_relevance,
                                )}
                              </span>
                            </td>
                            <td>
                              {report.data.keyword_terms.length === 0 ? (
                                <span className="table-sub">키워드 미설정</span>
                              ) : article.matched_keywords.length ? (
                                <div className="terms">
                                  {article.matched_keywords.map((keyword) => (
                                    <span className="term" key={keyword}>
                                      {keyword}
                                    </span>
                                  ))}
                                </div>
                              ) : (
                                <span className="table-sub">불일치</span>
                              )}
                            </td>
                            <td>
                              <div className="report-decision">
                                <span>
                                  {article.report_decision === "include"
                                    ? "포함"
                                    : article.report_decision === "exclude"
                                      ? "제외"
                                      : "미검토"}
                                </span>
                                <div className="button-row">
                                  <button
                                    className="button quiet"
                                    type="button"
                                    onClick={() => decide(article, "include")}
                                  >
                                    포함
                                  </button>
                                  <button
                                    className="button quiet"
                                    type="button"
                                    onClick={() => decide(article, "exclude")}
                                  >
                                    제외
                                  </button>
                                  {article.report_decision && (
                                    <button
                                      className="button quiet"
                                      type="button"
                                      onClick={() => decide(article, "release")}
                                    >
                                      해제
                                    </button>
                                  )}
                                </div>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {selectedIds.length > 0 && (
                  <section
                    className="report-bulk-bar"
                    aria-label="선택 기사 일괄 작업"
                  >
                    <strong>{selectedIds.length}건 선택</strong>
                    <input
                      aria-label="일괄 판단 사유"
                      value={decisionReason}
                      onChange={(event) =>
                        setDecisionReason(event.target.value)
                      }
                      placeholder="제외 사유(제외 시 필수)"
                    />
                    <button
                      className="button quiet"
                      type="button"
                      onClick={() => bulkDecide("include")}
                    >
                      포함
                    </button>
                    <button
                      className="button quiet"
                      type="button"
                      onClick={() => bulkDecide("exclude")}
                    >
                      제외
                    </button>
                    <button
                      className="button quiet"
                      type="button"
                      onClick={() => bulkDecide("release")}
                    >
                      해제
                    </button>
                  </section>
                )}
                <Pager
                  total={articles.data?.filtered_total ?? 0}
                  offset={offset}
                  size={20}
                  onChange={(next) => update({ offset: next })}
                />
                {deleteConfirmation && (
                  <dialog
                    className="report-dialog"
                    ref={(node) => {
                      if (node && !node.open) node.showModal();
                    }}
                    onCancel={(event) => {
                      if (deleting) event.preventDefault();
                      else setDeleteConfirmation(null);
                    }}
                    aria-labelledby="report-delete-title"
                  >
                    <h3 id="report-delete-title">보고서를 삭제할까요?</h3>
                    <p>
                      <strong>{deleteConfirmation.title}</strong>
                    </p>
                    <p>
                      이 보고서의 설정, 검토 결정, AI 판정 이력이 삭제되며
                      복구할 수 없습니다. 대기 중인 AI 판정도 중단됩니다.
                    </p>
                    <p>
                      수집한 기사 원문, 분석 대상, 다른 보고서는 유지됩니다.
                    </p>
                    {deleteError && <p role="alert">{deleteError.message}</p>}
                    <div className="button-row">
                      <button
                        className="button danger-button"
                        type="button"
                        disabled={deleting}
                        onClick={deleteReport}
                      >
                        {deleting ? "삭제 중" : "삭제"}
                      </button>
                      <button
                        className="button quiet"
                        type="button"
                        disabled={deleting}
                        onClick={() => setDeleteConfirmation(null)}
                      >
                        취소
                      </button>
                    </div>
                  </dialog>
                )}
                {preview && (
                  <dialog
                    className="report-dialog"
                    ref={(node) => {
                      if (node && !node.open) node.showModal();
                    }}
                    onCancel={() => setPreview(null)}
                    aria-labelledby="relevance-preview-title"
                  >
                    <h3 id="relevance-preview-title">AI 관련성 판정 확인</h3>
                    <dl>
                      <div>
                        <dt>판정 대상</dt>
                        <dd>{preview.eligible}건</dd>
                      </div>
                      <div>
                        <dt>본문 없음</dt>
                        <dd>{preview.skipped_no_body}건</dd>
                      </div>
                      <div>
                        <dt>제외됨</dt>
                        <dd>{preview.skipped_excluded}건</dd>
                      </div>
                      <div>
                        <dt>이미 최신</dt>
                        <dd>{preview.skipped_current}건</dd>
                      </div>
                      <div>
                        <dt>처리 중</dt>
                        <dd>{preview.pending}건</dd>
                      </div>
                      <div>
                        <dt>예상 토큰</dt>
                        <dd>
                          {preview.estimated_input_tokens +
                            preview.estimated_output_tokens}
                        </dd>
                      </div>
                      <div>
                        <dt>예상 비용</dt>
                        <dd>
                          {preview.estimated_cost_usd == null
                            ? "예상 비용 확인 불가"
                            : `$${preview.estimated_cost_usd}`}
                        </dd>
                      </div>
                    </dl>
                    {previewError && <p role="alert">{previewError.message}</p>}
                    <div className="button-row">
                      <button
                        className="button"
                        type="button"
                        disabled={!preview.eligible || running}
                        onClick={enqueueRelevance}
                      >
                        {running ? "시작 중" : "판정 시작"}
                      </button>
                      <button
                        className="button quiet"
                        type="button"
                        onClick={() => setPreview(null)}
                      >
                        취소
                      </button>
                    </div>
                  </dialog>
                )}
                {detailId && (
                  <dialog
                    className="report-dialog report-detail"
                    ref={(node) => {
                      if (node && !node.open) node.showModal();
                    }}
                    onCancel={closeDetail}
                    aria-labelledby="article-detail-title"
                  >
                    <button
                      className="button quiet"
                      type="button"
                      onClick={closeDetail}
                    >
                      닫기
                    </button>
                    {detail.error ? (
                      <ErrorNotice
                        error={detail.error}
                        retry={() => detail.refetch()}
                      />
                    ) : detail.isLoading ? (
                      <Loading />
                    ) : (
                      detail.data && (
                        <>
                          <h3 id="article-detail-title">{detail.data.title}</h3>
                          <p className="hint">
                            {detail.data.publisher ?? "—"} ·{" "}
                            {formatDate(detail.data.original_published_at)}
                          </p>
                          <p className="article-body">
                            {detail.data.body
                              ? highlightedText(
                                  detail.data.body,
                                  report.data.keyword_terms,
                                )
                              : "본문 없음"}
                          </p>
                          <section>
                            <h4>AI 관련성</h4>
                            <p>
                              {aiLabel(
                                detail.data.ai_status,
                                detail.data.ai_relevance,
                              )}{" "}
                              · {detail.data.ai_reason ?? "판정 근거 없음"}
                            </p>
                            {(detail.data.ai_evidence ?? []).map((item) => (
                              <p key={item} className="term">
                                {item}
                              </p>
                            ))}
                          </section>
                          <section>
                            <h4>사람 검토</h4>
                            <p>
                              {detail.data.report_decision ?? "미검토"} ·{" "}
                              {detail.data.report_decision_reason ??
                                "사유 없음"}
                            </p>
                          </section>
                        </>
                      )
                    )}
                  </dialog>
                )}
              </>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
