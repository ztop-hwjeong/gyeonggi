"use client";

import { PlusIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { type Schema, useApi } from "@/shared/api/client";
import { dateTime, sourceNames } from "@/shared/lib/format";
import { useListLocation } from "@/shared/lib/list-location";
import {
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
  Pager,
} from "@/shared/ui/feedback";

export function KeywordList() {
  const { params, offset, update } = useListLocation();
  const q = params.get("q") ?? "";
  const enabled = params.get("enabled") ?? "";
  const [text, setText] = useState(q);
  useEffect(() => setText(q), [q]);
  const filters = new URLSearchParams({
    limit: "20",
    offset: String(offset),
    q,
  });
  if (enabled) filters.set("enabled", enabled);
  const query = useApi<Schema["RulePage"]>(`/keyword-rules?${filters}`);
  return (
    <>
      <PageHeading
        title="키워드 관리"
        description="함께 검색할 키워드와 채널을 등록하고 자동 수집 사용 여부를 관리해요."
        action={
          <Link className="button" href="/keywords/new">
            <PlusIcon size={18} />
            키워드 등록
          </Link>
        }
      />
      {query.error && (
        <ErrorNotice error={query.error} retry={() => query.refetch()} />
      )}
      <section className="panel">
        <div className="toolbar">
          <form
            className="filters"
            onSubmit={(event) => {
              event.preventDefault();
              update({ q: text });
            }}
          >
            <label className="sr-only" htmlFor="keyword-search">
              이름·키워드 검색
            </label>
            <input
              id="keyword-search"
              placeholder="이름·키워드 검색"
              value={text}
              onChange={(event) => setText(event.target.value)}
              maxLength={100}
            />
            <label className="sr-only" htmlFor="keyword-enabled">
              자동 수집 상태
            </label>
            <select
              id="keyword-enabled"
              value={enabled}
              onChange={(event) => update({ enabled: event.target.value })}
            >
              <option value="">자동 수집 전체</option>
              <option value="true">자동 수집 켜짐</option>
              <option value="false">자동 수집 꺼짐</option>
            </select>
            <button className="button secondary" type="submit">
              검색
            </button>
            {(q || enabled) && (
              <Link className="button quiet" href="/keywords">
                조건 초기화
              </Link>
            )}
          </form>
          <span className="hint">최근 수정순</span>
        </div>
        {query.error && !query.data ? null : query.isLoading ? (
          <Loading />
        ) : !query.data?.items.length ? (
          <Empty
            title={
              q || enabled
                ? "조건에 맞는 검색 조건이 없어요"
                : "검색 조건을 등록해 주세요"
            }
          >
            같은 주제의 키워드를 묶어 검색할 수 있어요.{" "}
            <Link href="/keywords/new">첫 키워드 등록</Link>
          </Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">검색 조건 / 키워드</th>
                    <th scope="col">수집 채널</th>
                    <th scope="col">자동 수집</th>
                    <th scope="col">최근 수정</th>
                    <th scope="col">작업</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.items.map((rule) => (
                    <tr key={rule.id}>
                      <td>
                        <Link
                          className="table-title"
                          href={`/keywords/${rule.id}`}
                        >
                          {rule.definition.name}
                        </Link>
                        <div className="table-sub">
                          {rule.definition.terms.join(" · ")}
                        </div>
                      </td>
                      <td>
                        {rule.definition.sources
                          .map((source) => sourceNames[source])
                          .join(", ")}
                      </td>
                      <td className="nowrap">
                        {rule.definition.enabled ? "켜짐" : "꺼짐"}
                      </td>
                      <td className="nowrap">{dateTime(rule.updated_at)}</td>
                      <td>
                        <div className="button-row">
                          <Link
                            href={`/runs?rule_id=${rule.id}`}
                            className="button quiet"
                          >
                            수집 이력
                          </Link>
                          <Link
                            className="button secondary"
                            href={`/runs/new?rule=${rule.id}`}
                          >
                            수집 요청
                          </Link>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager
              total={query.data.total}
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
