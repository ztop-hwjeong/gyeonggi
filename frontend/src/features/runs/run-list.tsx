"use client";

import { PlusIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { type Schema, useApi } from "@/shared/api/client";
import { modeNames, sourceNames, stateNames } from "@/shared/lib/format";
import { useListLocation } from "@/shared/lib/list-location";
import {
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
  Pager,
} from "@/shared/ui/feedback";
import { RunTable } from "./run-table";

export function RunList() {
  const { params, offset, update } = useListLocation();
  const filters = new URLSearchParams({ limit: "20", offset: String(offset) });
  for (const key of ["status", "mode", "source", "rule_id"]) {
    const value = params.get(key);
    if (value) filters.set(key, value);
  }
  const ruleId = params.get("rule_id");
  const rule = useApi<Schema["RuleInfo"]>(
    ruleId ? `/keyword-rules/${ruleId}` : null,
    false,
  );
  const query = useApi<Schema["RequestPage"]>(`/collection-runs?${filters}`);
  return (
    <>
      <PageHeading
        title="수집 이력"
        description="수집이 어디까지 진행됐는지 확인하고, 오류나 미완료 기간을 다시 수집해요."
        action={
          <Link href="/runs/new" className="button">
            <PlusIcon size={18} />
            수집 요청
          </Link>
        }
      />
      {query.error && (
        <ErrorNotice error={query.error} retry={() => query.refetch()} />
      )}
      <section className="panel">
        <div className="toolbar">
          <div className="filters">
            <label className="sr-only" htmlFor="run-status">
              진행 상태
            </label>
            <select
              id="run-status"
              value={params.get("status") ?? ""}
              onChange={(e) => update({ status: e.target.value })}
            >
              <option value="">전체 상태</option>
              <option value="attention">확인 필요 · 오류 / 일부 수집</option>
              <option value="active">대기 / 진행 중</option>
              {Object.entries(stateNames).map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
            <label className="sr-only" htmlFor="run-source">
              수집 채널
            </label>
            <select
              id="run-source"
              value={params.get("source") ?? ""}
              onChange={(e) => update({ source: e.target.value })}
            >
              <option value="">전체 채널</option>
              {Object.entries(sourceNames).map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
            <label className="sr-only" htmlFor="run-mode">
              수집 종류
            </label>
            <select
              id="run-mode"
              value={params.get("mode") ?? ""}
              onChange={(e) => update({ mode: e.target.value })}
            >
              <option value="">전체 종류</option>
              {Object.entries(modeNames).map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
            {filters.size > 2 && (
              <Link className="button quiet" href="/runs">
                조건 초기화
              </Link>
            )}
          </div>
          <span className="hint">최근 요청순</span>
        </div>
        {ruleId && (
          <p className="filter-context">
            검색 조건: {rule.data?.definition.name ?? "선택한 조건"} ·{" "}
            <Link href="/runs">전체 조건 보기</Link>
          </p>
        )}
        {query.error && !query.data ? null : query.isLoading ? (
          <Loading />
        ) : !query.data?.items.length ? (
          <Empty title="표시할 수집 이력이 없어요">
            선택한 조건을 바꾸거나 새 수집을 요청해 주세요.
          </Empty>
        ) : (
          <>
            <RunTable items={query.data?.items ?? []} />
            <Pager
              total={query.data?.total ?? 0}
              offset={offset}
              size={20}
              onChange={(offset) => update({ offset })}
            />
          </>
        )}
      </section>
    </>
  );
}
