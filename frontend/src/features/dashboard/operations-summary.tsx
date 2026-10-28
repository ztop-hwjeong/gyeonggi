"use client";
import { ArrowRightIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { type Schema, useApi } from "@/shared/api/client";
import { number } from "@/shared/lib/format";
import { ErrorNotice, Loading } from "@/shared/ui/feedback";

export function OperationsSummary({ data }: { data: Schema["Overview"] }) {
  const attention = useApi<Schema["RequestPage"]>(
    "/collection-runs?limit=5&status=attention",
  );
  const workers = useApi<Schema["WorkerSnapshot"]>("/monitoring/workers");
  const pool = workers.data?.pools.find(
    (pool) => pool.name === "docker-collector",
  );
  const unavailable =
    workers.data &&
    (!pool ||
      pool.is_paused ||
      !pool.workers.some((worker) => worker.status === "ONLINE"));
  return (
    <section className="panel operations-focus">
      <div className="panel-header">
        <h2>먼저 확인해 주세요</h2>
        <Link href="/runs?status=attention" className="button quiet">
          확인 필요한 이력 <ArrowRightIcon size={16} />
        </Link>
      </div>
      <div className="panel-body">
        {data.body_skipped_articles > 0 && (
          <p className="hint">
            본문 없음으로 건너뛴 기사 {number(data.body_skipped_articles)}건 ·
            본문 분석 제외
          </p>
        )}
        {data.total_rules === 0 ? (
          <div className="action-row">
            <div>
              <h3>수집할 키워드를 등록해 주세요</h3>
            </div>
            <Link className="button" href="/keywords/new">
              첫 검색 조건 만들기
            </Link>
          </div>
        ) : data.active_rules === 0 ? (
          <div className="action-row">
            <div>
              <h3>자동 수집이 모두 꺼져 있어요</h3>
            </div>
            <Link className="button secondary" href="/keywords">
              검색 조건 확인
            </Link>
          </div>
        ) : (
          <p className="hint">
            검색 조건 {data.active_rules}개로 자동 수집을 사용하고 있어요.
          </p>
        )}
        {workers.error ? (
          <ErrorNotice error={workers.error} retry={() => workers.refetch()} />
        ) : workers.isLoading ? (
          <Loading />
        ) : unavailable ? (
          <div className="action-row">
            <div>
              <h3>수집 연결 대기</h3>
            </div>
            <Link className="button secondary" href="/workers">
              수집 환경 확인
            </Link>
          </div>
        ) : null}
        {attention.error ? (
          <ErrorNotice
            error={attention.error}
            retry={() => attention.refetch()}
          />
        ) : attention.isLoading ? (
          <Loading />
        ) : attention.data?.total ? (
          <div className="action-row">
            <div>
              <h3>
                오류 또는 일부만 수집된 요청 {number(attention.data.total)}건
              </h3>
            </div>
            <Link className="button secondary" href="/runs?status=attention">
              확인하고 대응
            </Link>
          </div>
        ) : null}
      </div>
    </section>
  );
}
