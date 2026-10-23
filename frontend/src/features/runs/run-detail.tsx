"use client";

import { ArrowLeftIcon } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { post, type Schema, useApi } from "@/shared/api/client";
import {
  dateTime,
  modeNames,
  number,
  safeUrl,
  sourceNames,
} from "@/shared/lib/format";
import {
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
  Pager,
  State,
} from "@/shared/ui/feedback";

export function RunDetail({ id }: { id: string }) {
  const query = useApi<Schema["RequestInfo"]>(`/collection-runs/${id}`);
  const [offset, setOffset] = useState(0);
  const results = useApi<Schema["ResultPage"]>(
    `/collection-runs/${id}/items?limit=20&offset=${offset}`,
  );
  const [pending, setPending] = useState(false),
    [error, setError] = useState<Error>();
  const cache = useQueryClient();
  async function cancel() {
    setPending(true);
    setError(undefined);
    try {
      await post(`/collection-runs/${id}/cancel`, {});
      await cache.invalidateQueries();
    } catch (e) {
      setError(e instanceof Error ? e : new Error("취소하지 못했어요."));
    } finally {
      setPending(false);
    }
  }
  if (query.error)
    return <ErrorNotice error={query.error} retry={() => query.refetch()} />;
  if (!query.data) return <Loading />;
  const run = query.data;
  const days = Array.isArray(run.summary.days)
    ? (run.summary.days as {
        date: string;
        total_count: number;
        retrieved_count: number;
        complete: boolean;
      }[])
    : [];
  return (
    <>
      <Link href="/runs" className="back-link">
        <ArrowLeftIcon size={16} />
        수집 실행 목록
      </Link>
      <PageHeading
        title={run.definition.name}
        description={`${sourceNames[run.source]} · ${modeNames[run.mode]} · ${run.start_date} ~ ${run.end_date}`}
        action={
          ["queued", "submitted", "running"].includes(run.status) && (
            <button
              type="button"
              className="button danger-button"
              disabled={pending}
              onClick={cancel}
            >
              {pending ? "요청 중…" : "실행 취소"}
            </button>
          )
        }
      />
      {error && <ErrorNotice error={error} />}
      {run.error && (
        <div className="notice danger" role="alert">
          <span>
            수집 중 문제가 발생했어요. {run.error} · 확보한 결과는 보존돼요.
          </span>
        </div>
      )}
      {["queued", "submitted"].includes(run.status) && (
        <div className="notice">
          <span>
            요청을 접수했어요. Dispatcher와 Worker가 연결되면 순서대로 실행해요.{" "}
            <Link href="/workers">실행 환경 확인</Link>
          </span>
        </div>
      )}
      {run.status === "partial" && (
        <div className="notice warning">
          <span>
            요청 범위의 일부만 확보했어요. 아래 날짜별 범위와 확보 건수를 확인한
            뒤 미완료 기간을 다시 요청해 주세요.
          </span>
        </div>
      )}
      <section className="panel panel-body">
        <dl className="detail-facts">
          <div>
            <dt>진행 상태</dt>
            <dd>
              <State value={run.status} />
            </dd>
          </div>
          <div>
            <dt>확보 / 검색 건수</dt>
            <dd>
              {number(run.summary.retrieved_count as number)} /{" "}
              {number(run.summary.total_count as number)}건
            </dd>
          </div>
          <div>
            <dt>규칙 버전</dt>
            <dd>
              {run.rule_version
                ? `버전 ${run.rule_version}`
                : "저장 전 미리보기"}
            </dd>
          </div>
          <div>
            <dt>요청 시각</dt>
            <dd>{dateTime(run.created_at)}</dd>
          </div>
          <div>
            <dt>최근 상태 확인</dt>
            <dd>{dateTime(run.updated_at)}</dd>
          </div>
          <div>
            <dt>조회 페이지</dt>
            <dd>{number(run.summary.pages_collected as number)}</dd>
          </div>
        </dl>
        <div className="terms section-gap">
          {run.definition.terms.map((term) => (
            <span className="term" key={term}>
              {term}
            </span>
          ))}
        </div>
        {typeof run.summary.stop_reason === "string" && (
          <p className="hint section-gap">{String(run.summary.stop_reason)}</p>
        )}
        {run.rule_id && (
          <Link
            href={`/runs/new?rule=${run.rule_id}`}
            className="button secondary section-gap"
          >
            이 규칙으로 수집 요청
          </Link>
        )}
      </section>
      {days.length > 0 && (
        <section className="panel section-gap">
          <div className="panel-header" style={{ paddingBottom: 22 }}>
            <h2>날짜별 수집 범위</h2>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">날짜</th>
                  <th scope="col">검색 건수</th>
                  <th scope="col">확보 건수</th>
                  <th scope="col">범위 확인</th>
                </tr>
              </thead>
              <tbody>
                {days.map((day) => (
                  <tr key={day.date}>
                    <td>{day.date}</td>
                    <td>{number(day.total_count)}</td>
                    <td>{number(day.retrieved_count)}</td>
                    <td>{day.complete ? "완료" : "미완료"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <section className="panel section-gap">
        <div className="panel-header" style={{ paddingBottom: 22 }}>
          <h2>{run.mode === "preview" ? "미리보기 결과" : "확보한 자료"}</h2>
        </div>
        {results.error ? (
          <div className="panel-body">
            <ErrorNotice
              error={results.error}
              retry={() => results.refetch()}
            />
          </div>
        ) : results.isLoading ? (
          <Loading />
        ) : !results.data?.items.length ? (
          <Empty title="아직 표시할 자료가 없어요">
            수집이 진행되면 확보한 목록이 여기에 표시돼요.
          </Empty>
        ) : (
          <ul className="article-list">
            {results.data.items.map((item) => (
              <li key={item.source_id}>
                <div className="article-meta">
                  <span>{item.publisher ?? sourceNames[run.source]}</span>
                  <span>
                    {item.published_on ?? dateTime(item.published_at)}
                  </span>
                </div>
                <h2>
                  {safeUrl(item.original_url ?? item.url) ? (
                    <a
                      className="article-link"
                      href={safeUrl(item.original_url ?? item.url)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {item.title}
                    </a>
                  ) : (
                    item.title
                  )}
                </h2>
                <p>{item.summary}</p>
              </li>
            ))}
          </ul>
        )}
        <Pager
          total={results.data?.total ?? 0}
          offset={offset}
          size={20}
          onChange={setOffset}
        />
      </section>
    </>
  );
}
