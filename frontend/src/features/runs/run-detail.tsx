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
  const [confirmCancel, setConfirmCancel] = useState(false);
  const cache = useQueryClient();
  async function review() {
    setPending(true);
    setError(undefined);
    try {
      await post(`/collection-runs/${id}/review`, {
        reviewed: !query.data?.reviewed_at,
      });
      await cache.invalidateQueries();
    } catch (error) {
      setError(
        error instanceof Error
          ? error
          : new Error("확인 표시를 저장하지 못했어요."),
      );
    } finally {
      setPending(false);
    }
  }
  async function cancel() {
    setPending(true);
    setError(undefined);
    try {
      await post(`/collection-runs/${id}/cancel`, {});
      setConfirmCancel(false);
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
  const repeatLink = (start = run.start_date, end = run.end_date) =>
    `/runs/new?${new URLSearchParams({ rule: run.rule_id ?? "", source: run.source, mode: run.mode === "preview" ? "backfill" : run.mode, start, end, repeat: "1" })}`;
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
        수집 이력
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
              onClick={() => setConfirmCancel(true)}
            >
              {pending ? "요청 중…" : "실행 취소"}
            </button>
          )
        }
      />
      {error && <ErrorNotice error={error} />}
      {confirmCancel && (
        <div className="notice warning" role="alert">
          <span>이 수집을 중단할까요? 이미 확보한 자료는 남아 있어요.</span>
          <button
            className="button secondary"
            type="button"
            disabled={pending}
            onClick={() => setConfirmCancel(false)}
          >
            계속 수집
          </button>
          <button
            className="button danger-button"
            type="button"
            disabled={pending}
            onClick={cancel}
          >
            {pending ? "취소 요청 중…" : "수집 중단"}
          </button>
        </div>
      )}
      {run.error && (
        <div className="notice danger" role="alert">
          <span>
            수집을 마치지 못했어요. 확보한 자료는 남아 있어요. 수집 환경을
            확인하고 다시 요청해 주세요.
          </span>
        </div>
      )}
      {["queued", "submitted"].includes(run.status) && (
        <div className="notice">
          <span>
            요청을 접수했어요. 수집 환경이 준비되면 순서대로 자료를 모아요.{" "}
            <Link href="/workers">수집 환경 확인</Link>
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
      {["failed", "partial"].includes(run.status) && (
        <div className="review-status">
          <div>
            <strong>
              {run.reviewed_at
                ? "확인 완료로 표시한 요청이에요"
                : "아직 확인 완료 표시를 하지 않은 요청이에요"}
            </strong>
            <p className="hint">
              {run.reviewed_at
                ? "수집 결과와 오류 이력은 보존돼요. 다시 대응해야 하면 확인 표시를 되돌릴 수 있어요."
                : "내용을 검토하거나 보충 수집을 요청한 뒤 확인 완료로 표시하면, 첫 화면의 확인 필요 목록에서 제외돼요."}
            </p>
          </div>
          <button
            className="button secondary"
            type="button"
            disabled={pending}
            onClick={review}
          >
            {pending
              ? "저장 중…"
              : run.reviewed_at
                ? "확인 표시 되돌리기"
                : "확인 완료로 표시"}
          </button>
        </div>
      )}
      <div className="context-actions">
        {run.rule_id && (
          <Link href={repeatLink()} className="button">
            같은 채널·기간으로 다시 요청
          </Link>
        )}
        <Link href="/workers" className="button secondary">
          수집 환경 확인
        </Link>
        {run.rule_id && (
          <Link href={`/keywords/${run.rule_id}`} className="button quiet">
            검색 조건 확인
          </Link>
        )}
      </div>
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
            <dt>사용한 검색 조건</dt>
            <dd>
              {run.rule_version
                ? `저장 기록 ${run.rule_version}`
                : "저장 전 미리보기"}
            </dd>
          </div>
          <div>
            <dt>요청 시각</dt>
            <dd>{dateTime(run.created_at)}</dd>
          </div>
          <div>
            <dt>최근 진행 기록</dt>
            <dd>{dateTime(run.updated_at)}</dd>
          </div>
          <div>
            <dt>확인한 검색 페이지</dt>
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
        {(typeof run.summary.stop_reason === "string" || run.error) && (
          <div className="technical-info section-gap">
            {typeof run.summary.stop_reason === "string" && (
              <p>{run.summary.stop_reason}</p>
            )}
            {run.error && <p>{run.error}</p>}
          </div>
        )}
      </section>
      {days.length > 0 && (
        <section className="panel section-gap">
          <div className="panel-header" style={{ paddingBottom: 22 }}>
            <h2>날짜별 수집 범위</h2>
          </div>
          <p className="mobile-table-hint">
            표를 옆으로 밀면 날짜별 보충 수집 버튼을 볼 수 있어요.
          </p>
          <div className="table-wrap">
            <table className="range-table">
              <thead>
                <tr>
                  <th scope="col">날짜</th>
                  <th scope="col">검색 건수</th>
                  <th scope="col">확보 건수</th>
                  <th scope="col">범위 확인</th>
                  <th scope="col">다음 작업</th>
                </tr>
              </thead>
              <tbody>
                {days.map((day) => (
                  <tr key={day.date}>
                    <td>{day.date}</td>
                    <td>{number(day.total_count)}</td>
                    <td>{number(day.retrieved_count)}</td>
                    <td>{day.complete ? "완료" : "미완료"}</td>
                    <td>
                      {!day.complete &&
                        run.rule_id &&
                        run.source === "bigkinds" && (
                          <Link
                            className="button secondary"
                            href={repeatLink(day.date, day.date)}
                          >
                            이 날짜 다시 수집
                          </Link>
                        )}
                    </td>
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
          <Empty
            title={
              run.status === "completed"
                ? "이 조건으로 확보한 자료가 없어요"
                : ["failed", "cancelled"].includes(run.status)
                  ? "이 요청에서 확보한 자료가 없어요"
                  : "아직 표시할 자료가 없어요"
            }
          >
            {run.status === "completed"
              ? "키워드와 조회 기간을 확인해 주세요."
              : ["failed", "cancelled"].includes(run.status)
                ? "조건과 수집 환경을 확인하고 다시 요청할 수 있어요."
                : "수집이 진행되면 확보한 목록이 여기에 표시돼요."}
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
