"use client";

import { type FormEvent, useState } from "react";
import { post, put, remove, useApi } from "@/shared/api/client";
import { Empty, ErrorNotice, Loading, PageHeading } from "@/shared/ui/feedback";
import type { AnalysisTarget, FilterRule } from "./types";

const kinds = {
  policy: "정책 분석",
  regular: "정기 보도 분석",
  current_issue: "현안 보도 분석",
  leader_message: "기관장 메시지",
} as const;

async function downloadReport(targetId: string) {
  const dateParts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const datePart = (type: string) =>
    dateParts.find((part) => part.type === type)?.value;
  const analysisDate = `${datePart("year")}-${datePart("month")}-${datePart("day")}`;
  const response = await fetch(
    "/api/analysis/reports/education-audit-press/render",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        analysis_date: analysisDate,
        target_id: targetId,
      }),
    },
  );
  if (!response.ok) throw new Error("보고서를 만들지 못했어요.");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "언론보도-분석.xlsx";
  link.click();
  URL.revokeObjectURL(url);
}

export function TargetManager() {
  const query = useApi<AnalysisTarget[]>("/analysis-targets");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<AnalysisTarget["kind"]>("policy");
  const [description, setDescription] = useState("");
  const [editing, setEditing] = useState<AnalysisTarget | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    if (editing) {
      await put(`/analysis-targets/${editing.id}`, {
        kind,
        name,
        description,
        version: editing.version,
      });
    } else {
      await post("/analysis-targets", { name, kind, description });
    }
    setName("");
    setDescription("");
    setEditing(null);
    await query.refetch();
  }
  return (
    <>
      <PageHeading title="기사 분석 대상 관리" />
      <section className="panel panel-body">
        <form className="form-stack" onSubmit={submit}>
          <div className="field">
            <label htmlFor="target-kind">분석 목적</label>
            <select
              id="target-kind"
              value={kind}
              onChange={(event) =>
                setKind(event.target.value as AnalysisTarget["kind"])
              }
            >
              {Object.entries(kinds).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="target-name">이름</label>
            <input
              id="target-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="예: 교권 보호 정책"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="target-description">설명</label>
            <input
              id="target-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="필요한 경우만 입력"
            />
          </div>
          <div>
            <button className="button" type="submit">
              {editing ? "수정 저장" : "추가"}
            </button>
            {editing && (
              <button
                className="button quiet"
                type="button"
                onClick={() => {
                  setEditing(null);
                  setName("");
                  setDescription("");
                }}
              >
                취소
              </button>
            )}
          </div>
        </form>
      </section>
      {query.error ? (
        <ErrorNotice error={query.error} retry={() => query.refetch()} />
      ) : query.isLoading ? (
        <Loading />
      ) : !query.data?.length ? (
        <Empty title="등록한 분석 대상이 없어요" />
      ) : (
        <section className="panel section-gap">
          <ul className="management-list">
            {query.data.map((target) => (
              <li key={target.id}>
                <div>
                  <strong>{target.name}</strong>
                  <span>{kinds[target.kind]}</span>
                  {target.description && <span>{target.description}</span>}
                </div>
                <div className="button-row">
                  <button
                    className="button quiet"
                    type="button"
                    onClick={() => downloadReport(target.id)}
                  >
                    보고서 다운로드
                  </button>
                  <button
                    className="button quiet"
                    type="button"
                    onClick={() => {
                      setEditing(target);
                      setName(target.name);
                      setKind(target.kind);
                      setDescription(target.description);
                    }}
                  >
                    수정
                  </button>
                  <button
                    className="button quiet"
                    type="button"
                    onClick={async () => {
                      await remove(
                        `/analysis-targets/${target.id}?version=${target.version}`,
                      );
                      await query.refetch();
                    }}
                  >
                    삭제
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function keywords(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function FilterRuleManager() {
  const query = useApi<FilterRule[]>("/article-filter-rules");
  const targets = useApi<AnalysisTarget[]>("/analysis-targets", false);
  const [name, setName] = useState("");
  const [decision, setDecision] = useState<"include" | "exclude">("include");
  const [priority, setPriority] = useState("100");
  const [all, setAll] = useState("");
  const [any, setAny] = useState("");
  const [none, setNone] = useState("");
  const [targetId, setTargetId] = useState("");
  const [editing, setEditing] = useState<FilterRule | null>(null);
  const [reapplyMessage, setReapplyMessage] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    const body = {
      name,
      decision,
      priority: Number(priority),
      conditions: {
        all: keywords(all),
        any: keywords(any),
        none: keywords(none),
      },
      target_id: targetId || null,
      enabled: true,
    };
    if (editing) {
      await put(`/article-filter-rules/${editing.id}`, {
        ...body,
        version: editing.version,
      });
    } else {
      await post("/article-filter-rules", body);
    }
    setName("");
    setAll("");
    setAny("");
    setNone("");
    setEditing(null);
    await query.refetch();
  }
  async function reapply() {
    const body = targetId
      ? { scope: "target", target_id: targetId }
      : { scope: "all" };
    const result = await post<{ processed_count: number }>(
      "/article-filter-rules/reapply",
      body,
    );
    setReapplyMessage(
      `${result.processed_count.toLocaleString("ko-KR")}건에 적용했어요.`,
    );
  }
  return (
    <>
      <PageHeading title="기사 분석 규칙 관리" />
      <section className="panel panel-body">
        <form className="form-stack" onSubmit={submit}>
          <div className="field">
            <label htmlFor="rule-name">규칙 이름</label>
            <input
              id="rule-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="예: 교육청 언급 기사"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="rule-target">적용할 분석 대상</label>
            <select
              id="rule-target"
              value={targetId}
              onChange={(event) => setTargetId(event.target.value)}
            >
              <option value="">전체 기사</option>
              {targets.data?.map((target) => (
                <option key={target.id} value={target.id}>
                  {target.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="rule-decision">판단</label>
            <select
              id="rule-decision"
              value={decision}
              onChange={(event) =>
                setDecision(event.target.value as "include" | "exclude")
              }
            >
              <option value="include">분석에 포함</option>
              <option value="exclude">분석에서 제외</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="rule-priority">우선순위</label>
            <input
              id="rule-priority"
              type="number"
              value={priority}
              onChange={(event) => setPriority(event.target.value)}
              min="0"
            />
          </div>
          <div className="field">
            <label htmlFor="rule-all">모두 포함할 말</label>
            <input
              id="rule-all"
              value={all}
              onChange={(event) => setAll(event.target.value)}
              placeholder="쉼표로 구분"
            />
          </div>
          <div className="field">
            <label htmlFor="rule-any">하나 이상 포함할 말</label>
            <input
              id="rule-any"
              value={any}
              onChange={(event) => setAny(event.target.value)}
              placeholder="쉼표로 구분"
            />
          </div>
          <div className="field">
            <label htmlFor="rule-none">포함하지 않을 말</label>
            <input
              id="rule-none"
              value={none}
              onChange={(event) => setNone(event.target.value)}
              placeholder="쉼표로 구분"
            />
          </div>
          <div className="button-row">
            <button className="button" type="submit">
              {editing ? "수정 저장" : "규칙 추가"}
            </button>
            {editing && (
              <button
                className="button quiet"
                type="button"
                onClick={() => {
                  setEditing(null);
                  setName("");
                  setAll("");
                  setAny("");
                  setNone("");
                }}
              >
                취소
              </button>
            )}
            <button
              className="button secondary"
              type="button"
              onClick={reapply}
            >
              규칙 다시 적용
            </button>
            {reapplyMessage && <span role="status">{reapplyMessage}</span>}
          </div>
          <p className="hint">
            {targetId
              ? "선택한 분석 대상의 기존 기사에 적용"
              : "전체 기존 기사에 적용"}
          </p>
        </form>
      </section>
      {query.error ? (
        <ErrorNotice error={query.error} retry={() => query.refetch()} />
      ) : query.isLoading ? (
        <Loading />
      ) : !query.data?.length ? (
        <Empty title="등록한 분석 규칙이 없어요" />
      ) : (
        <section className="panel section-gap">
          <ul className="management-list">
            {query.data.map((rule) => (
              <li key={rule.id}>
                <div>
                  <strong>{rule.name}</strong>
                  <span>
                    {rule.decision === "include" ? "포함" : "제외"} · 우선순위{" "}
                    {rule.priority}
                  </span>
                </div>
                <button
                  className="button quiet"
                  type="button"
                  onClick={() => {
                    setEditing(rule);
                    setName(rule.name);
                    setDecision(rule.decision);
                    setPriority(String(rule.priority));
                    setTargetId(rule.target_id ?? "");
                    setAll((rule.conditions.all ?? []).join(", "));
                    setAny((rule.conditions.any ?? []).join(", "));
                    setNone((rule.conditions.none ?? []).join(", "));
                  }}
                >
                  수정
                </button>
                <button
                  className="button quiet"
                  type="button"
                  onClick={async () => {
                    await remove(
                      `/article-filter-rules/${rule.id}?version=${rule.version}`,
                    );
                    await query.refetch();
                  }}
                >
                  삭제
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
