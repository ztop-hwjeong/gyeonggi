"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { type Schema, useApi, useIdempotentPost } from "@/shared/api/client";
import { sourceNames, today } from "@/shared/lib/format";
import { Empty, ErrorNotice, Loading, PageHeading } from "@/shared/ui/feedback";

export function RunCreate({ initialRule = "" }: { initialRule?: string }) {
  const createRequest = useIdempotentPost<Schema["RequestInfo"]>();
  const rules = useApi<Schema["RulePage"]>("/keyword-rules?limit=100", false);
  const [ruleId, setRuleId] = useState(initialRule);
  const detail = useApi<Schema["RuleInfo"]>(
    ruleId ? `/keyword-rules/${ruleId}` : null,
    false,
  );
  const selected =
    detail.data ?? rules.data?.items.find((rule) => rule.id === ruleId);
  const [source, setSource] = useState<Schema["SourceCode"]>("bigkinds");
  const actualSource = selected?.definition.sources.includes(source)
    ? source
    : selected?.definition.sources[0];
  const [mode, setMode] = useState<"backfill" | "incremental">("backfill");
  const actualMode = actualSource === "bigkinds" ? mode : "incremental";
  const [start, setStart] = useState(today),
    [end, setEnd] = useState(today);
  const [pending, setPending] = useState(false),
    [error, setError] = useState<Error>();
  const router = useRouter(),
    cache = useQueryClient();
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!selected || !actualSource) return;
    setPending(true);
    setError(undefined);
    try {
      const result = await createRequest("/collection-runs", {
        rule_id: selected.id,
        version: selected.version,
        source: actualSource,
        mode: actualMode,
        start_date: actualMode === "backfill" ? start : today(),
        end_date: actualMode === "backfill" ? end : today(),
      });
      await cache.invalidateQueries();
      router.push(`/runs/${result.id}`);
    } catch (e) {
      setError(e instanceof Error ? e : new Error("수집을 요청하지 못했어요."));
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <PageHeading
        title="수집 요청"
        description="저장된 검색 규칙으로 수집할 채널과 기간을 선택해요."
      />
      {rules.error && (
        <ErrorNotice error={rules.error} retry={() => rules.refetch()} />
      )}
      {rules.error && !rules.data ? null : rules.isLoading ? (
        <Loading />
      ) : !rules.data?.items.length ? (
        <section className="panel">
          <Empty title="먼저 검색 규칙을 등록해 주세요">
            <Link href="/keywords/new">키워드 등록하기</Link>
          </Empty>
        </section>
      ) : (
        <form className="panel" onSubmit={submit} style={{ maxWidth: 800 }}>
          <div className="form-section form-stack">
            <h2>수집 조건</h2>
            {error && <ErrorNotice error={error} />}
            {detail.error && (
              <ErrorNotice
                error={detail.error}
                retry={() => detail.refetch()}
              />
            )}
            <div className="field">
              <label htmlFor="collect-rule">검색 규칙</label>
              <select
                id="collect-rule"
                value={ruleId}
                required
                onChange={(e) => setRuleId(e.target.value)}
              >
                <option value="">규칙을 선택해 주세요</option>
                {rules.data.items.map((rule) => (
                  <option key={rule.id} value={rule.id}>
                    {rule.definition.name} · v{rule.version}
                  </option>
                ))}
              </select>
            </div>
            {selected && (
              <p className="hint">{selected.definition.terms.join(" · ")}</p>
            )}
            <div className="field">
              <label htmlFor="collect-source">수집 채널</label>
              <select
                id="collect-source"
                required
                value={actualSource ?? ""}
                onChange={(e) =>
                  setSource(e.target.value as Schema["SourceCode"])
                }
              >
                <option value="" disabled>
                  채널을 선택해 주세요
                </option>
                {selected?.definition.sources.map((code) => (
                  <option key={code} value={code}>
                    {sourceNames[code]}
                  </option>
                ))}
              </select>
            </div>
            {actualSource === "bigkinds" ? (
              <>
                <div className="field">
                  <label htmlFor="collect-mode">수집 방식</label>
                  <select
                    id="collect-mode"
                    value={mode}
                    onChange={(e) =>
                      setMode(e.target.value as "backfill" | "incremental")
                    }
                  >
                    <option value="backfill">기간 지정 과거 수집</option>
                    <option value="incremental">오늘 자료 수집</option>
                  </select>
                </div>
                {actualMode === "backfill" && (
                  <div className="field-grid">
                    <div className="field">
                      <label htmlFor="collect-start">시작일</label>
                      <input
                        id="collect-start"
                        type="date"
                        required
                        value={start}
                        max={end}
                        onChange={(e) => setStart(e.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="collect-end">종료일</label>
                      <input
                        id="collect-end"
                        type="date"
                        required
                        value={end}
                        min={start}
                        onChange={(e) => setEnd(e.target.value)}
                      />
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="notice">
                <span>
                  네이버는 마지막 성공 커서 이후의 자료를 최신순으로 수집해요.
                  처음 수집할 때는 최신 첫 페이지로 시작하며, 기간을 지정한 과거
                  수집은 지원하지 않아요.
                </span>
              </div>
            )}
            <p className="hint">
              요청 당시의 규칙 버전으로 실행해요. 과거 수집은 일별로 나눠
              처리하며, 실행 환경과 요청 제한에 따라 시간이 걸릴 수 있어요.
            </p>
          </div>
          <div className="form-actions">
            <Link href="/runs" className="button secondary">
              취소
            </Link>
            <button
              type="submit"
              className="button"
              disabled={pending || !selected || !!detail.error}
            >
              {pending ? "요청 중…" : "수집 요청"}
            </button>
          </div>
        </form>
      )}
    </>
  );
}
