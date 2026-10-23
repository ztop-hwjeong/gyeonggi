"use client";

import { PlusIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useState } from "react";
import { type Schema, useApi } from "@/shared/api/client";
import { dateTime, sourceNames } from "@/shared/lib/format";
import {
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
  Pager,
} from "@/shared/ui/feedback";

export function KeywordList() {
  const [offset, setOffset] = useState(0);
  const query = useApi<Schema["RulePage"]>(
    `/keyword-rules?limit=20&offset=${offset}`,
  );
  return (
    <>
      <PageHeading
        title="키워드 관리"
        description="함께 검색할 키워드와 채널을 등록하고 수집 주기를 관리해요."
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
        {query.error && !query.data ? null : query.isLoading ? (
          <Loading />
        ) : !query.data?.items.length ? (
          <Empty title="검색 규칙을 등록해 주세요">
            같은 주제의 키워드를 묶어 검색할 수 있어요.{" "}
            <Link href="/keywords/new">첫 키워드 등록</Link>
          </Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">검색 규칙 / 키워드</th>
                    <th scope="col">수집 채널</th>
                    <th scope="col">정기 수집</th>
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
                        {rule.definition.enabled
                          ? `${rule.definition.interval_minutes}분마다`
                          : "일시 중지"}
                        <div className="table-sub">버전 {rule.version}</div>
                      </td>
                      <td className="nowrap">{dateTime(rule.updated_at)}</td>
                      <td>
                        <Link
                          className="button secondary"
                          href={`/runs/new?rule=${rule.id}`}
                        >
                          수집 요청
                        </Link>
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
              onChange={setOffset}
            />
          </>
        )}
      </section>
    </>
  );
}
